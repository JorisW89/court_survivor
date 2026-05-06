"""add ranking snapshots

Revision ID: 20260506_0001
Revises: None
Create Date: 2026-05-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260506_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if "users" not in existing_tables:
        _create_baseline_schema(existing_tables)
        existing_tables = set(sa.inspect(bind).get_table_names())

    if "tournament_ranking_snapshots" not in existing_tables:
        _create_ranking_snapshot_table()

    false_value = "FALSE" if bind.dialect.name == "postgresql" else "0"
    op.execute(f"UPDATE game_participants SET is_eliminated = {false_value}, eliminated_at_round_id = NULL")


def downgrade() -> None:
    op.drop_index("ix_tournament_ranking_snapshots_lookup", table_name="tournament_ranking_snapshots")
    op.drop_table("tournament_ranking_snapshots")


def _create_baseline_schema(existing_tables: set[str]) -> None:
    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("username", sa.String(), nullable=False),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_users_id"), "users", ["id"])
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
        op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    if "tournaments" not in existing_tables:
        op.create_table(
            "tournaments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("psa_url", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=True),
            sa.Column("start_date", sa.String(), nullable=True),
            sa.Column("end_date", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("timezone", sa.String(), nullable=True),
            sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_tournaments_id"), "tournaments", ["id"])
        op.create_index(op.f("ix_tournaments_psa_url"), "tournaments", ["psa_url"], unique=True)

    if "players" not in existing_tables:
        op.create_table(
            "players",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("normalized_name", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_players_id"), "players", ["id"])
        op.create_index(op.f("ix_players_normalized_name"), "players", ["normalized_name"], unique=True)

    if "rounds" not in existing_tables:
        op.create_table(
            "rounds",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tournament_id", sa.Integer(), nullable=False),
            sa.Column("division", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("round_order", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("first_match_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pick_deadline", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tournament_id", "division", "name", name="uq_round"),
        )
        op.create_index(op.f("ix_rounds_id"), "rounds", ["id"])

    if "matches" not in existing_tables:
        op.create_table(
            "matches",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tournament_id", sa.Integer(), nullable=False),
            sa.Column("round_id", sa.Integer(), nullable=True),
            sa.Column("division", sa.String(), nullable=True),
            sa.Column("player1_id", sa.Integer(), nullable=True),
            sa.Column("player2_id", sa.Integer(), nullable=True),
            sa.Column("winner_id", sa.Integer(), nullable=True),
            sa.Column("score", sa.String(), nullable=True),
            sa.Column("match_time", sa.DateTime(timezone=True), nullable=True),
            sa.Column("psa_raw_id", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["player1_id"], ["players.id"]),
            sa.ForeignKeyConstraint(["player2_id"], ["players.id"]),
            sa.ForeignKeyConstraint(["round_id"], ["rounds.id"]),
            sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"]),
            sa.ForeignKeyConstraint(["winner_id"], ["players.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_matches_id"), "matches", ["id"])
        op.create_index(op.f("ix_matches_psa_raw_id"), "matches", ["psa_raw_id"], unique=True)

    if "games" not in existing_tables:
        op.create_table(
            "games",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tournament_id", sa.Integer(), nullable=False),
            sa.Column("division", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("points_base", sa.Integer(), nullable=True),
            sa.Column("points_multiplier", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tournament_id", "division", name="uq_game"),
        )
        op.create_index(op.f("ix_games_id"), "games", ["id"])

    if "game_participants" not in existing_tables:
        op.create_table(
            "game_participants",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("game_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("is_eliminated", sa.Boolean(), nullable=True),
            sa.Column("eliminated_at_round_id", sa.Integer(), nullable=True),
            sa.Column("total_points", sa.Integer(), nullable=True),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["eliminated_at_round_id"], ["rounds.id"]),
            sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("game_id", "user_id", name="uq_participant"),
        )
        op.create_index(op.f("ix_game_participants_id"), "game_participants", ["id"])

    if "picks" not in existing_tables:
        op.create_table(
            "picks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("game_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("round_id", sa.Integer(), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.Column("points_awarded", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
            sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
            sa.ForeignKeyConstraint(["round_id"], ["rounds.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("game_id", "user_id", "round_id", name="uq_pick"),
        )
        op.create_index(op.f("ix_picks_id"), "picks", ["id"])

    if "groups" not in existing_tables:
        op.create_table(
            "groups",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("invite_code", sa.String(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_groups_id"), "groups", ["id"])
        op.create_index(op.f("ix_groups_invite_code"), "groups", ["invite_code"], unique=True)

    if "group_members" not in existing_tables:
        op.create_table(
            "group_members",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
        )
        op.create_index(op.f("ix_group_members_id"), "group_members", ["id"])

    if "rankings" not in existing_tables:
        op.create_table(
            "rankings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("division", sa.String(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False),
            sa.Column("player_name", sa.String(), nullable=False),
            sa.Column("country", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_rankings_id"), "rankings", ["id"])

    if "tournament_ranking_snapshots" not in existing_tables:
        _create_ranking_snapshot_table()


def _create_ranking_snapshot_table() -> None:
    op.create_table(
        "tournament_ranking_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("division", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("player_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournaments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tournament_id",
            "division",
            "normalized_name",
            name="uq_tournament_ranking_snapshot_player",
        ),
    )
    op.create_index(
        "ix_tournament_ranking_snapshots_lookup",
        "tournament_ranking_snapshots",
        ["tournament_id", "division", "normalized_name"],
    )
