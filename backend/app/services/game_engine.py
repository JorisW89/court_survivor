"""
Evaluates picks after rounds complete and updates player scores.
"""

from typing import Optional

from sqlalchemy.orm import Session

from ..models import Game, GameParticipant, Match, Pick, Player, Round, TournamentRankingSnapshot
from ..player_utils import normalize_player_name
from ..time_utils import has_time_passed


def calculate_ranking_bonus(player_rank: Optional[int], opponent_rank: Optional[int]) -> int:
    if player_rank is None or opponent_rank is None:
        return 0
    rank_gap = player_rank - opponent_rank
    if rank_gap >= 10:
        return 3
    if rank_gap >= 5:
        return 2
    if rank_gap >= 1:
        return 1
    return 0


def get_player_snapshot_rank(
    db: Session,
    tournament_id: int,
    division: str,
    player_name: str,
) -> Optional[int]:
    snapshot = db.query(TournamentRankingSnapshot).filter(
        TournamentRankingSnapshot.tournament_id == tournament_id,
        TournamentRankingSnapshot.division == division,
        TournamentRankingSnapshot.normalized_name == normalize_player_name(player_name),
    ).first()
    return snapshot.rank if snapshot else None


def get_current_streak(db: Session, game_id: int, user_id: int, before_round: Optional[Round] = None) -> int:
    game = db.get(Game, game_id)
    if not game:
        return 0

    rounds_query = db.query(Round).filter(
        Round.tournament_id == game.tournament_id,
        Round.division == game.division,
    )
    if before_round:
        rounds_query = rounds_query.filter(Round.round_order < before_round.round_order)
    else:
        rounds_query = rounds_query.filter(Round.status == "completed")

    rounds = rounds_query.order_by(Round.round_order.desc()).all()
    streak = 0
    for round_obj in rounds:
        pick = db.query(Pick).filter(
            Pick.game_id == game_id,
            Pick.user_id == user_id,
            Pick.round_id == round_obj.id,
        ).first()
        if not pick:
            break
        if pick.is_correct is True:
            streak += 1
        else:
            break
    return streak


def get_projected_streak_points(db: Session, game_id: int, user_id: int, round_obj: Round) -> int:
    existing_pick = db.query(Pick).filter(
        Pick.game_id == game_id,
        Pick.user_id == user_id,
        Pick.round_id == round_obj.id,
    ).first()
    if existing_pick and existing_pick.is_correct is True:
        return get_current_streak(db, game_id, user_id)
    return get_current_streak(db, game_id, user_id, before_round=round_obj) + 1


def get_pick_points_breakdown(db: Session, pick: Pick) -> tuple[int, int, Optional[int], Optional[int]]:
    round_obj = db.get(Round, pick.round_id)
    game = db.get(Game, pick.game_id)
    player = db.get(Player, pick.player_id)
    if not round_obj or not game or not player:
        return 0, 0, None, None

    match = db.query(Match).filter(
        Match.round_id == pick.round_id,
        (Match.player1_id == pick.player_id) | (Match.player2_id == pick.player_id),
    ).first()
    opponent = None
    if match:
        opponent_id = match.player2_id if match.player1_id == pick.player_id else match.player1_id
        opponent = db.get(Player, opponent_id) if opponent_id else None

    player_rank = get_player_snapshot_rank(db, game.tournament_id, game.division, player.name)
    opponent_rank = (
        get_player_snapshot_rank(db, game.tournament_id, game.division, opponent.name)
        if opponent else None
    )
    ranking_bonus = calculate_ranking_bonus(player_rank, opponent_rank)
    if pick.is_correct is True:
        streak_points = max(0, pick.points_awarded - ranking_bonus)
    else:
        streak_points = 0
    return streak_points, ranking_bonus if pick.is_correct is True else 0, player_rank, opponent_rank


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
    """Evaluate picks for a round — scores each pick as soon as its match has a result."""
    matches = db.query(Match).filter(Match.round_id == round_obj.id).all()

    player_match: dict[int, Match] = {}
    for m in matches:
        if m.player1_id:
            player_match[m.player1_id] = m
        if m.player2_id:
            player_match[m.player2_id] = m

    picks = db.query(Pick).filter(
        Pick.round_id == round_obj.id,
        Pick.is_correct.is_(None),
    ).all()

    for pick in picks:
        match = player_match.get(pick.player_id)
        if not match or match.winner_id is None:
            continue  # result not in yet

        participant = get_or_create_participant(db, pick.game_id, pick.user_id)
        if pick.player_id == match.winner_id:
            pick.is_correct = True
            streak_points = get_current_streak(db, pick.game_id, pick.user_id, before_round=round_obj) + 1
            _, ranking_bonus, _, _ = get_pick_points_breakdown(db, pick)
            points = streak_points + ranking_bonus
            pick.points_awarded = points
            participant.total_points += points
        else:
            pick.is_correct = False
            pick.points_awarded = 0

    # Missing picks are simply a zero-point round and implicitly reset streaks.
    if round_obj.pick_deadline and has_time_passed(round_obj.pick_deadline):
        _reset_non_pickers(db, round_obj)

    db.commit()


