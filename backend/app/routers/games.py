from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_optional_user
from ..database import get_db
from ..models import Game, GameParticipant, Pick, Player, Round, Tournament, User
from ..models import Match as MatchModel
from ..schemas import (
    GameResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    MatchForPick,
    MyParticipant,
    PickSummary,
    PlayerForPick,
    RoundResponse,
    RoundWithMatches,
    TournamentResponse,
)
from ..services.game_engine import get_current_round

router = APIRouter()


def _build_game_response(db: Session, game: Game, user: Optional[User]) -> GameResponse:
    tournament = db.get(Tournament, game.tournament_id)

    current_round = get_current_round(db, game.tournament_id, game.division)

    participants = db.query(GameParticipant).filter(GameParticipant.game_id == game.id).all()
    participant_count = len(participants)
    surviving_count = sum(1 for p in participants if not p.is_eliminated)

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
            for pick in picks:
                r = db.get(Round, pick.round_id)
                player = db.get(Player, pick.player_id)
                if r and player:
                    pick_summaries.append(PickSummary(
                        round_id=pick.round_id,
                        round_name=r.name,
                        round_order=r.round_order,
                        player_id=pick.player_id,
                        player_name=player.name,
                        is_correct=pick.is_correct,
                        points_awarded=pick.points_awarded,
                    ))
            pick_summaries.sort(key=lambda x: x.round_order)

            eliminated_round_name = None
            if p.eliminated_at_round_id:
                er = db.get(Round, p.eliminated_at_round_id)
                if er:
                    eliminated_round_name = er.name

            my_participant = MyParticipant(
                is_eliminated=p.is_eliminated,
                eliminated_at_round_name=eliminated_round_name,
                total_points=p.total_points,
                my_picks=pick_summaries,
            )

    return GameResponse(
        id=game.id,
        division=game.division,
        status=game.status,
        tournament=TournamentResponse.model_validate(tournament),
        current_round=RoundResponse.model_validate(current_round) if current_round else None,
        participant_count=participant_count,
        surviving_count=surviving_count,
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
        .filter(Game.status.in_(["upcoming", "active"]))
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
        .all()
    }

    matches = (
        db.query(MatchModel)
        .filter(MatchModel.round_id == round_id)
        .order_by(MatchModel.match_time, MatchModel.id)
        .all()
    )

    match_data = []
    for m in matches:
        p1 = db.get(Player, m.player1_id) if m.player1_id else None
        p2 = db.get(Player, m.player2_id) if m.player2_id else None
        if not p1 or not p2:
            continue
        match_data.append(MatchForPick(
            match_id=m.id,
            player1=PlayerForPick(id=p1.id, name=p1.name, already_picked=p1.id in already_picked_ids),
            player2=PlayerForPick(id=p2.id, name=p2.name, already_picked=p2.id in already_picked_ids),
            match_time=str(m.match_time) if m.match_time else None,
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
        .order_by(GameParticipant.is_eliminated, GameParticipant.total_points.desc())
        .all()
    )

    entries = []
    rank = 1
    for p in participants:
        user = db.get(User, p.user_id)
        if not user:
            continue
        eliminated_round_name = None
        if p.eliminated_at_round_id:
            er = db.get(Round, p.eliminated_at_round_id)
            if er:
                eliminated_round_name = er.name
        entries.append(LeaderboardEntry(
            rank=rank,
            user_id=p.user_id,
            username=user.username,
            total_points=p.total_points,
            is_eliminated=p.is_eliminated,
            eliminated_at_round_name=eliminated_round_name,
        ))
        rank += 1

    my_rank = None
    if current_user:
        for e in entries:
            if e.user_id == current_user.id:
                my_rank = e.rank
                break

    game_response = _build_game_response(db, game, current_user)
    return LeaderboardResponse(game=game_response, entries=entries, my_rank=my_rank)
