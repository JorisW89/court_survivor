"""
Sofascore tennis scraper — fetches Grand Slam draws, results, and schedules.
Uses Sofascore's internal (unofficial) API. No API key required.

Tournament IDs are discovered dynamically from Sofascore's own tournament list
rather than hardcoded, so the scraper keeps working even if IDs change.
Only tournaments active or starting within `LOOKAHEAD_DAYS` are synced.
"""

import asyncio
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy.orm import Session

from .scraper_service import sync_rankings, sync_tournaments

BASE_URL = "https://api.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.sofascore.com/",
}
REQUEST_DELAY = 2.5  # seconds — Sofascore uses Cloudflare rate limiting
LOOKAHEAD_DAYS = 14

# Canonical Grand Slam names and their venue locations (for timezone lookup).
# Locations are stable geography — not affected by Sofascore API changes.
SLAM_LOCATIONS: Dict[str, str] = {
    "Australian Open": "Melbourne, AU",
    "Roland Garros": "Paris, FR",
    "Wimbledon": "London, EN",
    "US Open": "New York, US",
}

# Approximate (month, day) start dates — used as fallback when Sofascore season
# objects lack timestamp fields. ±7 day buffer applied in window check.
SLAM_TYPICAL_STARTS: Dict[str, tuple] = {
    "Australian Open": (1, 13),
    "Roland Garros": (5, 25),
    "Wimbledon": (6, 28),
    "US Open": (8, 25),
}

# Alternative names Sofascore might use → canonical name
_NAME_ALIASES: Dict[str, str] = {
    "french open": "Roland Garros",
}

# Sofascore round number → round name (Grand Slam knockout draw)
ROUND_NAMES: Dict[int, str] = {
    1: "Round 1",
    2: "Round 2",
    3: "Round 3",
    4: "Round 4",
    5: "Quarter Final",
    6: "Semi Final",
    7: "Final",
}


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(path: str) -> Optional[dict]:
    time.sleep(REQUEST_DELAY)
    try:
        resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[sofascore] GET {path} failed: {e}")
        return None


# ── Tournament discovery ──────────────────────────────────────────────────────

def _normalize_slam_name(raw: str) -> Optional[str]:
    """
    Map a raw Sofascore tournament name to a canonical Grand Slam name.
    Strips tour prefixes/suffixes (ATP, WTA, Men's, Women's, Singles).
    Returns None if no canonical name matches.
    """
    cleaned = re.sub(r"\b(atp|wta|men'?s?|women'?s?|singles|doubles)\b", "", raw, flags=re.IGNORECASE)
    cleaned = " ".join(cleaned.split()).strip().lower()

    alias = _NAME_ALIASES.get(cleaned)
    if alias:
        return alias

    for canonical in SLAM_LOCATIONS:
        if canonical.lower() == cleaned:
            return canonical

    return None


def _discover_grand_slams() -> Dict[str, Dict]:
    """
    Fetch Sofascore's ATP (category 3) and WTA (category 6) tournament calendars
    and extract Grand Slam entries.
    Returns a dict keyed by canonical name:
      {"Roland Garros": {"name": ..., "location": ..., "atp_id": int|None, "wta_id": int|None,
                          "calendar_month": str|None, "calendar_active": bool}}
    IDs are None when that edition is not found.
    calendar_month is the group name (e.g. "May") from the Sofascore calendar — used as
    a fallback date signal when season timestamp fields are absent.
    """
    slams: Dict[str, Dict] = {}

    # category 3 = ATP, category 6 = WTA
    for category_id, is_wta in [(3, False), (6, True)]:
        data = _get(f"/category/{category_id}/unique-tournaments")
        if not data:
            continue

        # Response: {groups: [{name: "May", isActive: true, uniqueTournaments: [...]}, ...]}
        for group in data.get("groups", []):
            group_name: str = group.get("name", "")
            group_active: bool = bool(group.get("isActive", False))

            for t in group.get("uniqueTournaments", []):
                raw_name = t.get("name", "")

                # Skip doubles events
                if "double" in raw_name.lower():
                    continue

                canonical = _normalize_slam_name(raw_name)
                if not canonical:
                    continue

                # Verify Grand Slam by prize point value (Grand Slams = 2000 pts)
                if t.get("tennisPoints", 0) < 2000:
                    continue

                if canonical not in slams:
                    slams[canonical] = {
                        "name": canonical,
                        "location": SLAM_LOCATIONS.get(canonical, ""),
                        "atp_id": None,
                        "wta_id": None,
                        "calendar_month": group_name or None,
                        "calendar_active": group_active,
                    }

                tid = t.get("id")
                if is_wta:
                    slams[canonical]["wta_id"] = tid
                else:
                    slams[canonical]["atp_id"] = tid

    found = {k: v for k, v in slams.items() if v["atp_id"] or v["wta_id"]}
    print(f"[sofascore] Discovered {len(found)} Grand Slam(s): {list(found.keys())}")
    return found


