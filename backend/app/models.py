from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    picks = relationship("Pick", back_populates="user")
    game_participants = relationship("GameParticipant", back_populates="user")
    groups_created = relationship("Group", back_populates="creator")
    group_memberships = relationship("GroupMember", back_populates="user")


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, index=True)
    psa_url = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String)
    start_date = Column(String)
    end_date = Column(String)
    status = Column(String, default="upcoming")  # upcoming, active, completed
    timezone = Column(String)  # IANA timezone of the tournament venue, e.g. "Europe/London"
    last_synced = Column(DateTime(timezone=True))

    rounds = relationship("Round", back_populates="tournament", cascade="all, delete-orphan")
    matches = relationship("Match", back_populates="tournament", cascade="all, delete-orphan")
    games = relationship("Game", back_populates="tournament", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, unique=True, index=True)


class Round(Base):
    __tablename__ = "rounds"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    division = Column(String, nullable=False)  # Men, Women
    name = Column(String, nullable=False)
    round_order = Column(Integer, nullable=False)
    status = Column(String, default="upcoming")  # upcoming, open, locked, completed
    first_match_time = Column(DateTime(timezone=True))
    pick_deadline = Column(DateTime(timezone=True))

    tournament = relationship("Tournament", back_populates="rounds")
    matches = relationship("Match", back_populates="round")
    picks = relationship("Pick", back_populates="round")

    __table_args__ = (UniqueConstraint("tournament_id", "division", "name", name="uq_round"),)


class Match(Base):
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    round_id = Column(Integer, ForeignKey("rounds.id"))
    division = Column(String)
    player1_id = Column(Integer, ForeignKey("players.id"))
    player2_id = Column(Integer, ForeignKey("players.id"))
    winner_id = Column(Integer, ForeignKey("players.id"))
    score = Column(String)
    match_time = Column(DateTime(timezone=True))
    psa_raw_id = Column(String, unique=True, index=True)

    tournament = relationship("Tournament", back_populates="matches")
    round = relationship("Round", back_populates="matches")
    player1 = relationship("Player", foreign_keys=[player1_id])
    player2 = relationship("Player", foreign_keys=[player2_id])
    winner = relationship("Player", foreign_keys=[winner_id])


class Game(Base):
    """One game per tournament+division combination."""

    __tablename__ = "games"

    id = Column(Integer, primary_key=True, index=True)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    division = Column(String, nullable=False)  # Men, Women
    status = Column(String, default="upcoming")  # upcoming, active, completed
    points_base = Column(Integer, default=1)
    points_multiplier = Column(Integer, default=2)

    tournament = relationship("Tournament", back_populates="games")
    participants = relationship("GameParticipant", back_populates="game", cascade="all, delete-orphan")
    picks = relationship("Pick", back_populates="game", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("tournament_id", "division", name="uq_game"),)


class GameParticipant(Base):
    __tablename__ = "game_participants"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_eliminated = Column(Boolean, default=False)
    eliminated_at_round_id = Column(Integer, ForeignKey("rounds.id"), nullable=True)
    total_points = Column(Integer, default=0)
    joined_at = Column(DateTime(timezone=True), default=_utcnow)

    game = relationship("Game", back_populates="participants")
    user = relationship("User", back_populates="game_participants")
    eliminated_at_round = relationship("Round", foreign_keys=[eliminated_at_round_id])

    __table_args__ = (UniqueConstraint("game_id", "user_id", name="uq_participant"),)


class Pick(Base):
    __tablename__ = "picks"

    id = Column(Integer, primary_key=True, index=True)
    game_id = Column(Integer, ForeignKey("games.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    round_id = Column(Integer, ForeignKey("rounds.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    submitted_at = Column(DateTime(timezone=True), default=_utcnow)
    is_correct = Column(Boolean, nullable=True)  # None = pending
    points_awarded = Column(Integer, default=0)

    game = relationship("Game", back_populates="picks")
    user = relationship("User", back_populates="picks")
    round = relationship("Round", back_populates="picks")
    player = relationship("Player")

    __table_args__ = (UniqueConstraint("game_id", "user_id", "round_id", name="uq_pick"),)


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    invite_code = Column(String, unique=True, nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    creator = relationship("User", back_populates="groups_created")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    joined_at = Column(DateTime(timezone=True), default=_utcnow)

    group = relationship("Group", back_populates="members")
    user = relationship("User", back_populates="group_memberships")

    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)


class Ranking(Base):
    __tablename__ = "rankings"

    id = Column(Integer, primary_key=True, index=True)
    division = Column(String, nullable=False)       # "Men" or "Women"
    rank = Column(Integer, nullable=False)
    player_name = Column(String, nullable=False)
    country = Column(String)
    updated_at = Column(DateTime(timezone=True), default=_utcnow)
