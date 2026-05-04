from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Game, GameParticipant, Match, Pick, Round
from ..schemas import PickCreate
from ..services.game_engine import get_or_create_participant

router = APIRouter()


@router.post("")
def submit_pick(
    payload: PickCreate,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    game = db.get(Game, payload.game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    round_obj = db.get(Round, payload.round_id)
    if not round_obj:
        raise HTTPException(status_code=404, detail="Round not found")

    # Check round belongs to this game's tournament+division
    if round_obj.tournament_id != game.tournament_id or round_obj.division != game.division:
        raise HTTPException(status_code=400, detail="Round does not belong to this game")

    # Check deadline
    if round_obj.pick_deadline and datetime.utcnow() > round_obj.pick_deadline:
        raise HTTPException(status_code=400, detail="Pick deadline has passed")

    if round_obj.status == "completed":
        raise HTTPException(status_code=400, detail="Round is already completed")

    # Check participant is not eliminated
    participant = db.query(GameParticipant).filter(
        GameParticipant.game_id == payload.game_id,
        GameParticipant.user_id == current_user.id,
    ).first()
    if participant and participant.is_eliminated:
        raise HTTPException(status_code=400, detail="You have been eliminated from this game")

    # Check player is in this round
    match = db.query(Match).filter(
        Match.round_id == payload.round_id,
        (Match.player1_id == payload.player_id) | (Match.player2_id == payload.player_id),
    ).first()
    if not match:
        raise HTTPException(status_code=400, detail="Player is not in this round")

    # Check player not already picked in this game
    previous_pick = db.query(Pick).filter(
        Pick.game_id == payload.game_id,
        Pick.user_id == current_user.id,
        Pick.player_id == payload.player_id,
    ).first()
    if previous_pick:
        raise HTTPException(status_code=400, detail="You already picked this player in this tournament")

    # Check for existing pick this round
    existing = db.query(Pick).filter(
        Pick.game_id == payload.game_id,
        Pick.user_id == current_user.id,
        Pick.round_id == payload.round_id,
    ).first()
    if existing:
        # Update existing pick
        existing.player_id = payload.player_id
        existing.submitted_at = datetime.utcnow()
        db.commit()
        return {"message": "Pick updated", "pick_id": existing.id}

    # Auto-enroll participant
    get_or_create_participant(db, payload.game_id, current_user.id)

    pick = Pick(
        game_id=payload.game_id,
        user_id=current_user.id,
        round_id=payload.round_id,
        player_id=payload.player_id,
    )
    db.add(pick)
    db.commit()
    db.refresh(pick)

    return {"message": "Pick submitted", "pick_id": pick.id}


@router.delete("/{game_id}/{round_id}")
def delete_pick(
    game_id: int,
    round_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    round_obj = db.get(Round, round_id)
    if round_obj and round_obj.pick_deadline and datetime.utcnow() > round_obj.pick_deadline:
        raise HTTPException(status_code=400, detail="Pick deadline has passed")

    pick = db.query(Pick).filter(
        Pick.game_id == game_id,
        Pick.user_id == current_user.id,
        Pick.round_id == round_id,
    ).first()
    if not pick:
        raise HTTPException(status_code=404, detail="Pick not found")

    db.delete(pick)
    db.commit()
    return {"message": "Pick deleted"}
