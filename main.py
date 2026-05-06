#!/usr/bin/env python3
"""
PSA tournament scraper — PSA-first approach:
  - psasquashtour.com  →  match pairs + times (Playwright, JS-rendered SPA)
  - squashinfo.com     →  full player names + scores (static HTML, name enrichment only)

PSA is the source of truth for match scheduling. Every match stored will have a
time. SquashInfo enriches player names (full name vs. abbreviated "M. ElShorbagy").
When SquashInfo has no match for a PSA entry, the PSA abbreviated name is kept.

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
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import async_playwright, BrowserContext, Page


# ── Constants ─────────────────────────────────────────────────────────────────

SQUASHINFO_BASE         = "https://www.squashinfo.com"
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

_PSA_ROUND_HEADERS: Dict[str, str] = {
    "round 1":       "Round 1",
    "round 2":       "Round 2",
    "round 3":       "Round 3",
    "round 4":       "Round 4",
    "round of 128":  "Round 1",
    "round of 64":   "Round 1",
    "round of 32":   "Round 2",
    "round of 16":   "Last 16",
    "last 64":       "Round 1",
    "last 32":       "Round 2",
    "last 16":       "Last 16",
    "quarter-final": "Quarter Final",
    "quarter final": "Quarter Final",
    "semi-final":    "Semi Final",
    "semi final":    "Semi Final",
    "final":         "Final",
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

SQUASHINFO_MATCH_RE = re.compile(
    r"(?:\[\s*[\w/]+\s*\]\s+)?"
    r"([A-Za-zÀ-ɏ][A-Za-zÀ-ɏ '\-\.]+?)"
    r"\s+\([A-Z]{3,4}\)"
    r"\s+(bt|v)\s+"
    r"(?:\[\s*[\w/]+\s*\]\s+)?"
    r"([A-Za-zÀ-ɏ][A-Za-zÀ-ɏ '\-\.]+?)"
    r"\s+\([A-Z]{3,4}\)",
)

SCORE_LINE_RE = re.compile(r"^\d{1,2}-\d{1,2}")


# ── Data classes ──────────────────────────────────────────────────────────────

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
    psa_location: Optional[str] = None
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


# ── Surname-pair matching ─────────────────────────────────────────────────────

def _normalize_surname_str(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*-\s*", "-", s)
    return s.lower()


def extract_surname(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\w+[\)\]]", "", name).strip()
    m = re.match(r"^[A-Z]\.\s+(.+)$", name)
    if m:
        return _normalize_surname_str(m.group(1).strip())
    parts = name.split()
    if len(parts) >= 2:
        return _normalize_surname_str(" ".join(parts[1:]).strip())
    return _normalize_surname_str(name.strip())


def match_surname_key(name1: str, name2: str) -> Tuple[str, str]:
    return tuple(sorted([extract_surname(name1), extract_surname(name2)]))


# ── Player name helpers ───────────────────────────────────────────────────────

def _is_tbd(name: str) -> bool:
    return name.lower().strip() in {"tbd", "t.b.d.", "to be determined", "bye", ""}


def _format_psa_name(name: str) -> str:
    """Strip seed/rank annotations: 'M. ElShorbagy (1)' → 'M. ElShorbagy'"""
    return re.sub(r"\s*[\(\[]\w+[\)\]]", "", name).strip()


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
    soup   = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if len(tables) < 2:
        return []

    match_table   = tables[1]
    matches: List[Match] = []
    seen:    set         = set()
    current_round: Optional[str] = None

    def _clean(td) -> str:
        return " ".join(td.get_text(" ").split())

    for row in match_table.find_all("tr"):
        td_type = row.find("td", class_="match_type")
        if td_type:
            key = td_type.get_text(strip=True).rstrip(":").strip().lower()
            current_round = ROUND_NORM.get(key, current_round)
            continue

        if not row.get("id", "").startswith("match_"):
            continue

        tds = row.find_all("td")
        if not tds:
            continue

        if len(tds) == 1:
            line  = _clean(tds[0])
            score = None
        else:
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

    return matches


# ── PSA scraping (Playwright) ─────────────────────────────────────────────────

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
    if not line or len(line) > 60:
        return False
    if not re.search(r"[A-Za-z]", line):
        return False
    if PSA_TIME_RE.search(line):
        return False
    if any(w in line.lower().split() for w in MONTH_WORDS):
        return False
    if re.fullmatch(r"[\d\s\-–—]+", line):
        return False
    return True


def _extract_psa_matches(visible_text: str) -> List[Dict[str, Any]]:
    """
    Parse PSA draw visible text → list of match dicts.
    Each match has: player1, player2 (abbreviated PSA names), match_time, round_name.
    Only matches with a scheduled time are returned.
    """
    lines = [l.strip() for l in visible_text.splitlines() if l.strip()]
    matches: List[Dict[str, Any]] = []
    current_round: Optional[str] = None

    for index, line in enumerate(lines):
        # Detect round headers (try exact key and without trailing 's')
        lk = line.lower().strip().rstrip(":").strip()
        for candidate in (lk, lk.rstrip("s")):
            if candidate in _PSA_ROUND_HEADERS:
                current_round = _PSA_ROUND_HEADERS[candidate]
                break

        if not PSA_TIME_RE.fullmatch(line):
            continue

        # Found time line — find the two player name lines before it
        scan_start = max(0, index - 18)
        candidates = [l for l in lines[scan_start:index] if _is_psa_player_line(l)]

        if len(candidates) < 2:
            continue

        p1, p2 = candidates[-2], candidates[-1]
        matches.append({
            "player1":    p1,
            "player2":    p2,
            "match_time": line,
            "round_name": current_round,
        })

    return matches


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
    """Scrape PSA tournament listing → [{url, title, start_date, end_date, location}]."""
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

        seen: set = set()
        for row in soup.select("table tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            date_text = cells[0].get_text(" ", strip=True)
            start_date, end_date = _parse_psa_table_date(date_text, reference_date.year)
            if not start_date:
                row_text = re.sub(r"\s+", " ", row.get_text(" ")).strip()
                start_date, end_date = _parse_psa_date_range(row_text, reference_date.year)

            if not is_within_window(start_date, end_date, reference_date, lookahead_days):
                continue

            location = cells[2].get_text(" ", strip=True) if len(cells) > 2 else None
            if location in ("-", ""):
                location = None

            # Detect tier from the LEVEL column image alt texts
            # e.g. alt="PSA World Tour Gold" vs alt="PSA Challenger Tour 3"
            img_alts = " ".join(img.get("alt", "") for img in row.find_all("img")).lower()
            is_challenger = "challenger" in img_alts

            for a in row.find_all("a", href=re.compile(r"/tournament/")):
                href  = a.get("href", "")
                url   = (PSA_BASE + href if href.startswith("/") else href)
                url   = url.split("#")[0].rstrip("/") + "/"
                title = a.get_text(strip=True) or "Unknown"
                if url not in seen:
                    seen.add(url)
                    results.append({
                        "url":          url,
                        "title":        title,
                        "start_date":   start_date,
                        "end_date":     end_date,
                        "location":     location,
                        "is_challenger": is_challenger,
                    })

        print(f"[enrich] PSA listing: {len(results)} tournament(s) in window")
    except Exception as exc:
        print(f"[enrich] PSA listing scrape failed: {exc}")
    finally:
        await page.close()

    return results


async def _scrape_psa_draw_matches(
    context: BrowserContext,
    psa_url: str,
    debug: bool,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scrape PSA draw page → {division: [match_dict]}.
    Each match_dict: {player1, player2, match_time, round_name} with PSA abbreviated names.
    """
    page   = await context.new_page()
    result: Dict[str, List[Dict[str, Any]]] = {}

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

            matches = _extract_psa_matches(visible_text)
            if matches:
                result[division] = matches
                if debug:
                    print(f"[debug] PSA {division}: {len(matches)} scheduled match(es)")

    except Exception as exc:
        print(f"[enrich] PSA draw scrape failed for {psa_url}: {exc}")
    finally:
        await page.close()

    return result


