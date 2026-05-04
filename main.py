#!/usr/bin/env python3

"""
Fetch upcoming/current PSA tournament draws and track daily result updates.

This version:
- Does NOT filter out Challenger or any tournament type
- Checks tournaments overlapping today through the next N days
- Always includes/overrides the World Championships manual tournament
- Opens each tournament page with Playwright
- Clicks MAIN DRAW
- Extracts MEN'S and WOMEN'S visible draw text
- Parses real draw rows from rendered text such as:
    M. Asal (1)
    0 - - - - -
    R. Kandra
    0 - - - - -
    08 MAY 2026 • 20:15
- Rejects fake player names such as "-", "0", "0 - - - - -"
- Saves a local snapshot to ./psa_snapshot.json
- Compares result changes on later runs

Install:
    pip install playwright beautifulsoup4 python-dateutil
    python -m playwright install chromium

Run:
    python main.py
    python main.py --debug
    python main.py --today 2026-05-03 --days 14 --debug
    python main.py --json
    python main.py --include-tbd
    python main.py --headed --debug
    python main.py --save-debug-files --debug
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from playwright.async_api import async_playwright, Page, BrowserContext


BASE_URL = "https://www.psasquashtour.com"
TOURNAMENTS_URL = "https://www.psasquashtour.com/tournaments/"
SNAPSHOT_FILE = Path("psa_snapshot.json")
DEBUG_DIR = Path("psa_debug")

LOOKAHEAD_DAYS = 14
MAX_CONCURRENT_PAGES = 3

MANUAL_TOURNAMENTS = [
    {
        "title": "CIB Palm Hills PSA World Championships 2025-2026",
        "url": "https://www.psasquashtour.com/tournament/psa-world-championships-2025-2026/",
        "card_text": "CIB Palm Hills PSA World Championships 2025-2026 08 May - 16 May 2026",
        "start_date": "2026-05-08",
        "end_date": "2026-05-16",
        "manual": True,
    }
]

BAD_PLAYER_PHRASES = [
    "head-to-head",
    "head-2-head",
    "compare",
    "select player",
    "no results",
    "wins",
    "years",
    "best ranking",
    "matches",
    "titles",
    "view all stats",
    "top seeds",
    "main draw",
    "results",
    "news",
    "add to calendar",
    "login",
    "rankings",
    "tournaments",
    "live scores",
    "squashtv",
    "psa",
    "tickets",
    "round",
    "quarter final",
    "semi final",
    "final",
    "men's",
    "women's",
    "head-to-head",
]

ROUND_PATTERNS = [
    r"ROUND\s+\d+",
    r"LAST\s+\d+",
    r"QUARTER\s*FINAL",
    r"QUARTER-FINAL",
    r"SEMI\s*FINAL",
    r"SEMI-FINAL",
    r"FINAL",
]

TIME_RE = re.compile(
    r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\s*•\s*\d{1,2}:\d{2}\b",
    flags=re.I,
)

MONTH_WORDS = {
    "jan", "january",
    "feb", "february",
    "mar", "march",
    "apr", "april",
    "may",
    "jun", "june",
    "jul", "july",
    "aug", "august",
    "sep", "september",
    "oct", "october",
    "nov", "november",
    "dec", "december",
}


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
    matches: List[Match]


def debug_print(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[debug] {message}")


def normalize_space(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", str(value)).strip()
    return value or None


def stable_hash(obj: Any) -> str:
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def safe_filename(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value[:100] or "debug"


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None

    try:
        return date_parser.parse(value).date()
    except Exception:
        return None


def get_reference_date(today_arg: Optional[str]) -> date:
    if today_arg:
        return date_parser.parse(today_arg).date()

    return datetime.now().date()


def parse_date_range(
    text: str,
    reference_year: Optional[int] = None,
) -> Tuple[Optional[str], Optional[str]]:
    text = normalize_space(text) or ""
    current_year = reference_year or datetime.now().year

    text = text.replace("–", "-").replace("—", "-")

    patterns = [
        r"(\d{1,2}\s+[A-Za-z]{3,9})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"([A-Za-z]{3,9}\s+\d{1,2})\s*-\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"([A-Za-z]{3,9}\s+\d{1,2})\s*-\s*([A-Za-z]{3,9}\s+\d{1,2})",
        r"(\d{1,2})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"(\d{1,2})\s*-\s*(\d{1,2}\s+[A-Za-z]{3,9})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue

        start_raw, end_raw = match.group(1), match.group(2)

        try:
            if not re.search(r"\d{4}", end_raw):
                end_raw = f"{end_raw} {current_year}"

            end_dt = date_parser.parse(end_raw, fuzzy=True).date()

            if re.fullmatch(r"\d{1,2}", start_raw):
                start_raw = f"{start_raw} {end_dt.strftime('%B')} {end_dt.year}"
            elif not re.search(r"\d{4}", start_raw):
                start_raw = f"{start_raw} {end_dt.year}"

            start_dt = date_parser.parse(start_raw, fuzzy=True).date()
            return start_dt.isoformat(), end_dt.isoformat()

        except Exception:
            continue

    return None, None


def is_within_lookahead_window(
    start_date: Optional[str],
    end_date: Optional[str],
    reference_date: date,
    days: int,
) -> bool:
    window_end = reference_date + timedelta(days=days)

    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)

    if not start and not end:
        return False

    if not start:
        start = end

    if not end:
        end = start

    if not start or not end:
        return False

    return start <= window_end and end >= reference_date


def looks_like_round(line: str) -> bool:
    line_upper = normalize_space(line or "") or ""

    for pattern in ROUND_PATTERNS:
        if re.fullmatch(pattern, line_upper, flags=re.I):
            return True

    return False


def normalize_round(line: str) -> Optional[str]:
    line = normalize_space(line)
    if not line:
        return None

    if looks_like_round(line):
        return line.title().replace("Final", "final").replace("Round", "Round")

    return None


def is_score_or_placeholder_line(line: str) -> bool:
    line = normalize_space(line) or ""

    if not line:
        return True

    if line in {"-", "—", "–"}:
        return True

    if re.fullmatch(r"\d+", line):
        return True

    # Examples:
    # 0 - - - - -
    # 0
    # - - - - -
    # 11 - 7
    if re.fullmatch(r"\d+\s+[-–—]\s+[-–—]\s+[-–—]\s+[-–—]\s+[-–—]", line):
        return True

    if re.fullmatch(r"[-–—\d\s]+", line):
        return True

    if re.fullmatch(r"\d{1,2}\s*[-–—]\s*\d{1,2}", line):
        return True

    return False


def clean_player_name(value: Optional[str]) -> Optional[str]:
    value = normalize_space(value)

    if not value:
        return None

    lowered = value.lower()

    # Critical fix: never treat these as player names.
    if lowered in {"-", "—", "–", "_", "0", "0 - - - - -"}:
        return None

    if is_score_or_placeholder_line(value):
        return None

    if lowered == "tbd":
        return "TBD"

    if lowered == "bye":
        return "BYE"

    if len(value) > 60:
        return None

    if TIME_RE.search(value):
        return None

    if any(month in lowered.split() for month in MONTH_WORDS):
        return None

    if any(phrase in lowered for phrase in BAD_PLAYER_PHRASES):
        return None

    if not re.search(r"[A-Za-z]", value):
        return None

    # Good examples:
    # M. Asal (1)
    # R. Kandra
    # Y. Soliman [12]
    # Mohamed ElShorbagy
    return value


def clean_score(value: Optional[str]) -> Optional[str]:
    value = normalize_space(value)

    if not value:
        return None

    lowered = value.lower()

    if TIME_RE.search(value):
        return None

    if any(month in lowered.split() for month in MONTH_WORDS):
        return None

    if re.fullmatch(r"\d{1,2}\s*[-–—]\s*\d{1,2}", value):
        # This is often a date range, not a squash score.
        return None

    if re.search(r"\b(?:wo|w/o|walkover|retired|ret\.?)\b", lowered):
        return value

    parts = re.findall(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\b", value)

    if len(parts) >= 2:
        return value

    if re.fullmatch(r"[0-3]\s*[-–]\s*[0-3]", value):
        return value

    return None


def extract_score_from_between(lines: List[str]) -> Optional[str]:
    text = " ".join(lines)
    return clean_score(text)


def is_real_match(match: Match, include_tbd: bool) -> bool:
    p1 = clean_player_name(match.player1)
    p2 = clean_player_name(match.player2)

    match.player1 = p1
    match.player2 = p2
    match.score = clean_score(match.score)

    if not p1 or not p2:
        return False

    both_tbd = p1 == "TBD" and p2 == "TBD"

    if both_tbd and not include_tbd:
        return False

    return True


async def block_heavy_assets(context: BrowserContext) -> None:
    async def route_handler(route):
        request = route.request

        # Do not block CSS; the site sometimes needs it for tabs/visibility.
        if request.resource_type in {"image", "media", "font"}:
            await route.abort()
        else:
            await route.continue_()

    await context.route("**/*", route_handler)


async def click_text_exact(page: Page, labels: List[str], debug: bool) -> bool:
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=True).first
            if await locator.count():
                debug_print(debug, f"Clicking: {label}")
                await locator.click(timeout=3_000)
                await page.wait_for_timeout(1_500)
                return True
        except Exception:
            pass

    return False


async def click_main_draw(page: Page, debug: bool) -> None:
    clicked = await click_text_exact(
        page,
        labels=["MAIN DRAW", "Main Draw", "Draw"],
        debug=debug,
    )

    if clicked:
        return

    try:
        await page.evaluate(
            """
            () => {
                const nodes = [...document.querySelectorAll('a,button,[role="tab"],[role="button"]')];
                for (const node of nodes) {
                    const txt = (node.innerText || node.textContent || '').trim().toUpperCase();
                    if (txt === 'MAIN DRAW' || txt === 'DRAW') {
                        node.click();
                        return true;
                    }
                }
                return false;
            }
            """
        )
        await page.wait_for_timeout(1_500)
    except Exception:
        pass


async def click_division(page: Page, division: str, debug: bool) -> bool:
    if division == "Men":
        labels = ["MEN'S", "Men's", "MENS", "Men"]
    else:
        labels = ["WOMEN'S", "Women's", "WOMENS", "Women"]

    clicked = await click_text_exact(page, labels=labels, debug=debug)

    if clicked:
        return True

    wanted = "MEN" if division == "Men" else "WOMEN"

    try:
        result = await page.evaluate(
            """
            (wanted) => {
                const nodes = [...document.querySelectorAll('a,button,[role="tab"],[role="button"],div,span')];
                for (const node of nodes) {
                    const txt = (node.innerText || node.textContent || '').trim().toUpperCase();
                    if (txt === wanted || txt === wanted + "'S") {
                        node.click();
                        return true;
                    }
                }
                return false;
            }
            """,
            wanted,
        )

        if result:
            debug_print(debug, f"Clicked division via JS: {division}")
            await page.wait_for_timeout(1_500)
            return True

    except Exception:
        pass

    return False


async def get_body_text(page: Page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=10_000)
    except Exception:
        return ""


async def get_html(page: Page) -> str:
    try:
        return await page.content()
    except Exception:
        return ""


def extract_tournament_links(
    html: str,
    reference_year: int,
    debug: bool,
) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}

    for a in soup.select("a[href*='/tournament/']"):
        href = a.get("href")
        if not href:
            continue

        url = urljoin(BASE_URL, href).split("#")[0].rstrip("/") + "/"

        container = a
        for _ in range(5):
            if container.parent:
                container = container.parent

        text = normalize_space(container.get_text(" ", strip=True)) or ""
        title = normalize_space(a.get_text(" ", strip=True))

        if not title:
            match = re.search(r"/tournament/([^/]+)/?", url)
            title = match.group(1).replace("-", " ").title() if match else url

        start_date, end_date = parse_date_range(text, reference_year=reference_year)

        found[url] = {
            "title": title,
            "url": url,
            "card_text": text,
            "start_date": start_date,
            "end_date": end_date,
            "manual": False,
        }

    debug_print(debug, f"Extracted {len(found)} tournament links from listing page")
    return list(found.values())


def upsert_manual_tournaments(
    tournament_links: List[Dict[str, Any]],
    debug: bool,
) -> List[Dict[str, Any]]:
    by_url = {
        item["url"].rstrip("/") + "/": item
        for item in tournament_links
    }

    for manual in MANUAL_TOURNAMENTS:
        normalized_url = manual["url"].rstrip("/") + "/"

        if normalized_url in by_url:
            debug_print(
                debug,
                f"Manual override applied: {manual['title']} "
                f"[{manual['start_date']} to {manual['end_date']}]",
            )
        else:
            debug_print(
                debug,
                f"Manual tournament inserted: {manual['title']} "
                f"[{manual['start_date']} to {manual['end_date']}]",
            )

        by_url[normalized_url] = {
            "title": manual["title"],
            "url": normalized_url,
            "card_text": manual["card_text"],
            "start_date": manual["start_date"],
            "end_date": manual["end_date"],
            "manual": True,
        }

    return list(by_url.values())


def extract_page_title(html: str, fallback: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if h1:
        title = normalize_space(h1.get_text(" ", strip=True))
        if title:
            return title

    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        title = normalize_space(og["content"])
        if title and "World No.1s" not in title:
            return title

    title_tag = soup.find("title")
    if title_tag:
        title = normalize_space(title_tag.get_text(" ", strip=True))
        if title and "World No.1s" not in title:
            return title.replace(" - PSA Squash Tour", "").strip()

    return fallback


def infer_category_from_text(text: str) -> Optional[str]:
    text = normalize_space(text) or ""
    lowered = text.lower()

    category_patterns = [
        "PSA World Tour Diamond",
        "PSA World Tour Platinum",
        "PSA World Tour Gold",
        "PSA World Tour Silver",
        "PSA World Tour Bronze",
        "PSA World Championships",
        "PSA World Championship",
        "PSA World Tour Finals",
        "PSA Challenger Tour",
        "PSA Challenger",
        "World Championships",
        "World Championship",
        "Diamond",
        "Platinum",
        "Gold",
        "Silver",
        "Bronze",
        "Challenger",
    ]

    for pattern in category_patterns:
        if pattern.lower() in lowered:
            return pattern

    return None


def parse_matches_from_visible_text(
    visible_text: str,
    tournament_title: str,
    tournament_url: str,
    division: str,
    include_tbd: bool,
    debug: bool,
) -> List[Match]:
    raw_lines = visible_text.splitlines()

    lines = []
    for line in raw_lines:
        cleaned = normalize_space(line)
        if cleaned:
            lines.append(cleaned)

    matches: List[Match] = []
    seen = set()

    current_round: Optional[str] = None

    for index, line in enumerate(lines):
        maybe_round = normalize_round(line)
        if maybe_round:
            current_round = maybe_round
            continue

        if not TIME_RE.fullmatch(line):
            continue

        match_time = line

        # Look backwards from the time line. In the rendered PSA draw, a match
        # usually appears as:
        #   Player 1
        #   0 - - - - -
        #   Player 2
        #   0 - - - - -
        #   08 MAY 2026 • 20:15
        scan_start = max(0, index - 18)
        previous_lines = lines[scan_start:index]

        player_candidates: List[Tuple[int, str]] = []

        for relative_i, previous in enumerate(previous_lines):
            player = clean_player_name(previous)
            if player:
                player_candidates.append((scan_start + relative_i, player))

        if len(player_candidates) < 2:
            debug_print(
                debug,
                f"No two player names found before {division} {match_time}. "
                f"Nearby lines: {previous_lines[-8:]}",
            )
            continue

        # Take the last two plausible player names before the match time.
        p1_index, p1 = player_candidates[-2]
        p2_index, p2 = player_candidates[-1]

        between_lines = lines[p1_index + 1:p2_index] + lines[p2_index + 1:index]
        score = extract_score_from_between(between_lines)

        match = Match(
            tournament=tournament_title,
            tournament_url=tournament_url,
            division=division,
            round_name=current_round,
            player1=p1,
            player2=p2,
            score=score,
            winner=None,
            status=None,
            match_time=match_time,
            source="visible-text",
            raw_id=stable_hash(
                {
                    "tournament": tournament_title,
                    "division": division,
                    "round": current_round,
                    "p1": p1,
                    "p2": p2,
                    "time": match_time,
                }
            ),
        )

        if not is_real_match(match, include_tbd=include_tbd):
            continue

        key = (
            match.division,
            match.round_name,
            match.player1,
            match.player2,
            match.match_time,
        )

        if key in seen:
            continue

        seen.add(key)
        matches.append(match)

    debug_print(
        debug,
        f"Parsed {len(matches)} visible-text matches for {division}",
    )

    return matches


def save_debug_files(
    title: str,
    html: str,
    division_texts: Dict[str, str],
    debug: bool,
) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)

    filename_base = safe_filename(title)

    html_path = DEBUG_DIR / f"{filename_base}.html"
    html_path.write_text(html, encoding="utf-8")
    debug_print(debug, f"Saved debug HTML: {html_path}")

    for division, text in division_texts.items():
        text_path = DEBUG_DIR / f"{filename_base}.{division.lower()}.visible-text.txt"
        text_path.write_text(text, encoding="utf-8")
        debug_print(debug, f"Saved debug visible text: {text_path}")


async def extract_tournament_draw_from_page(
    context: BrowserContext,
    item: Dict[str, Any],
    reference_date: date,
    lookahead_days: int,
    include_tbd: bool,
    save_debug: bool,
    debug: bool,
) -> Optional[Tournament]:
    page = await context.new_page()

    try:
        debug_print(debug, f"Opening tournament page: {item['url']}")
        await page.goto(item["url"], wait_until="domcontentloaded", timeout=45_000)

        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            await page.wait_for_timeout(4_000)

        await click_main_draw(page, debug=debug)

        html = await get_html(page)
        full_text = await get_body_text(page)

        title = extract_page_title(html, item["title"])

        if item.get("manual") and "World No.1s" in title:
            title = item["title"]

        category = (
            infer_category_from_text(full_text)
            or infer_category_from_text(item.get("card_text") or "")
        )

        page_start_date, page_end_date = parse_date_range(
            full_text,
            reference_year=reference_date.year,
        )

        start_date = page_start_date or item.get("start_date")
        end_date = page_end_date or item.get("end_date")

        if not is_within_lookahead_window(
            start_date=start_date,
            end_date=end_date,
            reference_date=reference_date,
            days=lookahead_days,
        ):
            if item.get("manual"):
                debug_print(
                    debug,
                    f"Page date looked outside window, keeping manual tournament anyway: {title}",
                )
                start_date = item.get("start_date")
                end_date = item.get("end_date")
            else:
                debug_print(
                    debug,
                    f"Skipping page outside date window: {title} [{start_date} to {end_date}]",
                )
                return None

        division_texts: Dict[str, str] = {}
        all_matches: List[Match] = []

        for division in ["Men", "Women"]:
            await click_main_draw(page, debug=debug)
            await click_division(page, division=division, debug=debug)
            await page.wait_for_timeout(1_500)

            visible_text = await get_body_text(page)
            division_texts[division] = visible_text

            division_matches = parse_matches_from_visible_text(
                visible_text=visible_text,
                tournament_title=title,
                tournament_url=item["url"],
                division=division,
                include_tbd=include_tbd,
                debug=debug,
            )

            all_matches.extend(division_matches)

        if save_debug:
            html = await get_html(page)
            save_debug_files(
                title=title,
                html=html,
                division_texts=division_texts,
                debug=debug,
            )

        deduped: List[Match] = []
        seen = set()

        for match in all_matches:
            key = (
                match.division,
                match.round_name,
                match.player1,
                match.player2,
                match.match_time,
            )

            if key in seen:
                continue

            seen.add(key)
            deduped.append(match)

        debug_print(
            debug,
            f"Keeping tournament: {title} [{start_date} to {end_date}], matches={len(deduped)}",
        )

        return Tournament(
            title=title,
            url=item["url"],
            category=category,
            start_date=start_date,
            end_date=end_date,
            matches=deduped,
        )

    except Exception as exc:
        debug_print(debug, f"Failed to extract tournament {item.get('title')}: {exc}")

        if item.get("manual"):
            return Tournament(
                title=item["title"],
                url=item["url"],
                category=None,
                start_date=item.get("start_date"),
                end_date=item.get("end_date"),
                matches=[],
            )

        return None

    finally:
        await page.close()


async def fetch_tournaments(
    limit: Optional[int],
    lookahead_days: int,
    reference_date: date,
    include_tbd: bool,
    save_debug: bool,
    headed: bool,
    debug: bool,
) -> List[Tournament]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 1100},
            locale="en-GB",
        )

        await block_heavy_assets(context)

        tournament_links: List[Dict[str, Any]] = []

        listing_page = await context.new_page()

        try:
            debug_print(debug, f"Opening listing page: {TOURNAMENTS_URL}")
            await listing_page.goto(TOURNAMENTS_URL, wait_until="domcontentloaded", timeout=45_000)

            try:
                await listing_page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                await listing_page.wait_for_timeout(4_000)

            listing_html = await get_html(listing_page)

            tournament_links = extract_tournament_links(
                html=listing_html,
                reference_year=reference_date.year,
                debug=debug,
            )

        except Exception as exc:
            debug_print(debug, f"Listing page failed, continuing with manual tournaments only: {exc}")

        finally:
            await listing_page.close()

        tournament_links = upsert_manual_tournaments(
            tournament_links=tournament_links,
            debug=debug,
        )

        debug_print(debug, f"Total tournament links after manual upsert: {len(tournament_links)}")

        candidates = []

        for item in tournament_links:
            start_date = item.get("start_date")
            end_date = item.get("end_date")

            if start_date or end_date:
                inside_window = is_within_lookahead_window(
                    start_date=start_date,
                    end_date=end_date,
                    reference_date=reference_date,
                    days=lookahead_days,
                )

                if not inside_window:
                    debug_print(
                        debug,
                        f"Skipping outside date window: {item.get('title')} "
                        f"[{start_date} to {end_date}]",
                    )
                    continue

                debug_print(
                    debug,
                    f"Candidate inside date window: {item.get('title')} "
                    f"[{start_date} to {end_date}] manual={item.get('manual')}",
                )

            else:
                debug_print(
                    debug,
                    f"Keeping no-date candidate for page inspection: "
                    f"{item.get('title')} {item.get('url')}",
                )

            candidates.append(item)

        if limit:
            candidates = candidates[:limit]

        debug_print(debug, f"Inspecting {len(candidates)} candidate tournament pages")

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

        async def inspect_with_limit(item: Dict[str, Any]) -> Optional[Tournament]:
            async with semaphore:
                return await extract_tournament_draw_from_page(
                    context=context,
                    item=item,
                    reference_date=reference_date,
                    lookahead_days=lookahead_days,
                    include_tbd=include_tbd,
                    save_debug=save_debug,
                    debug=debug,
                )

        results = await asyncio.gather(
            *[inspect_with_limit(item) for item in candidates]
        )

        await browser.close()

        events = [event for event in results if event is not None]

        events.sort(
            key=lambda event: (
                event.start_date or "9999-12-31",
                event.title,
            )
        )

        return events


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
        "events": [asdict(event) for event in events],
    }

    SNAPSHOT_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def match_index(events_payload: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}

    for event in events_payload:
        for match in event.get("matches", []):
            key = "|".join(
                [
                    event.get("title") or "",
                    match.get("division") or "",
                    match.get("round_name") or "",
                    match.get("player1") or "",
                    match.get("player2") or "",
                    match.get("match_time") or "",
                    match.get("raw_id") or "",
                ]
            )

            index[key] = match

    return index


def print_human_report(
    events: List[Tournament],
    previous: Dict[str, Any],
    reference_date: date,
    lookahead_days: int,
) -> None:
    window_end = reference_date + timedelta(days=lookahead_days)

    print("\nUpcoming/current PSA tournaments")
    print("=" * 45)
    print(f"Date window: {reference_date.isoformat()} to {window_end.isoformat()}")

    if not events:
        print("No upcoming/current tournaments found in the selected date window.")
        return

    for event in events:
        date_part = ""

        if event.start_date or event.end_date:
            date_part = f" [{event.start_date or '?'} to {event.end_date or '?'}]"

        print(f"\n{event.title}{date_part}")
        print(f"Category: {event.category or 'Unknown'}")
        print(f"URL: {event.url}")
        print(f"Matches/draw rows found: {len(event.matches)}")

        if not event.matches:
            print("  No real player match rows found yet.")
            print("  Try: python main.py --headed --debug")
            print("  Or:  python main.py --include-tbd --debug")

        for match in event.matches[:60]:
            names = " vs ".join(filter(None, [match.player1, match.player2])) or "Match"

            detail = " | ".join(
                filter(
                    None,
                    [
                        match.division,
                        match.round_name,
                        match.match_time,
                        f"Score: {match.score}" if match.score else None,
                        f"Winner: {match.winner}" if match.winner else None,
                    ],
                )
            )

            print(f"  - {names}" + (f" — {detail}" if detail else ""))

        if len(event.matches) > 60:
            print(f"  ... plus {len(event.matches) - 60} more")

    previous_events = previous.get("events", [])
    previous_idx = match_index(previous_events)
    current_idx = match_index([asdict(event) for event in events])

    changes = []

    for key, current in current_idx.items():
        old = previous_idx.get(key)

        if not old:
            if current.get("score") or current.get("winner") or current.get("status"):
                changes.append(("NEW", current))
            continue

        relevant_fields = ["score", "winner", "status"]

        if any((old.get(field) or None) != (current.get(field) or None) for field in relevant_fields):
            changes.append(("UPDATED", current))

    print("\nDaily result changes")
    print("=" * 45)

    if not previous:
        print("No previous snapshot found. Saved current state for future comparisons.")
    elif not changes:
        print("No new or changed results detected.")
    else:
        for kind, match in changes:
            names = " vs ".join(
                filter(None, [match.get("player1"), match.get("player2")])
            ) or "Match"

            detail = " | ".join(
                filter(
                    None,
                    [
                        match.get("tournament"),
                        match.get("division"),
                        match.get("round_name"),
                        match.get("match_time"),
                        match.get("status"),
                        f"Score: {match.get('score')}" if match.get("score") else None,
                        f"Winner: {match.get('winner')}" if match.get("winner") else None,
                    ],
                )
            )

            print(f"{kind}: {names} — {detail}")


async def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON output",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit tournament pages inspected",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=LOOKAHEAD_DAYS,
        help="Only check tournaments starting/running within this many days",
    )

    parser.add_argument(
        "--today",
        type=str,
        default=None,
        help="Override today's date, e.g. 2026-05-03",
    )

    parser.add_argument(
        "--include-tbd",
        action="store_true",
        help="Include TBD-vs-TBD placeholder draw rows",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser visibly instead of headless",
    )

    parser.add_argument(
        "--save-debug-files",
        action="store_true",
        help="Save rendered HTML and visible draw text to ./psa_debug",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print debug info",
    )

    args = parser.parse_args()

    reference_date = get_reference_date(args.today)

    previous = load_snapshot()

    events = await fetch_tournaments(
        limit=args.limit,
        lookahead_days=args.days,
        reference_date=reference_date,
        include_tbd=args.include_tbd,
        save_debug=args.save_debug_files,
        headed=args.headed,
        debug=args.debug,
    )

    if args.json:
        print(json.dumps([asdict(event) for event in events], indent=2, ensure_ascii=False))
    else:
        print_human_report(
            events=events,
            previous=previous,
            reference_date=reference_date,
            lookahead_days=args.days,
        )

    save_snapshot(events)


if __name__ == "__main__":
    asyncio.run(main())