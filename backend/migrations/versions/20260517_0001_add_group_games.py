"""add group_games table

Revision ID: 20260517_0001
Revises: 20260509_0001
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa

revision: str = "20260517_0001"
down_revision: str = "20260509_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_games",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=False, index=True),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False, index=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("group_id", "game_id", name="uq_group_game"),
    )


def downgrade() -> None:
    op.drop_table("group_games")
