"""
Evaluates picks after rounds complete and updates player scores/elimination status.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Game, GameParticipant, Match, Pick, Round


def calculate_points(round_order: int, base: int = 1, multiplier: int = 2) -> int:
    return base * (multiplier ** (round_order - 1))


def get_or_create_participant(db: Session, game_id: int, user_id: int) -> GameParticipant:
    p = db.query(GameParticipant).filter(
        GameParticipant.game_id == game_id,
        GameParticipant.user_id == user_id,
    ).first()
    if not p:
        p = GameParticipant(game_id=game_id, user_id=user_id)
        db.add(p)
        db.flush()
    return p


def evaluate_round(db: Session, round_obj: Round) -> None:
    """Evaluate all picks for a completed round."""
    matches = db.query(Match).filter(Match.round_id == round_obj.id).all()
    if not all(m.winner_id for m in matches):
        return  # Not all results in yet

    picks = db.query(Pick).filter(
        Pick.round_id == round_obj.id,
        Pick.is_correct.is_(None),
    ).all()

    winner_ids = {m.winner_id for m in matches}

    for pick in picks:
        participant = get_or_create_participant(db, pick.game_id, pick.user_id)
        if participant.is_eliminated:
            continue

        g = db.get(Game, pick.game_id)
        if pick.player_id in winner_ids:
            pick.is_correct = True
            points = calculate_points(round_obj.round_order, g.points_base, g.points_multiplier)
            pick.points_awarded = points
            participant.total_points += points
        else:
            pick.is_correct = False
            pick.points_awarded = 0
            participant.is_eliminated = True
            participant.eliminated_at_round_id = round_obj.id

    # Eliminate users who didn't pick for this round (if deadline has passed)
    if round_obj.pick_deadline and datetime.utcnow() > round_obj.pick_deadline:
        _eliminate_non_pickers(db, round_obj)

    db.commit()


def _eliminate_non_pickers(db: Session, round_obj: Round) -> None:
    """Find active participants in this game who have no pick for this round and eliminate them."""
    # Get the game for this round's tournament+division
    games = db.query(Game).filter(
        Game.tournament_id == round_obj.tournament_id,
        Game.division == round_obj.division,
    ).all()

    for game in games:
        participants = db.query(GameParticipant).filter(
            GameParticipant.game_id == game.id,
            GameParticipant.is_eliminated == False,
        ).all()

        for participant in participants:
            has_pick = db.query(Pick).filter(
                Pick.game_id == game.id,
                Pick.user_id == participant.user_id,
                Pick.round_id == round_obj.id,
            ).first()
            if not has_pick:
                participant.is_eliminated = True
                participant.eliminated_at_round_id = round_obj.id


def evaluate_all_completed_rounds(db: Session) -> None:
    """Called after each scraper sync to evaluate any newly completed rounds."""
    completed_rounds = db.query(Round).filter(Round.status == "completed").all()
    for r in completed_rounds:
        unevaluated = db.query(Pick).filter(
            Pick.round_id == r.id,
            Pick.is_correct.is_(None),
        ).count()
        if unevaluated > 0:
            evaluate_round(db, r)

    db.commit()


def get_current_round(db: Session, tournament_id: int, division: str) -> Optional[Round]:
    """Return the earliest non-completed round for this tournament+division."""
    return (
        db.query(Round)
        .filter(
            Round.tournament_id == tournament_id,
            Round.division == division,
            Round.status.in_(["upcoming", "open", "locked"]),
        )
        .order_by(Round.round_order)
        .first()
    )


def get_available_players_for_round(db: Session, game_id: int, round_id: int, user_id: int) -> list:
    """Return players competing in this round that the user hasn't already picked."""
    round_obj = db.get(Round, round_id)
    if not round_obj:
        return []

    matches = db.query(Match).filter(Match.round_id == round_id).all()
    player_ids = set()
    for m in matches:
        if m.player1_id:
            player_ids.add(m.player1_id)
        if m.player2_id:
            player_ids.add(m.player2_id)

    already_picked = {
        p.player_id
        for p in db.query(Pick).filter(Pick.game_id == game_id, Pick.user_id == user_id).all()
    }

    from ..models import Player

    players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    result = []
    for player in sorted(players, key=lambda p: p.normalized_name):
        result.append({"player": player, "already_picked": player.id in already_picked})
    return result
