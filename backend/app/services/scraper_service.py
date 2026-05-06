"""
Runs the PSA scraper and syncs results into the database.
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Game, Match, Player, Ranking, Round, Tournament

ROOT_DIR = Path(__file__).parent.parent.parent.parent

# ── Location → IANA timezone mapping ─────────────────────────────────────────
# PSA listing provides "City, CountryCode" (ISO 3166-1 alpha-2, except "EN" for England).
# Country-level defaults cover most cases; city-level overrides handle large countries
# with multiple timezones (US, AU, BR, CA).

_COUNTRY_TZ: Dict[str, str] = {
    "AE": "Asia/Dubai",
    "AT": "Europe/Vienna",
    "AU": "Australia/Sydney",
    "BE": "Europe/Brussels",
    "BG": "Europe/Sofia",
    "BR": "America/Sao_Paulo",
    "CA": "America/Toronto",
    "CH": "Europe/Zurich",
    "CZ": "Europe/Prague",
    "DE": "Europe/Berlin",
    "DK": "Europe/Copenhagen",
    "EG": "Africa/Cairo",
    "EN": "Europe/London",
    "ES": "Europe/Madrid",
    "FI": "Europe/Helsinki",
    "FR": "Europe/Paris",
    "GB": "Europe/London",
    "HK": "Asia/Hong_Kong",
    "HU": "Europe/Budapest",
    "IE": "Europe/Dublin",
    "IL": "Asia/Jerusalem",
    "IN": "Asia/Kolkata",
    "JO": "Asia/Amman",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "KW": "Asia/Kuwait",
    "LB": "Asia/Beirut",
    "MY": "Asia/Kuala_Lumpur",
    "NL": "Europe/Amsterdam",
    "NO": "Europe/Oslo",
    "NZ": "Pacific/Auckland",
    "OM": "Asia/Muscat",
    "PH": "Asia/Manila",
    "PK": "Asia/Karachi",
    "PL": "Europe/Warsaw",
    "PT": "Europe/Lisbon",
    "QA": "Asia/Qatar",
    "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade",
    "SA": "Asia/Riyadh",
    "SE": "Europe/Stockholm",
    "SG": "Asia/Singapore",
    "SI": "Europe/Ljubljana",
    "SK": "Europe/Bratislava",
    "TH": "Asia/Bangkok",
    "TR": "Europe/Istanbul",
    "TW": "Asia/Taipei",
    "TZ": "Africa/Dar_es_Salaam",
    "US": "America/New_York",   # default; most PSA US events are East Coast
    "VG": "America/Tortola",
    "ZA": "Africa/Johannesburg",
    "ZW": "Africa/Harare",
}

_CITY_TZ_OVERRIDES: Dict[str, str] = {
    # US multi-timezone overrides (lowercase city name)
    "chicago":       "America/Chicago",
    "houston":       "America/Chicago",
    "dallas":        "America/Chicago",
    "austin":        "America/Chicago",
    "minneapolis":   "America/Chicago",
    "denver":        "America/Denver",
    "phoenix":       "America/Phoenix",
    "los angeles":   "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle":       "America/Los_Angeles",
    "las vegas":     "America/Los_Angeles",
    # Australia
    "melbourne":     "Australia/Melbourne",
    "sydney":        "Australia/Sydney",
    "brisbane":      "Australia/Brisbane",
    "perth":         "Australia/Perth",
    "adelaide":      "Australia/Adelaide",
    # Canada
    "vancouver":     "America/Vancouver",
    "calgary":       "America/Edmonton",
    "winnipeg":      "America/Winnipeg",
    "montreal":      "America/Toronto",
    # Brazil
    "rio de janeiro": "America/Sao_Paulo",
    "brasilia":      "America/Sao_Paulo",
    "fortaleza":     "America/Fortaleza",
    "manaus":        "America/Manaus",
}


def location_to_timezone(location: Optional[str]) -> Optional[str]:
    """
    Convert a PSA location string like "Bristol, EN" or "Atlanta, US" to an
    IANA timezone name.  Returns None if the location cannot be resolved.
    """
    if not location or location.strip() in ("-", ""):
        return None
    parts = [p.strip() for p in location.split(",")]
    if len(parts) < 2:
        return None
    city    = parts[0].lower()
    country = parts[-1].upper()
    # City overrides take precedence (needed for large multi-tz countries)
    if city in _CITY_TZ_OVERRIDES:
        return _CITY_TZ_OVERRIDES[city]
    return _COUNTRY_TZ.get(country)

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


def parse_match_time(time_str: Optional[str], tz_name: Optional[str] = None) -> Optional[datetime]:
    if not time_str:
        return None
    cleaned = time_str.replace("•", " ").replace("–", "-")
    try:
        from dateutil import parser as date_parser
        dt = date_parser.parse(cleaned, fuzzy=True)
        if dt.tzinfo is None:
            if tz_name:
                # Interpret the scraped time as venue local time, then convert to UTC.
                from zoneinfo import ZoneInfo
                dt = dt.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
            else:
                # Unknown venue timezone — store as-is with UTC marker (best effort).
                dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def compute_pick_deadline(match_time: datetime) -> datetime:
    return match_time - timedelta(hours=1)


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
        tournament.last_synced = datetime.now(timezone.utc)
        tz_name = location_to_timezone(t_data.get("psa_location"))
        if tz_name:
            tournament.timezone = tz_name

        # Determine tournament status
        today = datetime.now(timezone.utc).date()
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
            _sync_match(db, tournament, m_data, tz_name=tournament.timezone)

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


def _sync_match(db: Session, tournament: Tournament, m_data: dict, tz_name: Optional[str] = None) -> None:
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

    match_time = parse_match_time(m_data.get("match_time"), tz_name=tz_name)

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
    tournament = db.get(Tournament, tournament_id)
    for r in rounds:
        all_matches = db.query(Match).filter(Match.round_id == r.id).all()

        # If every match in the round has a winner, the round is done — no match
        # times required (completed rounds often lack PSA time data).
        if all_matches and all(m.winner_id is not None for m in all_matches):
            r.status = "completed"
            timed = [m for m in all_matches if m.match_time]
            if timed:
                r.first_match_time = min(m.match_time for m in timed)
                r.pick_deadline = compute_pick_deadline(r.first_match_time)
            continue

        timed_matches = [m for m in all_matches if m.match_time]
        if not timed_matches:
            # No match times yet — mark as open if the tournament hasn't started so
            # the draw is visible and picks can be submitted.
            if tournament and tournament.status == "upcoming" and r.status not in ("completed", "locked"):
                r.status = "open"
            continue

        earliest = min(m.match_time for m in timed_matches)
        latest = max(m.match_time for m in timed_matches)
        r.first_match_time = earliest
        # Round deadline = 1 hour before the last match; round is locked only
        # when every match in the round is within 1 hour (no pick is possible).
        r.pick_deadline = compute_pick_deadline(latest)

        now = datetime.now(timezone.utc)
        if r.pick_deadline and now > r.pick_deadline:
            r.status = "locked"
        elif r.pick_deadline and now <= r.pick_deadline:
            r.status = "open"


PSA_RANKINGS_API: Dict[str, str] = {
    "Men":   "https://psa-api.ptsportsuite.com/rankedplayers/male",
    "Women": "https://psa-api.ptsportsuite.com/rankedplayers/female",
}

_RANKING_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def scrape_rankings() -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch full PSA world rankings via the PSA API (psa-api.ptsportsuite.com).
    Returns {"Men": [...], "Women": [...]}.
    """
    result: Dict[str, List[Dict[str, Any]]] = {}

    for division, url in PSA_RANKINGS_API.items():
        resp = requests.get(url, timeout=20, headers=_RANKING_HEADERS)
        resp.raise_for_status()
        raw = resp.json()

        entries: List[Dict[str, Any]] = []
        for player in raw:
            rank = player.get("World Ranking")
            name = player.get("Name", "").strip()
            if not rank or not name:
                continue
            entries.append({
                "rank":        int(rank),
                "player_name": name,
                "country":     player.get("Country") or None,
                "division":    division,
            })

        entries.sort(key=lambda e: e["rank"])
        result[division] = entries
        print(f"[rankings] {division}: {len(entries)} players scraped from PSA API")

    return result


