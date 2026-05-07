"""drop elimination columns from game_participants

Revision ID: 20260507_0001
Revises: 20260506_0003
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260507_0001"
down_revision: Union[str, Sequence[str], None] = "20260506_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.drop_column("is_eliminated")
        batch_op.drop_column("eliminated_at_round_id")


def downgrade() -> None:
    with op.batch_alter_table("game_participants") as batch_op:
        batch_op.add_column(sa.Column("eliminated_at_round_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_eliminated", sa.Boolean(), nullable=True))
        batch_op.create_foreign_key(
            None, "rounds", ["eliminated_at_round_id"], ["id"]
        )
