import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .routers import admin, auth, games, groups, picks, tournaments


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]


async def _scraper_loop() -> None:
    from .database import SessionLocal
    from .models import Tournament
    from .services.scraper_service import run_scraper_and_sync

    while True:
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)

        # If last sync was more than 24 hours ago, run immediately instead of waiting.
        db = SessionLocal()
        try:
            last_synced = db.query(Tournament.last_synced).order_by(Tournament.last_synced.desc()).scalar()
        finally:
            db.close()

        if last_synced is not None:
            if last_synced.tzinfo is None:
                last_synced = last_synced.replace(tzinfo=timezone.utc)
            if (now - last_synced) > timedelta(hours=24):
                print(f"[scheduler] Last sync was {last_synced.isoformat()}, running catch-up scrape now")
                next_run = now

        wait_seconds = (next_run - now).total_seconds()
        if wait_seconds > 0:
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(tournaments.router, prefix="/api/tournaments", tags=["tournaments"])
app.include_router(games.router, prefix="/api/games", tags=["games"])
app.include_router(picks.router, prefix="/api/picks", tags=["picks"])
app.include_router(groups.router, prefix="/api/groups", tags=["groups"])


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}


# Serve built frontend in production
FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if settings.ENV == "production" and FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        index = FRONTEND_DIST / "index.html"
        return FileResponse(str(index))
