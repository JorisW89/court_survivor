from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Tournament
from ..schemas import TournamentResponse

router = APIRouter()


@router.get("", response_model=list[TournamentResponse])
def list_tournaments(db: Session = Depends(get_db)):
    return (
        db.query(Tournament)
        .filter(Tournament.status.in_(["upcoming", "active"]))
        .order_by(Tournament.start_date)
        .all()
    )


@router.get("/{tournament_id}", response_model=TournamentResponse)
def get_tournament(tournament_id: int, db: Session = Depends(get_db)):
    t = db.get(Tournament, tournament_id)
    if not t:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tournament not found")
    return t