def recalculate_game_scores(db: Session, game_id: int) -> None:
    game = db.get(Game, game_id)
    if not game:
        return

    participants = db.query(GameParticipant).filter(GameParticipant.game_id == game_id).all()
    if not participants:
        return

    for participant in participants:
        participant.total_points = 0

    rounds = (
        db.query(Round)
        .filter(
            Round.tournament_id == game.tournament_id,
            Round.division == game.division,
            Round.status != "upcoming",
        )
        .order_by(Round.round_order)
        .all()
    )

    streaks: dict[int, int] = {participant.user_id: 0 for participant in participants}
    for round_obj in rounds:
        matches = db.query(Match).filter(Match.round_id == round_obj.id).all()
        if not matches:
            continue

        player_match: dict[int, Match] = {}
        for m in matches:
            if m.player1_id:
                player_match[m.player1_id] = m
            if m.player2_id:
                player_match[m.player2_id] = m

        picks = db.query(Pick).filter(Pick.game_id == game_id, Pick.round_id == round_obj.id).all()
        picks_by_user = {pick.user_id: pick for pick in picks}

        for participant in participants:
            pick = picks_by_user.get(participant.user_id)
            if not pick:
                # Only reset streak for missing picks once the round is fully done
                if round_obj.status == "completed":
                    streaks[participant.user_id] = 0
                continue

            match = player_match.get(pick.player_id)
            if not match or match.winner_id is None:
                continue  # result not in yet

            if pick.player_id == match.winner_id:
                streaks[participant.user_id] = streaks.get(participant.user_id, 0) + 1
                pick.is_correct = True
                _, ranking_bonus, _, _ = get_pick_points_breakdown(db, pick)
                points = streaks[participant.user_id] + ranking_bonus
                pick.points_awarded = points
                participant.total_points += points
            else:
                streaks[participant.user_id] = 0
                pick.is_correct = False
                pick.points_awarded = 0


def recalculate_all_scores(db: Session) -> None:
    for game in db.query(Game).all():
        recalculate_game_scores(db, game.id)
    db.commit()


def _reset_non_pickers(db: Session, round_obj: Round) -> None:
    """Missing picks are a zero-point round and reset the streak — no further action needed."""


def evaluate_all_completed_rounds(db: Session) -> None:
    """Called after each scraper sync to evaluate any picks whose match result is now in."""
    rounds_with_unevaluated = (
        db.query(Round)
        .join(Pick, Pick.round_id == Round.id)
        .filter(Pick.is_correct.is_(None))
        .distinct()
        .all()
    )

    for r in rounds_with_unevaluated:
        evaluate_round(db, r)

    db.commit()
    recalculate_all_scores(db)


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
