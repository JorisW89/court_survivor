#!/usr/bin/env python3
"""
PSA tournament scraper — PSA-only approach:
  - psasquashtour.com  →  full player names, rankings, match times (Playwright, JS-rendered SPA)

Full player names and rankings are extracted directly from the H2H data-attributes
baked into the draw page DOM. No secondary source needed.

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

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import async_playwright, BrowserContext


# ── Constants ─────────────────────────────────────────────────────────────────

PSA_BASE            = "https://www.psasquashtour.com"
PSA_TOURNAMENTS_URL = "https://www.psasquashtour.com/tournaments/"

SNAPSHOT_FILE  = Path("psa_snapshot.json")
LOOKAHEAD_DAYS = 14

_PSA_ROUND_MAP: Dict[str, str] = {
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



# ── PSA scraping (Playwright) ─────────────────────────────────────────────────

async def _block_heavy_assets(context: BrowserContext) -> None:
    async def handler(route):
        if route.request.resource_type in {"image", "media", "font"}:
            await route.abort()
        else:
            await route.continue_()
    await context.route("**/*", handler)


_PSA_H2H_EXTRACT_JS = """() => {
    const ROUND_MAP = """ + json.dumps(_PSA_ROUND_MAP) + """;

    function normalizeRound(text) {
        return ROUND_MAP[text.trim().toLowerCase()] || text.trim();
    }

    function extractMatches(container) {
        const matches = [];
        container.querySelectorAll('a.show-head-to-head-modal[data-player1-name]').forEach(btn => {
            const p1 = btn.dataset.player1Name;
            const p2 = btn.dataset.player2Name;
            if (!p1 || !p2) return;

            const matchDetails = btn.closest('.match-details');
            const timeEl = matchDetails ? matchDetails.querySelector('.match-details-date') : null;
            const timeText = timeEl ? timeEl.textContent.trim() : null;
            if (!timeText) return;

            const roundDiv = btn.closest('.round');
            const roundEl = roundDiv ? roundDiv.querySelector('.round-heading') : null;
            const roundText = roundEl ? normalizeRound(roundEl.textContent) : null;

            matches.push({
                player1:         p1,
                player1_ranking: btn.dataset.player1Ranking || null,
                player1_country: btn.dataset.player1Country || null,
                player2:         p2,
                player2_ranking: btn.dataset.player2Ranking || null,
                player2_country: btn.dataset.player2Country || null,
                match_time:      timeText,
                round_name:      roundText,
            });
        });
        return matches;
    }

    const result = {};
    const mens   = document.querySelector('.tab-content.mens');
    const womens = document.querySelector('.tab-content.womens');
    if (mens)   result['Men']   = extractMatches(mens);
    if (womens) result['Women'] = extractMatches(womens);
    return result;
}"""


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
    Each match_dict has full player names, rankings, countries, match_time, round_name
    extracted from the H2H data-attributes baked into the DOM.
    """
    page = await context.new_page()
    result: Dict[str, List[Dict[str, Any]]] = {}

    try:
        await page.goto(psa_url, wait_until="domcontentloaded", timeout=45_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            await page.wait_for_timeout(4_000)

        raw = await page.evaluate(_PSA_H2H_EXTRACT_JS)

        for division, matches in raw.items():
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
    PSA-only pipeline:
    1. PSA listing    → tournament URLs, dates, locations, titles
    2. PSA draw pages → full player names, rankings, match times (from H2H DOM attributes)
    3. Build Tournament objects
    """

    psa_draw_data: Dict[str, Dict[str, Any]] = {}

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

    # ── Build Tournament objects ───────────────────────────────────────────────
    tournaments: List[Tournament] = []

    for psa_url, data in psa_draw_data.items():
        listing    = data["listing"]
        psa_title  = strip_gender(listing.get("title", "Unknown"))
        start_date = listing["start_date"]
        end_date   = listing["end_date"]
        location   = listing.get("location")

        all_matches: List[Match] = []

        for division, psa_matches in data["divisions"].items():
            for pm in psa_matches:
                p1 = pm["player1"]
                p2 = pm["player2"]

                raw_id = stable_hash({
                    "psa_url":  psa_url,
                    "division": division,
                    "surnames": sorted([extract_surname(p1), extract_surname(p2)]),
                })

                all_matches.append(Match(
                    tournament     = psa_title,
                    tournament_url = psa_url,
                    division       = division,
                    round_name     = pm.get("round_name"),
                    player1        = p1,
                    player2        = p2,
                    score          = None,
                    winner         = None,
                    status         = "upcoming",
                    match_time     = pm["match_time"],
                    source         = "psa",
                    raw_id         = raw_id,
                ))

        print(f"[enrich] '{psa_title}': {len(all_matches)} match(es) built")

        if all_matches:
            tournaments.append(Tournament(
                title        = psa_title,
                url          = psa_url,
                category     = infer_category(psa_title),
                start_date   = start_date,
                end_date     = end_date,
                psa_location = location,
                matches      = all_matches,
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