# ── Season / date window ──────────────────────────────────────────────────────

def _current_season(tournament_id: int) -> Optional[dict]:
    data = _get(f"/unique-tournament/{tournament_id}/seasons")
    if not data:
        return None
    seasons = data.get("seasons", [])
    return seasons[0] if seasons else None


def _season_dates(season: dict) -> tuple[Optional[datetime], Optional[datetime]]:
    """Extract start and end as UTC datetimes from a Sofascore season object."""
    start = end = None
    for key in ("startDateTimestamp", "startTimestamp"):
        if season.get(key):
            start = datetime.fromtimestamp(season[key], tz=timezone.utc)
            break
    for key in ("endDateTimestamp", "endTimestamp"):
        if season.get(key):
            end = datetime.fromtimestamp(season[key], tz=timezone.utc)
            break
    return start, end


def _in_window(season: dict, lookahead_days: int = LOOKAHEAD_DAYS) -> bool:
    """Return True if the season is currently active or starts within the lookahead window."""
    start, end = _season_dates(season)
    if not start:
        return False
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=lookahead_days)
    effective_end = end or (start + timedelta(days=21))
    return start <= window_end and effective_end >= now


def _slam_approximate_in_window(canonical_name: str, lookahead_days: int = LOOKAHEAD_DAYS) -> bool:
    """
    Fallback window check using SLAM_TYPICAL_STARTS approximate dates.
    Returns True if the slam's typical start date (±7 day buffer) falls within
    the current year's lookahead window or is currently in progress.
    Used when Sofascore season objects lack timestamp fields.
    """
    typical = SLAM_TYPICAL_STARTS.get(canonical_name)
    if not typical:
        return False
    month, day = typical
    now = datetime.now(timezone.utc)
    try:
        approx_start = datetime(now.year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return False
    # ±7 day buffer around the approximate start date, plus tournament duration (~21 days)
    earliest = approx_start - timedelta(days=7)
    latest_end = approx_start + timedelta(days=21 + 7)
    window_end = now + timedelta(days=lookahead_days)
    return earliest <= window_end and latest_end >= now


# ── Match fetching ────────────────────────────────────────────────────────────

def _round_numbers(tournament_id: int, season_id: int) -> List[int]:
    data = _get(f"/unique-tournament/{tournament_id}/season/{season_id}/rounds")
    if not data:
        return []
    return [r["round"] for r in data.get("rounds", []) if "round" in r]


def _events_for_round(tournament_id: int, season_id: int, round_num: int) -> List[dict]:
    data = _get(f"/unique-tournament/{tournament_id}/season/{season_id}/events/round/{round_num}")
    if not data:
        return []
    return data.get("events", [])


def _format_score(event: dict) -> Optional[str]:
    """Build '6-3, 6-4, 7-5' score string from Sofascore period scores."""
    home = event.get("homeScore") or {}
    away = event.get("awayScore") or {}
    sets = []
    for i in range(1, 6):
        h = home.get(f"period{i}")
        a = away.get(f"period{i}")
        if h is None or a is None:
            break
        sets.append(f"{h}-{a}")
    return ", ".join(sets) if sets else None


def _convert_event(event: dict, division: str, round_name: str) -> Optional[dict]:
    """Convert a Sofascore event to the match dict sync_tournaments expects."""
    # Sofascore uses homeTeam/awayTeam even for individual sports like tennis
    player1 = ((event.get("homeTeam") or {}).get("name") or "").strip()
    player2 = ((event.get("awayTeam") or {}).get("name") or "").strip()
    if not player1 or not player2:
        return None

    match_time_str = None
    ts = event.get("startTimestamp")
    if ts:
        match_time_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    # winnerCode: 1 = homeTeam wins, 2 = awayTeam wins
    wc = event.get("winnerCode")
    winner = player1 if wc == 1 else (player2 if wc == 2 else None)

    return {
        "raw_id": f"sofascore_{event['id']}",
        "division": division,
        "round_name": round_name,
        "player1": player1,
        "player2": player2,
        "match_time": match_time_str,
        "score": _format_score(event),
        "winner": winner,
    }


def _fetch_matches(tournament_id: int, season_id: int, division: str) -> List[dict]:
    matches = []
    for round_num in _round_numbers(tournament_id, season_id):
        round_name = ROUND_NAMES.get(round_num, f"Round {round_num}")
        for event in _events_for_round(tournament_id, season_id, round_num):
            m = _convert_event(event, division, round_name)
            if m:
                matches.append(m)
    return matches


# ── Rankings ──────────────────────────────────────────────────────────────────

_RANKINGS_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.sofascore.com/",
}


