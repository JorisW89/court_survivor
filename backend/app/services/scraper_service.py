"""
Runs the PSA scraper and syncs results into the database.
"""

import asyncio
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Game, Match, Player, Round, Tournament

ROOT_DIR = Path(__file__).parent.parent.parent.parent

ROUND_ORDER_MAP = {
    "round 1": 1,
    "round of 128": 1,
    "round 2": 2,
    "round of 64": 2,
    "last 64": 2,
    "round 3": 3,
    "round of 32": 3,
    "last 32": 3,
    "round 4": 4,
    "round of 16": 4,
    "last 16": 4,
    "quarter final": 5,
    "quarter-final": 5,
    "quarterfinal": 5,
    "quarter finals": 5,
    "semi final": 6,
    "semi-final": 6,
    "semifinal": 6,
    "semi finals": 6,
    "final": 7,
}


def normalize_player_name(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\d+[\)\]]", "", name)
    return " ".join(name.split()).strip().lower()


def get_round_order(round_name: str) -> int:
    key = round_name.lower().strip()
    return ROUND_ORDER_MAP.get(key, 99)


def parse_match_time(time_str: Optional[str]) -> Optional[datetime]:
    if not time_str:
        return None
    cleaned = time_str.replace("•", " ").replace("–", "-")
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(cleaned, fuzzy=True)
    except Exception:
        return None


def compute_pick_deadline(match_time: datetime) -> datetime:
    # Midnight UTC of the day before the match
    match_date = match_time.date()
    day_before = match_date - timedelta(days=1)
    return datetime(day_before.year, day_before.month, day_before.day, 23, 59, 59)


def upsert_player(db: Session, raw_name: str) -> Optional[Player]:
    normalized = normalize_player_name(raw_name)
    if not normalized or normalized in {"tbd", "bye"}:
        return None
    player = db.query(Player).filter(Player.normalized_name == normalized).first()
    if not player:
        player = Player(name=raw_name, normalized_name=normalized)
        db.add(player)
        db.flush()
    return player


def upsert_round(db: Session, tournament_id: int, division: str, round_name: str) -> Round:
    existing = (
        db.query(Round)
        .filter(Round.tournament_id == tournament_id, Round.division == division, Round.name == round_name)
        .first()
    )
    if existing:
        return existing
    order = get_round_order(round_name)
    r = Round(
        tournament_id=tournament_id,
        division=division,
        name=round_name,
        round_order=order,
        status="upcoming",
    )
    db.add(r)
    db.flush()
    return r


def sync_tournaments(db: Session, data: list[dict]) -> None:
    for t_data in data:
        url = t_data.get("url", "").rstrip("/") + "/"
        tournament = db.query(Tournament).filter(Tournament.psa_url == url).first()
        if not tournament:
            tournament = Tournament(psa_url=url)
            db.add(tournament)

        tournament.title = t_data.get("title", "Unknown")
        tournament.category = t_data.get("category")
        tournament.start_date = t_data.get("start_date")
        tournament.end_date = t_data.get("end_date")
        tournament.last_synced = datetime.utcnow()

        # Determine tournament status
        today = datetime.utcnow().date()
        start = _parse_date(tournament.start_date)
        end = _parse_date(tournament.end_date)
        if start and end:
            if today < start:
                tournament.status = "upcoming"
            elif today > end:
                tournament.status = "completed"
            else:
                tournament.status = "active"

        db.flush()

        # Ensure games exist for each division present
        divisions_in_data = {m.get("division") for m in t_data.get("matches", []) if m.get("division")}
        for division in divisions_in_data:
            _ensure_game(db, tournament.id, division)

        # Sync matches
        for m_data in t_data.get("matches", []):
            _sync_match(db, tournament, m_data)

        # Update rounds: set first_match_time and pick_deadline
        _update_round_deadlines(db, tournament.id)

    db.commit()


def _parse_date(date_str: Optional[str]):
    if not date_str:
        return None
    try:
        from dateutil import parser
        return parser.parse(date_str).date()
    except Exception:
        return None


