from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db

router = APIRouter()


def verify_admin(x_admin_secret: str = Header(default="")):
    if not settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin secret not configured")
    if x_admin_secret != settings.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/scrape", dependencies=[Depends(verify_admin)])
async def trigger_scrape(db: Session = Depends(get_db)):
    from ..services.scraper_service import run_scraper_and_sync
    await run_scraper_and_sync(db)
    return {"status": "ok"}


@router.post("/scrape/tennis", dependencies=[Depends(verify_admin)])
async def trigger_tennis_scrape(db: Session = Depends(get_db)):
    from ..services.sofascore_service import run_tennis_scraper_and_sync
    await run_tennis_scraper_and_sync(db)
    return {"status": "ok"}