def _scrape_tennis_rankings() -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch ATP/WTA rankings by scraping the Sofascore rankings page.

    The page is server-side rendered; all 500 entries are embedded in the
    __NEXT_DATA__ JSON blob under:
      props.pageProps.initialProps.initialRankingsData.rankingRows

    Each row: {"name": str, "position": int, "country": {"alpha2": str, ...}}
    """
    import re as _re
    import json as _json

    result: Dict[str, List[Dict[str, Any]]] = {}

    for division, tour in [("Men", "atp"), ("Women", "wta")]:
        time.sleep(REQUEST_DELAY)
        try:
            resp = requests.get(
                f"https://www.sofascore.com/tennis/rankings/{tour}",
                headers=_RANKINGS_PAGE_HEADERS,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            print(f"[sofascore] {tour.upper()} rankings page unavailable: {e}")
            continue

        m = _re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            resp.text,
            _re.DOTALL,
        )
        if not m:
            print(f"[sofascore] {tour.upper()} rankings: __NEXT_DATA__ not found in page")
            continue

        try:
            page_data = _json.loads(m.group(1))
            rows = (
                page_data["props"]["pageProps"]["initialProps"]
                ["initialRankingsData"]["rankingRows"]
            )
        except (KeyError, ValueError) as e:
            print(f"[sofascore] {tour.upper()} rankings: failed to parse __NEXT_DATA__: {e}")
            continue

        entries = []
        for row in rows:
            name = (row.get("name") or "").strip()
            rank = row.get("position")
            # row-level country is empty for neutral-flag players; fall back to team.country
            country = (
                (row.get("country") or {}).get("alpha2")
                or ((row.get("team") or {}).get("country") or {}).get("alpha2")
                or None
            )
            if not name or not rank:
                continue
            entries.append({"rank": int(rank), "player_name": name, "country": country, "division": division})

        if entries:
            entries.sort(key=lambda e: e["rank"])
            result[division] = entries
            print(f"[sofascore] {tour.upper()} rankings: {len(entries)} players scraped")
        else:
            print(f"[sofascore] {tour.upper()} rankings: no entries found in page data")

    return result


# ── Main entry point ──────────────────────────────────────────────────────────

def fetch_active_grand_slams(lookahead_days: int = LOOKAHEAD_DAYS) -> List[dict]:
    """
    Discover all Grand Slams from Sofascore, filter to those active or starting
    within `lookahead_days`, and return the tournament dicts for sync_tournaments.
    """
    slams = _discover_grand_slams()
    if not slams:
        print("[sofascore] No Grand Slams discovered — check Sofascore API")
        return []

    current_year = datetime.now(timezone.utc).year
    tournaments = []
    for slam in slams.values():
        name = slam["name"]
        atp_id = slam["atp_id"]
        if not atp_id:
            print(f"[sofascore] {name}: no ATP ID found, skipping")
            continue

        season = _current_season(atp_id)
        if not season:
            print(f"[sofascore] {name}: no current season found")
            continue

        # Primary: use season timestamp fields. Fallback: approximate from SLAM_TYPICAL_STARTS.
        start_dt, end_dt = _season_dates(season)
        if start_dt:
            in_window = _in_window(season, lookahead_days)
        else:
            in_window = _slam_approximate_in_window(name, lookahead_days)
            if in_window:
                print(f"[sofascore] {name}: no season timestamps — using approximate calendar fallback")

        if not in_window:
            date_str = start_dt.strftime("%Y-%m-%d") if start_dt else "unknown"
            print(f"[sofascore] {name}: starts {date_str}, outside {lookahead_days}-day window — skipping")
            continue

        season_id = season["id"]
        season_year_str = season.get("year", "")
        # Guard: don't import match data from a previous year's season
        try:
            season_year = int(season_year_str)
        except (ValueError, TypeError):
            season_year = None
        stale_season = season_year is not None and season_year < current_year

        title = f"{name} {current_year}".strip()

        # Infer start/end dates from approximate values when season lacks timestamps
        if not start_dt:
            typical = SLAM_TYPICAL_STARTS.get(name)
            if typical:
                start_dt = datetime(current_year, typical[0], typical[1], tzinfo=timezone.utc)
                end_dt = start_dt + timedelta(days=14)

        if stale_season:
            print(f"[sofascore] {name}: most recent season is {season_year_str} — {current_year} not yet on Sofascore; syncing as upcoming with no matches")
            matches: List[dict] = []
        else:
            print(f"[sofascore] Syncing {title} (ATP id={atp_id}, season={season_id})")
            matches = _fetch_matches(atp_id, season_id, "Men")

        wta_id = slam.get("wta_id")
        if wta_id and not stale_season:
            wta_season = _current_season(wta_id)
            if wta_season:
                wta_start, _ = _season_dates(wta_season)
                wta_in_window = (
                    _in_window(wta_season, lookahead_days) if wta_start
                    else _slam_approximate_in_window(name, lookahead_days)
                )
                try:
                    wta_year = int(wta_season.get("year", "0"))
                except (ValueError, TypeError):
                    wta_year = None
                wta_stale = wta_year is not None and wta_year < current_year
                if wta_in_window and not wta_stale:
                    wta_season_id = wta_season["id"]
                    print(f"[sofascore] Syncing {title} WTA (id={wta_id}, season={wta_season_id})")
                    matches.extend(_fetch_matches(wta_id, wta_season_id, "Women"))
                elif wta_stale:
                    print(f"[sofascore] {name} WTA: season {wta_season.get('year')} is stale — skipping WTA matches")
                else:
                    print(f"[sofascore] {name} WTA: not in window or no season found")
        elif wta_id and stale_season:
            print(f"[sofascore] {name} WTA: skipped (ATP season stale)")

        print(f"[sofascore] {title}: {len(matches)} matches total")
        tournaments.append({
            "url": f"sofascore://tennis/{atp_id}/season/{season_id}",
            "title": title,
            "category": "Grand Slam",
            "start_date": start_dt.strftime("%Y-%m-%d") if start_dt else None,
            "end_date": end_dt.strftime("%Y-%m-%d") if end_dt else None,
            "psa_location": slam["location"],
            "matches": matches,
        })

    return tournaments


async def run_tennis_scraper_and_sync(db: Session) -> None:
    print("[tennis] Starting Sofascore scraper...")
    try:
        tournaments = await asyncio.to_thread(fetch_active_grand_slams)
        print(f"[tennis] Got {len(tournaments)} Grand Slam(s) in window")
        sync_tournaments(db, tournaments, sport="tennis")
        from .game_engine import evaluate_all_completed_rounds
        evaluate_all_completed_rounds(db)
        print("[tennis] Tournament sync complete")
    except Exception as e:
        print(f"[tennis] Tournament sync failed: {e}")

    print("[tennis] Fetching ATP/WTA rankings...")
    try:
        rankings = await asyncio.to_thread(_scrape_tennis_rankings)
        if rankings:
            sync_rankings(db, rankings, sport="tennis")
        else:
            print("[tennis] No rankings data — skipping")
    except Exception as e:
        print(f"[tennis] Rankings sync failed: {e}")
