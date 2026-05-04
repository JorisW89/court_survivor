from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import settings
from .database import engine
from .models import Base
from .routers import auth, games, groups, picks, tournaments


def get_cors_origins() -> list[str]:
    return [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Seed test data and run scraper on startup in dev mode
    if settings.ENV == "development":
        from .database import SessionLocal
        from .services.scraper_service import run_scraper_and_sync
        from .seed import seed
        import asyncio

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

    yield


app = FastAPI(title="Court Survivor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