def _ensure_game(db: Session, tournament_id: int, division: str) -> Game:
    game = (
        db.query(Game)
        .filter(Game.tournament_id == tournament_id, Game.division == division)
        .first()
    )
    if not game:
        game = Game(tournament_id=tournament_id, division=division, status="upcoming")
        db.add(game)
        db.flush()

    # Sync game status with tournament
    tournament = db.get(Tournament, tournament_id)
    if tournament:
        game.status = tournament.status

    return game


def _sync_match(db: Session, tournament: Tournament, m_data: dict) -> None:
    raw_id = m_data.get("raw_id")
    if not raw_id:
        return

    division = m_data.get("division", "Men")
    round_name = m_data.get("round_name") or "Unknown"

    round_obj = upsert_round(db, tournament.id, division, round_name)

    p1 = upsert_player(db, m_data.get("player1") or "")
    p2 = upsert_player(db, m_data.get("player2") or "")
    if not p1 or not p2:
        return

    match_time = parse_match_time(m_data.get("match_time"))

    existing = db.query(Match).filter(Match.psa_raw_id == raw_id).first()
    if not existing:
        existing = Match(
            tournament_id=tournament.id,
            round_id=round_obj.id,
            division=division,
            player1_id=p1.id,
            player2_id=p2.id,
            psa_raw_id=raw_id,
        )
        db.add(existing)

    existing.score = m_data.get("score")
    existing.match_time = match_time
    existing.round_id = round_obj.id

    # Set winner if score is available (basic heuristic: score like "3-1" means p1 won)
    winner_name = m_data.get("winner")
    if winner_name:
        winner = upsert_player(db, winner_name)
        existing.winner_id = winner.id if winner else None
    elif existing.score:
        existing.winner_id = _infer_winner(existing.score, p1.id, p2.id)


def _infer_winner(score: str, p1_id: int, p2_id: int) -> Optional[int]:
    """Infer winner from score string like '3-1', '3-0', '2-3'."""
    parts = re.findall(r"(\d+)\s*[-–]\s*(\d+)", score)
    if not parts:
        return None
    # Aggregate game scores
    p1_games = sum(int(a) for a, b in parts)
    p2_games = sum(int(b) for a, b in parts)
    if p1_games > p2_games:
        return p1_id
    if p2_games > p1_games:
        return p2_id
    return None


def _update_round_deadlines(db: Session, tournament_id: int) -> None:
    rounds = db.query(Round).filter(Round.tournament_id == tournament_id).all()
    for r in rounds:
        matches = db.query(Match).filter(Match.round_id == r.id, Match.match_time.isnot(None)).all()
        if not matches:
            continue
        earliest = min(m.match_time for m in matches)
        r.first_match_time = earliest
        r.pick_deadline = compute_pick_deadline(earliest)

        # Determine round status
        all_have_winner = all(m.winner_id is not None for m in db.query(Match).filter(Match.round_id == r.id).all())
        now = datetime.utcnow()
        if all_have_winner and len(matches) > 0:
            r.status = "completed"
        elif r.pick_deadline and now > r.pick_deadline:
            r.status = "locked"
        elif r.pick_deadline and now <= r.pick_deadline:
            r.status = "open"


async def run_scraper_and_sync(db: Session) -> None:
    print("[scraper] Starting PSA scraper...")
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["python", "main.py", "--json"],
            capture_output=True,
            text=True,
            cwd=str(ROOT_DIR),
            timeout=300,
        )
        if result.returncode != 0:
            print(f"[scraper] Scraper error: {result.stderr[:500]}")
            return

        data = json.loads(result.stdout)
        if not isinstance(data, list):
            print("[scraper] Unexpected scraper output format")
            return

        print(f"[scraper] Got {len(data)} tournaments from scraper")
        sync_tournaments(db, data)

        from .game_engine import evaluate_all_completed_rounds
        evaluate_all_completed_rounds(db)
        print("[scraper] Sync complete")

    except subprocess.TimeoutExpired:
        print("[scraper] Scraper timed out after 5 minutes")
    except json.JSONDecodeError as e:
        print(f"[scraper] Failed to parse scraper output: {e}")
    except Exception as e:
        print(f"[scraper] Unexpected error: {e}")