def sync_rankings(db: Session, rankings: Dict[str, List[Dict[str, Any]]]) -> None:
    """Replace all ranking rows with the freshly scraped data."""
    # Drop the old unique constraint if it still exists (it incorrectly prevented tied ranks)
    try:
        db.execute(text("ALTER TABLE rankings DROP CONSTRAINT IF EXISTS uq_ranking"))
        db.commit()
    except Exception:
        db.rollback()

    db.execute(text("DELETE FROM rankings"))
    now = datetime.now(timezone.utc)

    for division, entries in rankings.items():
        for entry in entries:
            db.add(Ranking(
                division    = division,
                rank        = entry["rank"],
                player_name = entry["player_name"],
                country     = entry.get("country"),
                updated_at  = now,
            ))

    db.commit()
    print(f"[rankings] Sync complete — {sum(len(v) for v in rankings.values())} rows written")


async def run_scraper_and_sync(db: Session) -> None:
    import sys
    sys.path.insert(0, str(ROOT_DIR))
    from main import fetch_tournaments, get_reference_date
    from dataclasses import asdict

    print("[scraper] Starting scraper...")
    try:
        tournaments = await fetch_tournaments(
            limit=None,
            lookahead_days=14,
            reference_date=get_reference_date(None),
            include_tbd=False,
            debug=False,
        )
        data = [asdict(t) for t in tournaments]
        print(f"[scraper] Got {len(data)} tournaments")
        sync_tournaments(db, data)

        from .game_engine import evaluate_all_completed_rounds
        evaluate_all_completed_rounds(db)
        print("[scraper] Sync complete")

    except Exception as e:
        print(f"[scraper] Failed: {e}")

    # Sync rankings — squashinfo static HTML, fast
    print("[rankings] Scraping rankings...")
    try:
        rankings = await asyncio.to_thread(scrape_rankings)
        sync_rankings(db, rankings)
    except Exception as e:
        print(f"[rankings] Failed: {e}")
