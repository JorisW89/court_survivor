#!/usr/bin/env python3
"""
PSA tournament scraper — hybrid approach:
  - squashinfo.com  →  full player names + scores (static HTML, no Playwright)
  - psasquashtour.com →  match times only (Playwright, JS-rendered SPA)

Matches between the two sources are correlated by a sorted (surname1, surname2)
pair, e.g. ("asal", "kandra").  The only failure case is two players with
identical surnames facing each other, which is extremely rare.

Usage:
    python main.py
    python main.py --json
    python main.py --days 14
    python main.py --today 2026-05-08
    python main.py --debug
    python main.py --include-tbd
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import async_playwright, BrowserContext, Page


# ── Constants ─────────────────────────────────────────────────────────────────

SQUASHINFO_BASE        = "https://www.squashinfo.com"
SQUASHINFO_CALENDAR_URL = "https://www.squashinfo.com/calendar"

PSA_BASE            = "https://www.psasquashtour.com"
PSA_TOURNAMENTS_URL = "https://www.psasquashtour.com/tournaments/"

SNAPSHOT_FILE  = Path("psa_snapshot.json")
LOOKAHEAD_DAYS = 14

ROUND_NORM: Dict[str, str] = {
    "1st round":              "Round 1",
    "2nd round":              "Round 2",
    "last 64":                "Round 1",
    "last 32":                "Round 2",
    "last thirty-two round":  "Round 2",
    "last sixteen round":     "Last 16",
    "round of 16":            "Last 16",
    "last 16":                "Last 16",
    "quarter-finals":         "Quarter Final",
    "quarter finals":         "Quarter Final",
    "semi-finals":            "Semi Final",
    "semi finals":            "Semi Final",
    "final":                  "Final",
}

# Time pattern used in PSA draw text: "08 MAY 2026 • 20:15"
PSA_TIME_RE = re.compile(
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s*•\s*\d{1,2}:\d{2}\b",
    flags=re.I,
)

MONTH_WORDS = {
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august",
    "sep", "september", "oct", "october", "nov", "november", "dec", "december",
}

# Squashinfo match line (from individual row td, not whole-page get_text):
#   "[1] Mostafa Asal (EGY) v Raphael Kandra (GER)"
#   "AbdAllah Eissa (ENG) bt [9/16] Robert Downer (ENG)"
#   "[3] Bailey Malik (ENG) v [WC] Harith Danial (MAS)"
# Seeds use \w and / to cover [9/16], [WC] etc.
# Name character class includes Latin extended for accented names (Grégoire, Azaña).
SQUASHINFO_MATCH_RE = re.compile(
    r"(?:\[\s*[\w/]+\s*\]\s+)?"                            # optional [seed] for p1 (allows spaces like [ WC ])
    r"([A-Za-zÀ-ɏ][A-Za-zÀ-ɏ '\-\.]+?)"  # player 1 name
    r"\s+\([A-Z]{3,4}\)"                                   # (CTY)
    r"\s+(bt|v)\s+"                                        # result verb
    r"(?:\[\s*[\w/]+\s*\]\s+)?"                            # optional [seed] for p2 (allows spaces like [ WC ])
    r"([A-Za-zÀ-ɏ][A-Za-zÀ-ɏ '\-\.]+?)"  # player 2 name
    r"\s+\([A-Z]{3,4}\)",                                  # (CTY)
)

# Score lines start with a game score pattern: "11-5" or "9-11"
SCORE_LINE_RE = re.compile(r"^\d{1,2}-\d{1,2}")


# ── Data classes (unchanged interface for scraper_service.py) ─────────────────

@dataclass
class Match:
    tournament: str
    tournament_url: str
    division: Optional[str]
    round_name: Optional[str]
    player1: Optional[str]
    player2: Optional[str]
    score: Optional[str]
    winner: Optional[str]
    status: Optional[str]
    match_time: Optional[str]
    source: str
    raw_id: str


@dataclass
class Tournament:
    title: str
    url: str
    category: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    matches: List[Match] = field(default_factory=list)


# ── Shared utilities ──────────────────────────────────────────────────────────

def stable_hash(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def get_reference_date(today_arg: Optional[str]) -> date:
    if today_arg:
        return date_parser.parse(today_arg).date()
    return datetime.now().date()


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date_parser.parse(value).date()
    except Exception:
        return None


def is_within_window(
    start_date: Optional[str],
    end_date: Optional[str],
    reference_date: date,
    days: int,
) -> bool:
    window_end = reference_date + timedelta(days=days)
    start = parse_iso_date(start_date)
    end   = parse_iso_date(end_date)
    if not start and not end:
        return False
    start = start or end
    end   = end   or start
    return start <= window_end and end >= reference_date


def dates_overlap(
    s1: Optional[str], e1: Optional[str],
    s2: Optional[str], e2: Optional[str],
) -> bool:
    a = parse_iso_date(s1)
    b = parse_iso_date(e1)
    c = parse_iso_date(s2)
    d = parse_iso_date(e2)
    if not (a and b and c and d):
        return False
    return a <= d and b >= c


def infer_category(title: str) -> Optional[str]:
    lowered = title.lower()
    for cat in ["World Championship", "Diamond", "Platinum", "Gold",
                "Silver", "Bronze", "Challenger"]:
        if cat.lower() in lowered:
            return cat
    return None


def strip_gender(title: str) -> str:
    title = re.sub(r"\s*\(Men'?s?\)",   "", title, flags=re.I)
    title = re.sub(r"\s*\(Women'?s?\)", "", title, flags=re.I)
    title = re.sub(r"^(Men'?s?|Women'?s?)\s+", "", title, flags=re.I)
    return title.strip()


# ── Surname-pair matching (bridges squashinfo ↔ PSA) ─────────────────────────

def extract_surname(name: str) -> str:
    """
    Extract the surname from either an abbreviated PSA name ("M. ElShorbagy (1)")
    or a full squashinfo name ("Mohamed ElShorbagy").  Used only for match-key
    construction — not stored anywhere.
    """
    name = re.sub(r"\s*[\(\[]\w+[\)\]]", "", name).strip()  # strip seed/brackets
    # Abbreviated: "M. Surname …"
    m = re.match(r"^[A-Z]\.\s+(.+)$", name)
    if m:
        return m.group(1).strip().lower()
    # Full name: drop first word (first name)
    parts = name.split()
    if len(parts) >= 2:
        return " ".join(parts[1:]).strip().lower()
    return name.strip().lower()


def match_surname_key(name1: str, name2: str) -> Tuple[str, str]:
    """Sorted (surname1, surname2) used as a cross-source match identifier."""
    return tuple(sorted([extract_surname(name1), extract_surname(name2)]))


# ── squashinfo scraping (requests + BeautifulSoup) ───────────────────────────

def fetch_html(url: str) -> str:
    resp = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-GB,en;q=0.9",
        },
    )
    resp.raise_for_status()
    return resp.text


def parse_event_dates(html: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract start/end dates from a squashinfo event page ("8 - 16 May 2026")."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ")
    m = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
    if m:
        day1, day2, month, year = m.groups()
        try:
            start = date_parser.parse(f"{day1} {month} {year}").date().isoformat()
            end   = date_parser.parse(f"{day2} {month} {year}").date().isoformat()
            return start, end
        except Exception:
            pass
    return None, None


def parse_calendar_event_links(html: str) -> List[Dict[str, Any]]:
    """Return [{url, title, division}] for all event links on the calendar page."""
    soup = BeautifulSoup(html, "html.parser")
    events: List[Dict[str, Any]] = []
    seen: set = set()

    for a in soup.find_all("a", href=re.compile(r"^/events/")):
        href  = a.get("href", "")
        url   = SQUASHINFO_BASE + href
        if url in seen:
            continue
        seen.add(url)

        title = a.get_text(strip=True)
        if not title:
            continue

        tl, hl = title.lower(), href.lower()
        if "women" in tl or "women" in hl:
            division = "Women"
        elif "men" in tl or "men" in hl:
            division = "Men"
        else:
            division = None

        events.append({"url": url, "title": title, "division": division})

    return events


def parse_event_matches(
    html: str,
    tournament_title: str,
    tournament_url: str,
    division: str,
    include_tbd: bool,
    debug: bool,
) -> List[Match]:
    """
    Parse matches from a squashinfo event page by iterating table rows directly.

    Row types in the match table:
      - <td class="match_type">  → round header
      - <tr id="match_..."> with one <td colspan="2">  → upcoming match
      - <tr id="match_..."> with two tds (indv_col_1 / indv_col_2)
          → completed match (col2 has score) or bye (col2 == "bye")
    """
    soup   = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        if debug:
            print(f"[debug] squashinfo: no match table found ({division})")
        return []

    match_table   = tables[1]
    matches: List[Match] = []
    seen:    set         = set()
    current_round: Optional[str] = None

    def _clean(td) -> str:
        return " ".join(td.get_text(" ").split())

    for row in match_table.find_all("tr"):
        # Round header row
        td_type = row.find("td", class_="match_type")
        if td_type:
            key = td_type.get_text(strip=True).rstrip(":").strip().lower()
            current_round = ROUND_NORM.get(key, current_round)
            continue

        # Only process match rows
        if not row.get("id", "").startswith("match_"):
            continue

        tds = row.find_all("td")
        if not tds:
            continue

        if len(tds) == 1:
            # Upcoming: single td colspan="2"
            line  = _clean(tds[0])
            score = None
        else:
            # Completed or bye: two tds
            col2 = _clean(tds[1])
            if col2.lower() == "bye":
                continue
            line  = _clean(tds[0])
            score = re.sub(r"\s*\(\d+m\)\s*$", "", col2).strip() or None

        m = SQUASHINFO_MATCH_RE.search(line)
        if not m:
            continue

        name1, verb, name2 = m.groups()
        name1, name2 = name1.strip(), name2.strip()
        is_done = verb == "bt"

        key = (division, current_round, name1, name2)
        if key in seen:
            continue
        seen.add(key)

        matches.append(Match(
            tournament     = tournament_title,
            tournament_url = tournament_url,
            division       = division,
            round_name     = current_round,
            player1        = name1,
            player2        = name2,
            score          = score,
            winner         = name1 if is_done else None,
            status         = "completed" if is_done else "upcoming",
            match_time     = None,
            source         = "squashinfo",
            raw_id         = stable_hash({
                "tournament": tournament_title,
                "division":   division,
                "round":      current_round,
                "p1":         name1,
                "p2":         name2,
            }),
        ))

    if debug:
        print(f"[debug] squashinfo: {len(matches)} {division} matches parsed")

    return matches


# ── PSA match-time scraping (Playwright) ─────────────────────────────────────

async def _block_heavy_assets(context: BrowserContext) -> None:
    async def handler(route):
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
        else:
            await route.continue_()
    await context.route("**/*", handler)


async def _click_text(page: Page, labels: List[str]) -> bool:
    for label in labels:
        try:
            loc = page.get_by_text(label, exact=True).first
            if await loc.count():
                await loc.click(timeout=3_000)
                await page.wait_for_timeout(1_500)
                return True
        except Exception:
            pass
    return False


def _is_psa_player_line(line: str) -> bool:
    """True if this line looks like a player name in PSA draw format."""
    if not line or len(line) > 60:
        return False
    if not re.search(r"[A-Za-z]", line):
        return False
    if PSA_TIME_RE.search(line):
        return False
    if any(w in line.lower().split() for w in MONTH_WORDS):
        return False
    # Score/placeholder lines: only digits and dashes
    if re.fullmatch(r"[\d\s\-–—]+", line):
        return False
    return True


def _extract_psa_match_times(visible_text: str) -> Dict[Tuple[str, str], str]:
    """
    Parse PSA draw visible text → {sorted_surname_pair: match_time_str}.
    Player names in PSA are abbreviated ("M. ElShorbagy (1)").
    """
    lines    = [l.strip() for l in visible_text.splitlines() if l.strip()]
    time_map: Dict[Tuple[str, str], str] = {}

    for index, line in enumerate(lines):
        if not PSA_TIME_RE.fullmatch(line):
            continue

        scan_start = max(0, index - 18)
        candidates = [l for l in lines[scan_start:index] if _is_psa_player_line(l)]

        if len(candidates) < 2:
            continue

        key = match_surname_key(candidates[-2], candidates[-1])
        time_map[key] = line

    return time_map


def _parse_psa_date_range(text: str, reference_year: int) -> Tuple[Optional[str], Optional[str]]:
    text = text.replace("–", "-").replace("—", "-")
    patterns = [
        r"(\d{1,2}\s+[A-Za-z]{3,9})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"(\d{1,2})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        start_raw, end_raw = m.group(1), m.group(2)
        try:
            if not re.search(r"\d{4}", end_raw):
                end_raw = f"{end_raw} {reference_year}"
            end_dt = date_parser.parse(end_raw, fuzzy=True).date()
            if re.fullmatch(r"\d{1,2}", start_raw.strip()):
                start_raw = f"{start_raw} {end_dt.strftime('%B')} {end_dt.year}"
            elif not re.search(r"\d{4}", start_raw):
                start_raw = f"{start_raw} {end_dt.year}"
            start_dt = date_parser.parse(start_raw, fuzzy=True).date()
            return start_dt.isoformat(), end_dt.isoformat()
        except Exception:
            continue
    return None, None


_PSA_TABLE_DATE_RE = re.compile(
    r"([A-Za-z]{3})\s+(\d{1,2})\s*[-–]\s*([A-Za-z]{3})\s+(\d{1,2})",
    flags=re.I,
)


def _parse_psa_table_date(text: str, reference_year: int) -> Tuple[Optional[str], Optional[str]]:
    """Parse PSA listing table date cell: 'MAY 05 - MAY 09' → (iso_start, iso_end)."""
    m = _PSA_TABLE_DATE_RE.search(text.strip())
    if not m:
        return None, None
    start_month, start_day, end_month, end_day = m.groups()
    try:
        start_dt = date_parser.parse(f"{start_day} {start_month} {reference_year}").date()
        end_dt   = date_parser.parse(f"{end_day} {end_month} {reference_year}").date()
        if end_dt < start_dt:
            end_dt = date_parser.parse(f"{end_day} {end_month} {reference_year + 1}").date()
        return start_dt.isoformat(), end_dt.isoformat()
    except Exception:
        return None, None


async def _scrape_psa_listing(
    context: BrowserContext,
    reference_date: date,
    lookahead_days: int,
    debug: bool,
) -> List[Dict[str, Any]]:
    """Scrape the PSA tournament listing page → [{url, start_date, end_date}]."""
    page = await context.new_page()
    results: List[Dict[str, Any]] = []
    try:
        await page.goto(PSA_TOURNAMENTS_URL, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            await page.wait_for_timeout(3_000)

        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")

        # The listing is a table: DATE | TOURNAMENT (link) | LOCATION | ...
        # Walk each table row, extract the date from the first cell and the URL from any link.
        seen: set = set()
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            date_text = cells[0].get_text(" ", strip=True)
            start_date, end_date = _parse_psa_table_date(date_text, reference_date.year)
            if not start_date:
                # Fallback: try the old approach on the full row text
                row_text = re.sub(r"\s+", " ", row.get_text(" ")).strip()
                start_date, end_date = _parse_psa_date_range(row_text, reference_date.year)

            if not is_within_window(start_date, end_date, reference_date, lookahead_days):
                continue

            for a in row.find_all("a", href=re.compile(r"/tournament/")):
                href = a.get("href", "")
                url  = (PSA_BASE + href if href.startswith("/") else href)
                url  = url.split("#")[0].rstrip("/") + "/"
                if url not in seen:
                    seen.add(url)
                    results.append({"url": url, "start_date": start_date, "end_date": end_date})

        if debug:
            print(f"[debug] PSA listing: {len(results)} tournaments in window")
    except Exception as exc:
        if debug:
            print(f"[debug] PSA listing scrape failed: {exc}")
    finally:
        await page.close()

    return results


async def _scrape_psa_draw_times(
    context: BrowserContext,
    psa_url: str,
    debug: bool,
) -> Dict[str, Dict[Tuple[str, str], str]]:
    """
    Open a PSA tournament draw page and extract match times per division.
    Returns {division: {surname_pair: match_time_str}}.
    """
    page   = await context.new_page()
    result: Dict[str, Dict[Tuple[str, str], str]] = {}

    try:
        await page.goto(psa_url, wait_until="domcontentloaded", timeout=45_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            await page.wait_for_timeout(4_000)

        for division in ["Men", "Women"]:
            await _click_text(page, ["MAIN DRAW", "Main Draw", "Draw"])
            labels = (["MEN'S", "Men's", "Men"] if division == "Men"
                      else ["WOMEN'S", "Women's", "Women"])
            await _click_text(page, labels)
            await page.wait_for_timeout(1_500)

            try:
                visible_text = await page.locator("body").inner_text(timeout=10_000)
            except Exception:
                continue

            time_map = _extract_psa_match_times(visible_text)
            if time_map:
                result[division] = time_map
                if debug:
                    print(f"[debug] PSA times for {division}: {len(time_map)} entries")

    except Exception as exc:
        if debug:
            print(f"[debug] PSA draw scrape failed for {psa_url}: {exc}")
    finally:
        await page.close()

    return result


async def enrich_with_psa_times(
    tournaments: List[Tournament],
    reference_date: date,
    lookahead_days: int,
    debug: bool,
) -> None:
    """
    For each tournament, find its PSA page and pull match times.
    Assign times to squashinfo matches via sorted surname-pair key.
    Only upcoming matches need times (completed matches already have results).
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-GB",
        )
        await _block_heavy_assets(context)

        psa_listings = await _scrape_psa_listing(context, reference_date, lookahead_days, debug)

        for tournament in tournaments:
            # Find PSA tournament whose dates overlap this squashinfo tournament
            psa_url = next(
                (p["url"] for p in psa_listings
                 if dates_overlap(p["start_date"], p["end_date"],
                                  tournament.start_date, tournament.end_date)),
                None,
            )

            if not psa_url:
                if debug:
                    print(f"[debug] No PSA URL matched for: {tournament.title}")
                continue

            if debug:
                print(f"[debug] Enriching '{tournament.title}' times from {psa_url}")

            division_times = await _scrape_psa_draw_times(context, psa_url, debug)

            for match in tournament.matches:
                if match.match_time or not match.player1 or not match.player2:
                    continue
                div_times = division_times.get(match.division, {})
                key = match_surname_key(match.player1, match.player2)
                match.match_time = div_times.get(key)

        await browser.close()


