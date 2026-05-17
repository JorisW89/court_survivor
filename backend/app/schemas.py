from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


# --- Auth ---

class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=72)


class UserLogin(BaseModel):
    identifier: str = Field(max_length=254)
    password: str = Field(max_length=72)


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


# --- Tournament ---

class TournamentResponse(BaseModel):
    id: int
    title: str
    category: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    status: str

    model_config = {"from_attributes": True}


# --- Round ---

class RoundResponse(BaseModel):
    id: int
    name: str
    round_order: int
    status: str
    first_match_time: Optional[datetime]
    pick_deadline: Optional[datetime]

    model_config = {"from_attributes": True}


# --- Player ---

class PlayerResponse(BaseModel):
    id: int
    name: str
    normalized_name: str
    already_picked: bool = False

    model_config = {"from_attributes": True}


# --- Pick ---

class PickCreate(BaseModel):
    game_id: int
    round_id: int
    player_id: int


class PickSummary(BaseModel):
    round_id: int
    round_name: str
    round_order: int
    player_id: int
    player_name: str
    is_correct: Optional[bool]
    points_awarded: int
    streak_points: int = 0
    ranking_bonus: int = 0
    player_rank: Optional[int] = None
    opponent_rank: Optional[int] = None
    opponent_name: Optional[str] = None

    model_config = {"from_attributes": True}


# --- Game ---

class MyParticipant(BaseModel):
    total_points: int
    current_streak: int
    my_picks: list[PickSummary]

    model_config = {"from_attributes": True}


class GameResponse(BaseModel):
    id: int
    division: str
    status: str
    tournament: TournamentResponse
    current_round: Optional[RoundResponse]
    participant_count: int
    my_participant: Optional[MyParticipant] = None

    model_config = {"from_attributes": True}


class PlayerForPick(BaseModel):
    id: int
    name: str
    already_picked: bool = False
    rank: Optional[int] = None
    opponent_rank: Optional[int] = None
    streak_points: int = 1
    ranking_bonus: int = 0
    potential_points: int = 1


class MatchForPick(BaseModel):
    match_id: int
    player1: PlayerForPick
    player2: PlayerForPick
    match_time: Optional[str] = None  # raw display string
    is_locked: bool = False  # true when < 1 hour before match start
    is_finished: bool = False


class RoundWithMatches(BaseModel):
    round: RoundResponse
    matches: list[MatchForPick]
    my_pick: Optional[int] = None  # player_id


# --- Leaderboard ---

class LeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    username: str
    total_points: int


class LeaderboardResponse(BaseModel):
    game: GameResponse
    entries: list[LeaderboardEntry]
    my_rank: Optional[int] = None


# --- Group ---

class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupMemberResponse(BaseModel):
    user_id: int
    username: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class GroupResponse(BaseModel):
    id: int
    name: str
    invite_code: str
    created_by: int
    created_at: datetime
    member_count: int

    model_config = {"from_attributes": True}


class GroupDetailResponse(BaseModel):
    id: int
    name: str
    invite_code: str
    created_by: int
    created_at: datetime
    members: list[GroupMemberResponse]

    model_config = {"from_attributes": True}


class GroupLeaderboardEntry(BaseModel):
    game_id: int
    tournament_title: str
    division: str
    entries: list[LeaderboardEntry]


class GroupGameItem(BaseModel):
    game_id: int
    tournament_title: str
    division: str
    game_status: str
    tournament_end_date: Optional[str]
    selected: bool


# --- Member picks ---

class MemberPicksForGame(BaseModel):
    game_id: int
    tournament_title: str
    division: str
    picks: list[PickSummary]


class MemberPicksResponse(BaseModel):
    user_id: int
    username: str
    games: list[MemberPicksForGame]


# --- Profile ---

class ProfileGameEntry(BaseModel):
    game_id: int
    tournament_title: str
    division: str
    game_status: str
    total_points: int
    rank: Optional[int]
    participants: int
    picks_made: int
    correct_picks: int


class ProfileStats(BaseModel):
    username: str
    member_since: datetime
    games_played: int
    total_points: int
    avg_points_per_game: float
    total_picks: int
    correct_picks: int
    pick_accuracy: float
    avg_rank: Optional[float]
    most_picked_player: Optional[str]
    games: list[ProfileGameEntry]


# --- Draw / Round results ---

class MatchResult(BaseModel):
    match_id: int
    player1_name: str
    player2_name: str
    winner_name: Optional[str]
    score: Optional[str]
    match_time: Optional[str]


class RoundResult(BaseModel):
    round_id: int
    round_name: str
    round_order: int
    status: str
    matches: list[MatchResult]


class DrawResponse(BaseModel):
    rounds: list[RoundResult]
