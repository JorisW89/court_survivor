import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Game, GameParticipant, Group, GroupMember, Pick, Player, Round, Tournament, User
from ..models import Match as MatchModel
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
from ..services.game_engine import get_pick_points_breakdown

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
def get_group_by_invite(invite_code: str, db: Session = Depends(get_db)):
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

    return GroupDetailResponse(
        id=group.id,
        name=group.name,
        invite_code=group.invite_code,
        created_by=group.created_by,
        created_at=group.created_at,
        members=[
            GroupMemberResponse(
                user_id=m.user_id,
                username=db.get(User, m.user_id).username,
                joined_at=m.joined_at,
            )
            for m in group.members
            if db.get(User, m.user_id)
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

    result = []
    for game in active_games:
        tournament = db.get(Tournament, game.tournament_id)
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
        for p in participants:
            user = db.get(User, p.user_id)
            if not user:
                continue
            entries.append(LeaderboardEntry(
                rank=rank,
                user_id=p.user_id,
                username=user.username,
                total_points=p.total_points,
            ))
            rank += 1

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

    result_games = []
    for game in games:
        picks = (
            db.query(Pick)
            .filter(Pick.game_id == game.id, Pick.user_id == user_id)
            .all()
        )

        pick_summaries = []
        for pick in picks:
            r = db.get(Round, pick.round_id)
            if not r or r.status != "completed":
                continue
            player = db.get(Player, pick.player_id)
            if not player:
                continue
            streak_points, ranking_bonus, player_rank, opponent_rank = get_pick_points_breakdown(db, pick)
            match = db.query(MatchModel).filter(
                MatchModel.round_id == pick.round_id,
                (MatchModel.player1_id == pick.player_id) | (MatchModel.player2_id == pick.player_id),
            ).first()
            opponent_name = None
            if match:
                opp_id = match.player2_id if match.player1_id == pick.player_id else match.player1_id
                opp = db.get(Player, opp_id) if opp_id else None
                opponent_name = opp.name if opp else None
            pick_summaries.append(PickSummary(
                round_id=pick.round_id,
                round_name=r.name,
                round_order=r.round_order,
                player_id=pick.player_id,
                player_name=player.name,
                is_correct=pick.is_correct,
                points_awarded=pick.points_awarded,
                streak_points=streak_points,
                ranking_bonus=ranking_bonus,
                player_rank=player_rank,
                opponent_rank=opponent_rank,
                opponent_name=opponent_name,
            ))

        if pick_summaries:
            pick_summaries.sort(key=lambda x: x.round_order)
            tournament = db.get(Tournament, game.tournament_id)
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