# ── Orchestration ─────────────────────────────────────────────────────────────

async def fetch_tournaments(
    limit: Optional[int],
    lookahead_days: int,
    reference_date: date,
    include_tbd: bool,
    debug: bool,
) -> List[Tournament]:
    """
    1. Fetch squashinfo calendar → event URLs
    2. For each event in the lookahead window, fetch matches (full names + scores)
    3. Enrich upcoming matches with PSA draw times via Playwright
    """
    if debug:
        print(f"[debug] Fetching squashinfo calendar…")

    calendar_html = await asyncio.to_thread(fetch_html, SQUASHINFO_CALENDAR_URL)
    raw_events    = parse_calendar_event_links(calendar_html)

    if debug:
        print(f"[debug] {len(raw_events)} event links on calendar")

    # Restrict to current year to avoid fetching obviously stale events
    current_year  = str(reference_date.year)
    raw_events    = [e for e in raw_events if current_year in e["url"]]
    if limit:
        raw_events = raw_events[:limit]

    tournament_map: Dict[str, Dict[str, Any]] = {}

    for event in raw_events:
        url      = event["url"]
        title    = event["title"]
        division = event["division"]

        if division not in ("Men", "Women"):
            continue

        if debug:
            print(f"[debug] Fetching {title} — {url}")

        try:
            html = await asyncio.to_thread(fetch_html, url)
        except Exception as exc:
            if debug:
                print(f"[debug] HTTP error for {url}: {exc}")
            continue

        start_date, end_date = parse_event_dates(html)

        if not is_within_window(start_date, end_date, reference_date, lookahead_days):
            if debug:
                print(f"[debug] Outside window: {title} [{start_date} – {end_date}]")
            continue

        base_title = strip_gender(title)

        if base_title not in tournament_map:
            tournament_map[base_title] = {
                "title":      base_title,
                "url":        url,
                "category":   infer_category(base_title),
                "start_date": start_date,
                "end_date":   end_date,
                "matches":    [],
            }

        division_matches = parse_event_matches(
            html             = html,
            tournament_title = base_title,
            tournament_url   = tournament_map[base_title]["url"],
            division         = division,
            include_tbd      = include_tbd,
            debug            = debug,
        )
        tournament_map[base_title]["matches"].extend(division_matches)

    tournaments = [
        Tournament(
            title      = t["title"],
            url        = t["url"],
            category   = t["category"],
            start_date = t["start_date"],
            end_date   = t["end_date"],
            matches    = t["matches"],
        )
        for t in tournament_map.values()
        if t["matches"]
    ]
    tournaments.sort(key=lambda t: (t.start_date or "9999", t.title))

    # Enrich upcoming matches with PSA match times
    if tournaments:
        if debug:
            print(f"[debug] Enriching match times from PSA…")
        await enrich_with_psa_times(tournaments, reference_date, lookahead_days, debug)

    return tournaments


