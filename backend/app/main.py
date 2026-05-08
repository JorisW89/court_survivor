import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


async def _scraper_loop() -> None:
    from .database import SessionLocal
    from .models import Tournament
    from .services.scraper_service import run_scraper_and_sync

    # One-time startup catch-up: run immediately if last sync is more than 24h ago.
    db = SessionLocal()
    try:
        last_synced = db.query(Tournament.last_synced).order_by(Tournament.last_synced.desc()).limit(1).scalar()
    finally:
        db.close()

    if last_synced is not None:
        if last_synced.tzinfo is None:
            last_synced = last_synced.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - last_synced) > timedelta(hours=24):
            print(f"[scheduler] Last sync was {last_synced.isoformat()}, running catch-up scrape now")
            db = SessionLocal()
            try:
                await run_scraper_and_sync(db)
            except Exception as e:
                print(f"[scheduler] Catch-up scrape failed: {e}")
            finally:
                db.close()

    # Regular daily schedule at 04:00 Amsterdam time (handles DST automatically).
    AMS = ZoneInfo("Europe/Amsterdam")
    while True:
        now = datetime.now(AMS)
        next_run = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        print(f"[scheduler] Next scrape at {next_run.isoformat()} (in {wait_seconds:.0f}s)")
        await asyncio.sleep(wait_seconds)

        db = SessionLocal()
        try:
            await run_scraper_and_sync(db)
        except Exception as e:
            print(f"[scheduler] Scraper failed: {e}")
        finally:
            db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENV == "development":
        from .database import SessionLocal
        from .services.scraper_service import run_scraper_and_sync
        from .seed import seed

        seed()

        async def startup_scrape():
            db = SessionLocal()
            try:
                await run_scraper_and_sync(db)
            except Exception as e:
                print(f"[startup] Scraper failed: {e}")
            finally:
                db.close()

        asyncio.create_task(startup_scrape())

    if settings.ENV == "production":
        asyncio.create_task(_scraper_loop())

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