# ── Orchestration ─────────────────────────────────────────────────────────────

async def fetch_tournaments(
    limit: Optional[int],
    lookahead_days: int,
    reference_date: date,
    include_tbd: bool,
    debug: bool,
    world_events_only: bool = True,
) -> List[Tournament]:
    """
    PSA-first pipeline:
    1. PSA listing    → tournament URLs, dates, locations, titles
    2. PSA draw pages → match pairs + times (abbreviated names)
    3. SquashInfo     → full player names + scores (name enrichment only)
    4. Merge: use full names where matched, abbreviated PSA names otherwise
    """

    # ── Phase 1 & 2: PSA via Playwright ───────────────────────────────────────
    psa_draw_data: Dict[str, Dict[str, Any]] = {}  # psa_url → {listing, divisions}

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
            timezone_id="UTC",
        )
        await _block_heavy_assets(context)

        psa_listings = await _scrape_psa_listing(context, reference_date, lookahead_days, debug)

        if world_events_only:
            before = len(psa_listings)
            psa_listings = [l for l in psa_listings if not l.get("is_challenger")]
            print(f"[enrich] World Events filter: {len(psa_listings)}/{before} tournament(s) kept")

        if limit:
            psa_listings = psa_listings[:limit]

        for listing in psa_listings:
            division_matches = await _scrape_psa_draw_matches(context, listing["url"], debug)
            total = sum(len(v) for v in division_matches.values())
            if total:
                psa_draw_data[listing["url"]] = {
                    "listing":   listing,
                    "divisions": division_matches,
                }
                print(f"[enrich] '{listing['title']}': {total} scheduled match(es) from PSA")
            else:
                print(f"[enrich] '{listing['title']}': no scheduled matches found on PSA draw page")

        await browser.close()

    # ── Phase 3: SquashInfo name/score enrichment (requests) ──────────────────
    # Build a list of per-event lookups: {surname_pair → (full1, full2, score, winner, round_name)}
    si_events: List[Dict[str, Any]] = []

    if debug:
        print("[debug] Fetching SquashInfo calendar for name enrichment…")

    try:
        calendar_html = await asyncio.to_thread(fetch_html, SQUASHINFO_CALENDAR_URL)
        raw_events    = parse_calendar_event_links(calendar_html)
        current_year  = str(reference_date.year)
        raw_events    = [e for e in raw_events if current_year in e["url"]]

        for event in raw_events:
            division = event["division"]
            if division not in ("Men", "Women"):
                continue

            try:
                html = await asyncio.to_thread(fetch_html, event["url"])
            except Exception:
                continue

            start_date, end_date = parse_event_dates(html)
            # Use a generous window (60 days) so minor date mismatches on SquashInfo
            # don't silently drop events — dates_overlap() is the real filter when
            # we pair SquashInfo events against specific PSA tournaments.
            if not is_within_window(start_date, end_date, reference_date, 60):
                continue

            si_title  = strip_gender(event["title"])
            si_matches = parse_event_matches(
                html             = html,
                tournament_title = si_title,
                tournament_url   = event["url"],
                division         = division,
                include_tbd      = include_tbd,
                debug            = debug,
            )

            full_key_lookup: Dict[Tuple[str, str], tuple] = {}
            last_word_lookup: Dict[Tuple[str, str], tuple] = {}

            for m in si_matches:
                if not m.player1 or not m.player2:
                    continue
                entry    = (m.player1, m.player2, m.score, m.winner, m.round_name, si_title)
                full_key = match_surname_key(m.player1, m.player2)
                full_key_lookup.setdefault(full_key, entry)

                lw1    = extract_surname(m.player1).split()[-1]
                lw2    = extract_surname(m.player2).split()[-1]
                lw_key = tuple(sorted([lw1, lw2]))
                last_word_lookup.setdefault(lw_key, entry)

            si_events.append({
                "start":     start_date,
                "end":       end_date,
                "division":  division,
                "si_title":  si_title,
                "full_key":  full_key_lookup,
                "last_word": last_word_lookup,
            })

    except Exception as exc:
        print(f"[enrich] SquashInfo enrichment failed: {exc}")
        if debug:
            import traceback; traceback.print_exc()

    # ── Phase 4: Build Tournament objects ─────────────────────────────────────
    tournaments: List[Tournament] = []

    for psa_url, data in psa_draw_data.items():
        listing    = data["listing"]
        psa_title  = listing.get("title", "Unknown")
        start_date = listing["start_date"]
        end_date   = listing["end_date"]
        location   = listing.get("location")

        # Collect SquashInfo lookups whose dates overlap this PSA tournament
        matching_si: Dict[str, Dict[str, Any]] = {
            div: {"full_key": {}, "last_word": {}, "si_title": None}
            for div in ["Men", "Women"]
        }
        for si in si_events:
            if not dates_overlap(start_date, end_date, si["start"], si["end"]):
                continue
            div = si["division"]
            matching_si[div]["full_key"].update(si["full_key"])
            matching_si[div]["last_word"].update(si["last_word"])
            if si["si_title"] and not matching_si[div]["si_title"]:
                matching_si[div]["si_title"] = si["si_title"]

        # Prefer the longer SquashInfo title (sponsor names etc.) over PSA short title
        si_titles  = [v["si_title"] for v in matching_si.values() if v["si_title"]]
        best_title = max(si_titles, key=len) if si_titles else strip_gender(psa_title)

        all_matches: List[Match] = []
        enriched = 0

        for division, psa_matches in data["divisions"].items():
            full_kl = matching_si[division]["full_key"]
            lw_kl   = matching_si[division]["last_word"]

            for pm in psa_matches:
                p1_raw = pm["player1"]
                p2_raw = pm["player2"]

                # Skip TBD vs TBD always; skip one-sided TBD unless include_tbd
                both_tbd   = _is_tbd(p1_raw) and _is_tbd(p2_raw)
                either_tbd = _is_tbd(p1_raw) or _is_tbd(p2_raw)
                if both_tbd:
                    continue
                if not include_tbd and either_tbd:
                    continue

                # Look up SquashInfo full names: exact surname pair, then last-word fallback
                full_key = match_surname_key(p1_raw, p2_raw)
                lw1      = extract_surname(p1_raw).split()[-1]
                lw2      = extract_surname(p2_raw).split()[-1]
                lw_key   = tuple(sorted([lw1, lw2]))

                si_entry = full_kl.get(full_key) or lw_kl.get(lw_key)

                if si_entry:
                    p1_full, p2_full, score, winner, round_name, _ = si_entry
                    status = "completed" if winner else "upcoming"
                    enriched += 1
                else:
                    p1_full    = _format_psa_name(p1_raw)
                    p2_full    = _format_psa_name(p2_raw)
                    score      = None
                    winner     = None
                    round_name = pm.get("round_name")
                    status     = "upcoming"

                raw_id = stable_hash({
                    "psa_url":  psa_url,
                    "division": division,
                    "surnames": sorted([extract_surname(p1_raw), extract_surname(p2_raw)]),
                })

                all_matches.append(Match(
                    tournament     = best_title,
                    tournament_url = psa_url,
                    division       = division,
                    round_name     = round_name,
                    player1        = p1_full,
                    player2        = p2_full,
                    score          = score,
                    winner         = winner,
                    status         = status,
                    match_time     = pm["match_time"],
                    source         = "psa",
                    raw_id         = raw_id,
                ))

        total     = sum(len(v) for v in data["divisions"].values())
        kept      = len(all_matches)
        tbd_skip  = total - kept
        print(f"[enrich] '{best_title}': {kept}/{total} match(es) kept "
              f"({tbd_skip} TBD-filtered), {enriched}/{kept} enriched with SquashInfo full names")

        if all_matches:
            tournaments.append(Tournament(
                title      = best_title,
                url        = psa_url,
                category   = infer_category(best_title),
                start_date = start_date,
                end_date   = end_date,
                psa_location = location,
                matches    = all_matches,
            ))

    tournaments.sort(key=lambda t: (t.start_date or "9999", t.title))
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
    parser.add_argument("--json",              action="store_true")
    parser.add_argument("--limit",             type=int,  default=None)
    parser.add_argument("--days",              type=int,  default=LOOKAHEAD_DAYS)
    parser.add_argument("--today",             type=str,  default=None)
    parser.add_argument("--include-tbd",       action="store_true")
    parser.add_argument("--all-events",        action="store_true",
                        help="Include Challenger events (default: World Events only)")
    parser.add_argument("--debug",             action="store_true")
    args = parser.parse_args()

    reference_date = get_reference_date(args.today)

    events = await fetch_tournaments(
        limit             = args.limit,
        lookahead_days    = args.days,
        reference_date    = reference_date,
        include_tbd       = args.include_tbd,
        debug             = args.debug,
        world_events_only = not args.all_events,
    )

    if args.json:
        print(json.dumps([asdict(e) for e in events], indent=2, ensure_ascii=False))
    else:
        print_human_report(events, reference_date, args.days)

    save_snapshot(events)


if __name__ == "__main__":
    asyncio.run(main())