# ── Snapshot ──────────────────────────────────────────────────────────────────

def load_snapshot() -> Dict[str, Any]:
    if not SNAPSHOT_FILE.exists():
        return {}
    try:
        return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_snapshot(events: List[Tournament]) -> None:
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "events":     [asdict(e) for e in events],
    }
    SNAPSHOT_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def print_human_report(
    events: List[Tournament],
    reference_date: date,
    lookahead_days: int,
) -> None:
    window_end = reference_date + timedelta(days=lookahead_days)
    print("\nUpcoming/current PSA tournaments")
    print("=" * 50)
    print(f"Date window: {reference_date.isoformat()} to {window_end.isoformat()}")

    if not events:
        print("No tournaments found in window.")
        return

    for event in events:
        date_part = f" [{event.start_date or '?'} to {event.end_date or '?'}]"
        print(f"\n{event.title}{date_part}")
        print(f"Category: {event.category or 'Unknown'}")
        print(f"URL: {event.url}")
        print(f"Matches: {len(event.matches)}")

        for match in event.matches[:60]:
            names  = f"{match.player1} vs {match.player2}"
            detail = " | ".join(filter(None, [
                match.division,
                match.round_name,
                match.match_time,
                f"Score: {match.score}" if match.score else None,
                f"Winner: {match.winner}" if match.winner else None,
            ]))
            print(f"  - {names}" + (f" — {detail}" if detail else ""))

        if len(event.matches) > 60:
            print(f"  … plus {len(event.matches) - 60} more")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json",        action="store_true")
    parser.add_argument("--limit",       type=int,  default=None)
    parser.add_argument("--days",        type=int,  default=LOOKAHEAD_DAYS)
    parser.add_argument("--today",       type=str,  default=None)
    parser.add_argument("--include-tbd", action="store_true")
    parser.add_argument("--debug",       action="store_true")
    args = parser.parse_args()

    reference_date = get_reference_date(args.today)

    events = await fetch_tournaments(
        limit          = args.limit,
        lookahead_days = args.days,
        reference_date = reference_date,
        include_tbd    = args.include_tbd,
        debug          = args.debug,
    )

    if args.json:
        print(json.dumps([asdict(e) for e in events], indent=2, ensure_ascii=False))
    else:
        print_human_report(events, reference_date, args.days)

    save_snapshot(events)


if __name__ == "__main__":
    asyncio.run(main())
