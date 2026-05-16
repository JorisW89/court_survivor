from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from ..auth import create_access_token, hash_password, verify_password, get_current_user
from ..database import get_db
from ..models import Game, GameParticipant, Pick, Player, Tournament, User
from ..schemas import ProfileGameEntry, ProfileStats, Token, UserCreate, UserLogin, UserResponse

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=Token)
@limiter.limit("10/minute")
def register(request: Request, payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return Token(
        access_token=create_access_token(user.id),
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=Token)
@limiter.limit("10/minute")
def login(request: Request, payload: UserLogin, db: Session = Depends(get_db)):
    user = (
        db.query(User).filter(User.email == payload.identifier).first()
        or db.query(User).filter(User.username == payload.identifier).first()
    )
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email/username or password")

    return Token(
        access_token=create_access_token(user.id),
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/stats", response_model=ProfileStats)
def get_my_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    participants = (
        db.query(GameParticipant)
        .filter(GameParticipant.user_id == current_user.id)
        .all()
    )
    picks = db.query(Pick).filter(Pick.user_id == current_user.id).all()

    games_played = len(participants)
    total_points = sum(p.total_points for p in participants)

    decided = [pk for pk in picks if pk.is_correct is not None]
    correct_count = sum(1 for pk in decided if pk.is_correct)
    pick_accuracy = round(correct_count / len(decided) * 100, 1) if decided else 0.0

    picks_by_game: dict[int, list] = {}
    for pk in picks:
        picks_by_game.setdefault(pk.game_id, []).append(pk)

    ranks: list[int] = []
    game_entries: list[ProfileGameEntry] = []
    for p in participants:
        game = db.get(Game, p.game_id)
        tournament = db.get(Tournament, game.tournament_id)
        all_ps = (
            db.query(GameParticipant)
            .filter(GameParticipant.game_id == p.game_id)
            .order_by(GameParticipant.total_points.desc(), GameParticipant.joined_at)
            .all()
        )
        rank = next((i + 1 for i, x in enumerate(all_ps) if x.user_id == current_user.id), None)
        if rank:
            ranks.append(rank)
        game_picks = picks_by_game.get(p.game_id, [])
        correct = sum(1 for pk in game_picks if pk.is_correct is True)
        game_entries.append(ProfileGameEntry(
            game_id=p.game_id,
            tournament_title=tournament.title,
            division=game.division,
            sport=tournament.sport,
            game_status=game.status,
            total_points=p.total_points,
            rank=rank,
            participants=len(all_ps),
            picks_made=len(game_picks),
            correct_picks=correct,
        ))

    game_entries.sort(key=lambda x: x.game_id, reverse=True)
    avg_rank = round(sum(ranks) / len(ranks), 1) if ranks else None

    player_counts = Counter(pk.player_id for pk in picks)
    most_picked_player = None
    if player_counts:
        top_id = player_counts.most_common(1)[0][0]
        player = db.get(Player, top_id)
        most_picked_player = player.name if player else None

    return ProfileStats(
        username=current_user.username,
        member_since=current_user.created_at,
        games_played=games_played,
        total_points=total_points,
        avg_points_per_game=round(total_points / games_played, 1) if games_played else 0.0,
        total_picks=len(picks),
        correct_picks=correct_count,
        pick_accuracy=pick_accuracy,
        avg_rank=avg_rank,
        most_picked_player=most_picked_player,
        games=game_entries,
    )
