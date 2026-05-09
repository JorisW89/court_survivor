import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Game, GameParticipant, Group, GroupMember, Pick, Player, Round, Tournament, TournamentRankingSnapshot, User
from ..models import Match as MatchModel
from ..player_utils import normalize_player_name
from ..schemas import (
    GroupCreate,
    GroupDetailResponse,
    GroupLeaderboardEntry,
    GroupMemberResponse,
    GroupResponse,
    LeaderboardEntry,
    MemberPicksForGame,
    MemberPicksResponse,
    PickSummary,
)
from ..services.game_engine import calculate_ranking_bonus

router = APIRouter()


def _group_response(group: Group, db: Session) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        invite_code=group.invite_code,
        created_by=group.created_by,
        created_at=group.created_at,
        member_count=len(group.members),
    )


@router.post("", response_model=GroupResponse)
def create_group(
    payload: GroupCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = Group(
        name=payload.name,
        invite_code=secrets.token_urlsafe(8),
        created_by=current_user.id,
    )
    db.add(group)
    db.flush()

    member = GroupMember(group_id=group.id, user_id=current_user.id)
    db.add(member)
    db.commit()
    db.refresh(group)

    return _group_response(group, db)


@router.get("", response_model=list[GroupResponse])
def list_my_groups(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    memberships = db.query(GroupMember).filter(GroupMember.user_id == current_user.id).all()
    groups = [db.get(Group, m.group_id) for m in memberships]
    return [_group_response(g, db) for g in groups if g]


@router.get("/join/{invite_code}", response_model=GroupResponse)
def get_group_by_invite(
    invite_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.query(Group).filter(Group.invite_code == invite_code).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return _group_response(group, db)


@router.post("/join/{invite_code}", response_model=GroupResponse)
def join_group(
    invite_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.query(Group).filter(Group.invite_code == invite_code).first()
    if not group:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    existing = db.query(GroupMember).filter(
        GroupMember.group_id == group.id,
        GroupMember.user_id == current_user.id,
    ).first()
    if existing:
        return _group_response(group, db)

    member = GroupMember(group_id=group.id, user_id=current_user.id)
    db.add(member)
    db.commit()
    db.refresh(group)

    return _group_response(group, db)


@router.get("/{group_id}", response_model=GroupDetailResponse)
def get_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id,
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    member_user_ids = [m.user_id for m in group.members]
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(member_user_ids)).all()}

    return GroupDetailResponse(
        id=group.id,
        name=group.name,
        invite_code=group.invite_code,
        created_by=group.created_by,
        created_at=group.created_at,
        members=[
            GroupMemberResponse(
                user_id=m.user_id,
                username=users_map[m.user_id].username,
                joined_at=m.joined_at,
            )
            for m in group.members
            if m.user_id in users_map
        ],
    )


@router.get("/{group_id}/leaderboard", response_model=list[GroupLeaderboardEntry])
def get_group_leaderboard(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id,
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    member_user_ids = {m.user_id for m in group.members}

    active_games = (
        db.query(Game)
        .join(Tournament)
        .filter(Game.status.in_(["upcoming", "active"]))
        .order_by(Tournament.start_date, Game.division)
        .all()
    )

    # Batch-fetch tournaments and member users up front
    tournament_ids = {game.tournament_id for game in active_games}
    tournaments_map = {
        t.id: t for t in db.query(Tournament).filter(Tournament.id.in_(tournament_ids)).all()
    }
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(member_user_ids)).all()}

    result = []
    for game in active_games:
        participants = (
            db.query(GameParticipant)
            .filter(
                GameParticipant.game_id == game.id,
                GameParticipant.user_id.in_(member_user_ids),
            )
            .order_by(GameParticipant.total_points.desc(), GameParticipant.joined_at)
            .all()
        )

        if not participants:
            continue

        entries = []
        rank = 1
        prev_points = None
        for p in participants:
            user = users_map.get(p.user_id)
            if not user:
                continue
            if prev_points is not None and p.total_points < prev_points:
                rank = len(entries) + 1
            prev_points = p.total_points
            entries.append(LeaderboardEntry(
                rank=rank,
                user_id=p.user_id,
                username=user.username,
                total_points=p.total_points,
            ))

        tournament = tournaments_map.get(game.tournament_id)
        result.append(GroupLeaderboardEntry(
            game_id=game.id,
            tournament_title=tournament.title if tournament else "Unknown",
            division=game.division,
            entries=entries,
        ))

    return result


@router.get("/{group_id}/members/{user_id}/picks", response_model=MemberPicksResponse)
def get_member_picks(
    group_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = db.get(Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")

    is_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id,
    ).first()
    if not is_member:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    target_member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == user_id,
    ).first()
    if not target_member:
        raise HTTPException(status_code=404, detail="User not in group")

    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    games = (
        db.query(Game)
        .join(Tournament)
        .filter(Game.status.in_(["upcoming", "active"]))
        .order_by(Tournament.start_date, Game.division)
        .all()
    )

    # Batch-fetch all picks for this user across all games in one query
    game_ids = [game.id for game in games]
    all_picks = (
        db.query(Pick)
        .filter(Pick.game_id.in_(game_ids), Pick.user_id == user_id)
        .all()
    )
    picks_by_game: dict[int, list[Pick]] = {}
    all_round_ids: set[int] = set()
    all_player_ids: set[int] = set()
    for pick in all_picks:
        picks_by_game.setdefault(pick.game_id, []).append(pick)
        all_round_ids.add(pick.round_id)
        all_player_ids.add(pick.player_id)

    rounds_map = {r.id: r for r in db.query(Round).filter(Round.id.in_(all_round_ids)).all()} if all_round_ids else {}
    players_map = {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(all_player_ids)).all()} if all_player_ids else {}

    # Fetch all matches for all relevant rounds
    all_matches = db.query(MatchModel).filter(MatchModel.round_id.in_(all_round_ids)).all() if all_round_ids else []
    matches_by_round: dict[int, list] = {}
    opp_ids: set[int] = set()
    pick_match_map: dict[int, MatchModel] = {}
    for m in all_matches:
        matches_by_round.setdefault(m.round_id, []).append(m)
    for pick in all_picks:
        for m in matches_by_round.get(pick.round_id, []):
            if m.player1_id == pick.player_id or m.player2_id == pick.player_id:
                pick_match_map[pick.id] = m
                opp_id = m.player2_id if m.player1_id == pick.player_id else m.player1_id
                if opp_id:
                    opp_ids.add(opp_id)
                break
    missing = opp_ids - set(players_map.keys())
    if missing:
        players_map.update({pl.id: pl for pl in db.query(Player).filter(Player.id.in_(missing)).all()})

    # Build per-tournament snapshot maps (one query per unique tournament+division)
    tournament_ids = {game.tournament_id for game in games}
    tournaments_map = {t.id: t for t in db.query(Tournament).filter(Tournament.id.in_(tournament_ids)).all()}
    game_division_map = {game.id: (game.tournament_id, game.division) for game in games}

    snapshots_by_tournament: dict[tuple[int, str], dict[str, int]] = {}
    for t_id in tournament_ids:
        for division in {game.division for game in games if game.tournament_id == t_id}:
            snapshots_by_tournament[(t_id, division)] = {
                s.normalized_name: s.rank
                for s in db.query(TournamentRankingSnapshot).filter(
                    TournamentRankingSnapshot.tournament_id == t_id,
                    TournamentRankingSnapshot.division == division,
                ).all()
            }

    result_games = []
    for game in games:
        picks = picks_by_game.get(game.id, [])
        t_id, division = game_division_map[game.id]
        snapshot_map = snapshots_by_tournament.get((t_id, division), {})

        pick_summaries = []
        for pick in picks:
            r = rounds_map.get(pick.round_id)
            if not r or r.status != "completed":
                continue
            player = players_map.get(pick.player_id)
            if not player:
                continue
            match = pick_match_map.get(pick.id)
            opp_id = None
            if match:
                opp_id = match.player2_id if match.player1_id == pick.player_id else match.player1_id
            opponent = players_map.get(opp_id) if opp_id else None
            player_rank = snapshot_map.get(normalize_player_name(player.name))
            opponent_rank = snapshot_map.get(normalize_player_name(opponent.name)) if opponent else None
            ranking_bonus = calculate_ranking_bonus(player_rank, opponent_rank)
            streak_points = max(0, pick.points_awarded - ranking_bonus) if pick.is_correct is True else 0
            pick_summaries.append(PickSummary(
                round_id=pick.round_id,
                round_name=r.name,
                round_order=r.round_order,
                player_id=pick.player_id,
                player_name=player.name,
                is_correct=pick.is_correct,
                points_awarded=pick.points_awarded,
                streak_points=streak_points,
                ranking_bonus=ranking_bonus if pick.is_correct is True else 0,
                player_rank=player_rank,
                opponent_rank=opponent_rank,
                opponent_name=opponent.name if opponent else None,
            ))

        if pick_summaries:
            pick_summaries.sort(key=lambda x: x.round_order)
            tournament = tournaments_map.get(game.tournament_id)
            result_games.append(MemberPicksForGame(
                game_id=game.id,
                tournament_title=tournament.title if tournament else "Unknown",
                division=game.division,
                picks=pick_summaries,
            ))

    return MemberPicksResponse(
        user_id=user_id,
        username=target_user.username,
        games=result_games,
    )


@router.delete("/{group_id}/leave")
def leave_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(GroupMember).filter(
        GroupMember.group_id == group_id,
        GroupMember.user_id == current_user.id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Not a member")

    db.delete(member)
    db.commit()
    return {"message": "Left group"}
