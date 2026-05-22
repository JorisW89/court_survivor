from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_optional_user
from ..database import get_db
from ..models import Game, GameParticipant, Pick, Player, Round, Tournament, TournamentRankingSnapshot, User
from ..models import Match as MatchModel
from ..player_utils import normalize_player_name
from ..schemas import (
    DrawResponse,
    GameResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    MatchForPick,
    MatchResult,
    MyParticipant,
    PickSummary,
    PlayerForPick,
    RoundResponse,
    RoundResult,
    RoundWithMatches,
    TournamentResponse,
)
from ..services.game_engine import get_current_round
from ..services.game_engine import (
    calculate_ranking_bonus,
    get_current_streak,
    get_pick_points_breakdown,
    get_player_snapshot_rank,
    get_projected_streak_points,
)
from ..time_utils import as_utc, is_locked_before

router = APIRouter()


def _serialize_match_time(match_time):
    if not match_time:
        return None
    return as_utc(match_time).isoformat().replace("+00:00", "Z")


def _build_game_response(db: Session, game: Game, user: Optional[User]) -> GameResponse:
    tournament = db.get(Tournament, game.tournament_id)

    current_round = get_current_round(db, game.tournament_id, game.division)

    participants = db.query(GameParticipant).filter(GameParticipant.game_id == game.id).all()
    participant_count = len(participants)

    my_participant = None
    if user:
        p = next((x for x in participants if x.user_id == user.id), None)
        if p:
            picks = (
                db.query(Pick)
                .filter(Pick.game_id == game.id, Pick.user_id == user.id)
                .all()
            )
            pick_summaries = []
            if picks:
                round_ids = {pick.round_id for pick in picks}
                player_ids = {pick.player_id for pick in picks}
                rounds_map = {r.id: r for r in db.query(Round).filter(Round.id.in_(round_ids)).all()}
                players_map = {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(player_ids)).all()}

                all_round_matches = db.query(MatchModel).filter(MatchModel.round_id.in_(round_ids)).all()
                matches_by_round: dict[int, list] = {}
                for m in all_round_matches:
                    matches_by_round.setdefault(m.round_id, []).append(m)

                pick_match_map: dict[int, MatchModel] = {}
                opp_ids: set[int] = set()
                for pick in picks:
                    for m in matches_by_round.get(pick.round_id, []):
                        if m.player1_id == pick.player_id or m.player2_id == pick.player_id:
                            pick_match_map[pick.id] = m
                            opp_id = m.player2_id if m.player1_id == pick.player_id else m.player1_id
                            if opp_id:
                                opp_ids.add(opp_id)
                            break
                missing = opp_ids - set(players_map.keys())
                if missing:
                    players_map.update(
                        {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(missing)).all()}
                    )

                snapshot_map = {
                    s.normalized_name: s.rank
                    for s in db.query(TournamentRankingSnapshot).filter(
                        TournamentRankingSnapshot.tournament_id == game.tournament_id,
                        TournamentRankingSnapshot.division == game.division,
                    ).all()
                }

                for pick in picks:
                    r = rounds_map.get(pick.round_id)
                    player = players_map.get(pick.player_id)
                    if not r or not player:
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
            pick_summaries.sort(key=lambda x: x.round_order)

            # If the user's pick for the current round is already resolved, advance
            # current_round to the next round so the card and detail page reflect
            # what they should act on next.
            if current_round and any(
                ps.round_id == current_round.id and ps.is_correct is not None
                for ps in pick_summaries
            ):
                next_round = (
                    db.query(Round)
                    .filter(
                        Round.tournament_id == game.tournament_id,
                        Round.division == game.division,
                        Round.status.in_(["upcoming", "open", "locked"]),
                        Round.round_order > current_round.round_order,
                    )
                    .order_by(Round.round_order)
                    .first()
                )
                if next_round:
                    current_round = next_round

            my_participant = MyParticipant(
                total_points=p.total_points,
                current_streak=get_current_streak(db, game.id, user.id),
                my_picks=pick_summaries,
            )

    return GameResponse(
        id=game.id,
        division=game.division,
        status=game.status,
        tournament=TournamentResponse.model_validate(tournament),
        current_round=RoundResponse.model_validate(current_round) if current_round else None,
        participant_count=participant_count,
        my_participant=my_participant,
    )


