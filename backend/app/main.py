import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings
from .routers import admin, auth, games, groups, picks, tournaments

limiter = Limiter(key_func=get_remote_address)


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]


def _resolve_tz(tz_name: str | None) -> timezone | ZoneInfo:
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            pass
    return timezone.utc


def _compute_next_scrape_time(db, sport: str) -> datetime:
    """
    Decide when to run the next scrape for a given sport.

    Rules:
    - Any matches today (local tournament time) without a result yet:
        - If the first pending match hasn't started: schedule for 1h after it.
        - If matches have already started but results missing: scrape in 1h.
    - No pending matches today: find first match on the next match day,
      schedule for 1h after it starts.
    - No upcoming matches at all: check again in 24h.
    """
    from .models import Match, Tournament

    now = datetime.now(timezone.utc)

    # Find the timezone of the next upcoming match for this sport.
    tz_row = (
        db.query(Tournament.timezone)
        .join(Match, Match.tournament_id == Tournament.id)
        .filter(Tournament.sport == sport, Match.match_time >= now)
        .order_by(Match.match_time)
        .first()
    )
    tz = _resolve_tz(tz_row[0] if tz_row else None)

    now_local = now.astimezone(tz)
    today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_local_end = today_local_start + timedelta(days=1)
    today_start_utc = today_local_start.astimezone(timezone.utc)
    today_end_utc = today_local_end.astimezone(timezone.utc)

    pending_today = (
        db.query(Match.match_time)
        .join(Tournament, Match.tournament_id == Tournament.id)
        .filter(
            Tournament.sport == sport,
            Match.match_time >= today_start_utc,
            Match.match_time < today_end_utc,
            Match.winner_id.is_(None),
        )
        .order_by(Match.match_time)
        .first()
    )

    if pending_today:
        first_pending = pending_today[0]
        if first_pending.tzinfo is None:
            first_pending = first_pending.replace(tzinfo=timezone.utc)
        if first_pending > now:
            next_run = first_pending + timedelta(hours=1)
            print(f"[scheduler:{sport}] Match day active — first match at {first_pending.astimezone(tz).isoformat()}, next scrape at {next_run.astimezone(tz).isoformat()}")
        else:
            next_run = now + timedelta(hours=1)
            print(f"[scheduler:{sport}] Results still pending, next scrape at {next_run.astimezone(tz).isoformat()}")
        return next_run

    next_match = (
        db.query(Match.match_time, Tournament.timezone)
        .join(Tournament, Match.tournament_id == Tournament.id)
        .filter(Tournament.sport == sport, Match.match_time >= today_end_utc)
        .order_by(Match.match_time)
        .first()
    )

    if next_match:
        next_match_time, next_tz_name = next_match
        if next_match_time.tzinfo is None:
            next_match_time = next_match_time.replace(tzinfo=timezone.utc)
        next_tz = _resolve_tz(next_tz_name)
        next_run = next_match_time + timedelta(hours=1)
        if next_run <= now:
            next_run = now + timedelta(hours=1)
        print(f"[scheduler:{sport}] Next match day {next_match_time.astimezone(next_tz).isoformat()}, first scrape at {next_run.astimezone(next_tz).isoformat()}")
        return next_run

    next_run = now + timedelta(hours=24)
    print(f"[scheduler:{sport}] No upcoming matches; next check in 24h")
    return next_run


async def _scraper_loop(sport: str) -> None:
    from .database import SessionLocal
    from .models import Tournament

    scrape_fn = None
    if sport == "squash":
        from .services.scraper_service import run_scraper_and_sync
        scrape_fn = run_scraper_and_sync
    elif sport == "tennis":
        from .services.sofascore_service import run_tennis_scraper_and_sync
        scrape_fn = run_tennis_scraper_and_sync

    # Catch-up: run immediately if last sync for this sport is more than 4h ago.
    db = SessionLocal()
    try:
        last_synced = (
            db.query(Tournament.last_synced)
            .filter(Tournament.sport == sport)
            .order_by(Tournament.last_synced.desc())
            .limit(1)
            .scalar()
        )
    finally:
        db.close()

    needs_catchup = last_synced is None
    if last_synced is not None:
        if last_synced.tzinfo is None:
            last_synced = last_synced.replace(tzinfo=timezone.utc)
        needs_catchup = (datetime.now(timezone.utc) - last_synced) > timedelta(hours=4)

    if needs_catchup:
        reason = "no prior sync" if last_synced is None else f"last sync {last_synced.isoformat()}"
        print(f"[scheduler:{sport}] Catch-up scrape ({reason})")
        db = SessionLocal()
        try:
            await scrape_fn(db)
        except Exception as e:
            print(f"[scheduler:{sport}] Catch-up failed: {e}")
        finally:
            db.close()

    while True:
        db = SessionLocal()
        try:
            next_run = _compute_next_scrape_time(db, sport)
        finally:
            db.close()

        wait_seconds = max((next_run - datetime.now(timezone.utc)).total_seconds(), 0)
        await asyncio.sleep(wait_seconds)

        db = SessionLocal()
        try:
            await scrape_fn(db)
        except Exception as e:
            print(f"[scheduler:{sport}] Scrape failed: {e}")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENV == "development":
        from .database import SessionLocal
        from .services.scraper_service import run_scraper_and_sync
        from .services.sofascore_service import run_tennis_scraper_and_sync
        from .seed import seed

        seed()

        async def startup_scrape():
            db = SessionLocal()
            try:
                await run_scraper_and_sync(db)
            except Exception as e:
                print(f"[startup] Squash scraper failed: {e}")
            finally:
                db.close()

            db = SessionLocal()
            try:
                await run_tennis_scraper_and_sync(db)
            except Exception as e:
                print(f"[startup] Tennis scraper failed: {e}")
            finally:
                db.close()

        asyncio.create_task(startup_scrape())

    if settings.ENV == "production":
        asyncio.create_task(_scraper_loop("squash"))
        asyncio.create_task(_scraper_loop("tennis"))

    yield


app = FastAPI(title="Court Survivor", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(tournaments.router, prefix="/api/tournaments", tags=["tournaments"])
app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(picks.router, prefix="/api/picks", tags=["picks"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}