@router.get("", response_model=list[GameResponse])
def list_games(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    games = (
        db.query(Game)
        .join(Tournament)
        .order_by(Tournament.start_date, Game.division)
        .all()
    )
    return [_build_game_response(db, g, current_user) for g in games]


@router.get("/{game_id}", response_model=GameResponse)
def get_game(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return _build_game_response(db, game, current_user)


@router.get("/{game_id}/rounds/{round_id}/players", response_model=RoundWithMatches)
def get_round_players(
    game_id: int,
    round_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    round_obj = db.get(Round, round_id)
    if not round_obj:
        raise HTTPException(status_code=404, detail="Round not found")

    # Player IDs already used by this user in this game (previous rounds)
    already_picked_ids = {
        p.player_id
        for p in db.query(Pick)
        .filter(Pick.game_id == game_id, Pick.user_id == current_user.id)
        .filter(Pick.round_id != round_id)
        .all()
    }

    matches = (
        db.query(MatchModel)
        .filter(MatchModel.round_id == round_id)
        .order_by(MatchModel.match_time, MatchModel.id)
        .all()
    )

    # Batch-fetch all players in this round and their snapshot ranks
    player_ids = {i for m in matches for i in (m.player1_id, m.player2_id) if i}
    players_map = {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(player_ids)).all()}
    snapshot_map = {
        s.normalized_name: s.rank
        for s in db.query(TournamentRankingSnapshot).filter(
            TournamentRankingSnapshot.tournament_id == game.tournament_id,
            TournamentRankingSnapshot.division == game.division,
        ).all()
    }

    match_data = []
    streak_points = get_projected_streak_points(db, game_id, current_user.id, round_obj)
    for m in matches:
        p1 = players_map.get(m.player1_id) if m.player1_id else None
        p2 = players_map.get(m.player2_id) if m.player2_id else None
        if not p1 or not p2:
            continue
        match_locked = bool(m.match_time and is_locked_before(m.match_time, timedelta(hours=1)))
        p1_rank = snapshot_map.get(normalize_player_name(p1.name))
        p2_rank = snapshot_map.get(normalize_player_name(p2.name))
        p1_bonus = calculate_ranking_bonus(p1_rank, p2_rank)
        p2_bonus = calculate_ranking_bonus(p2_rank, p1_rank)
        match_data.append(MatchForPick(
            match_id=m.id,
            player1=PlayerForPick(
                id=p1.id,
                name=p1.name,
                already_picked=p1.id in already_picked_ids,
                rank=p1_rank,
                opponent_rank=p2_rank,
                streak_points=streak_points,
                ranking_bonus=p1_bonus,
                potential_points=streak_points + p1_bonus,
            ),
            player2=PlayerForPick(
                id=p2.id,
                name=p2.name,
                already_picked=p2.id in already_picked_ids,
                rank=p2_rank,
                opponent_rank=p1_rank,
                streak_points=streak_points,
                ranking_bonus=p2_bonus,
                potential_points=streak_points + p2_bonus,
            ),
            match_time=_serialize_match_time(m.match_time),
            is_locked=match_locked,
            is_finished=m.winner_id is not None,
        ))

    existing_pick = db.query(Pick).filter(
        Pick.game_id == game_id,
        Pick.user_id == current_user.id,
        Pick.round_id == round_id,
    ).first()

    return RoundWithMatches(
        round=RoundResponse.model_validate(round_obj),
        matches=match_data,
        my_pick=existing_pick.player_id if existing_pick else None,
    )


@router.get("/{game_id}/draw", response_model=DrawResponse)
def get_draw(
    game_id: int,
    db: Session = Depends(get_db),
):
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    rounds = (
        db.query(Round)
        .filter(Round.tournament_id == game.tournament_id, Round.division == game.division)
        .order_by(Round.round_order)
        .all()
    )

    # Batch-fetch all matches and players for all rounds in one pass
    round_ids = [r.id for r in rounds]
    all_matches = (
        db.query(MatchModel)
        .filter(MatchModel.round_id.in_(round_ids))
        .order_by(MatchModel.match_time, MatchModel.id)
        .all()
    )
    matches_by_round: dict[int, list] = {}
    all_player_ids: set[int] = set()
    for m in all_matches:
        matches_by_round.setdefault(m.round_id, []).append(m)
        if m.player1_id:
            all_player_ids.add(m.player1_id)
        if m.player2_id:
            all_player_ids.add(m.player2_id)
        if m.winner_id:
            all_player_ids.add(m.winner_id)
    players_map = (
        {pl.id: pl for pl in db.query(Player).filter(Player.id.in_(all_player_ids)).all()}
        if all_player_ids else {}
    )

    round_results = []
    for r in rounds:
        match_results = []
        for m in matches_by_round.get(r.id, []):
            p1 = players_map.get(m.player1_id) if m.player1_id else None
            p2 = players_map.get(m.player2_id) if m.player2_id else None
            if not p1 or not p2:
                continue
            winner = players_map.get(m.winner_id) if m.winner_id else None
            match_results.append(MatchResult(
                match_id=m.id,
                player1_name=p1.name,
                player2_name=p2.name,
                winner_name=winner.name if winner else None,
                score=m.score,
                match_time=_serialize_match_time(m.match_time),
            ))
        round_results.append(RoundResult(
            round_id=r.id,
            round_name=r.name,
            round_order=r.round_order,
            status=r.status,
            matches=match_results,
        ))

    return DrawResponse(rounds=round_results)


@router.get("/{game_id}/leaderboard", response_model=LeaderboardResponse)
def get_leaderboard(
    game_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    game = db.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    participants = (
        db.query(GameParticipant)
        .filter(GameParticipant.game_id == game_id)
        .order_by(GameParticipant.total_points.desc(), GameParticipant.joined_at)
        .all()
    )

    user_ids = [p.user_id for p in participants]
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

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

    my_rank = None
    if current_user:
        for e in entries:
            if e.user_id == current_user.id:
                my_rank = e.rank
                break

    game_response = _build_game_response(db, game, current_user)
    return LeaderboardResponse(game=game_response, entries=entries, my_rank=my_rank)
