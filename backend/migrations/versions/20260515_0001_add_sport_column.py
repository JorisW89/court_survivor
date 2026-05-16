"""add sport column to tournaments and rankings

Revision ID: 20260515_0001
Revises: 20260509_0001
Create Date: 2026-05-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260515_0001"
down_revision: Union[str, None] = "20260509_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't support ALTER COLUMN, so we use batch mode which rebuilds the table.
    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.add_column(
            sa.Column("sport", sa.String(), nullable=False, server_default="squash")
        )
        # Make psa_url nullable so tennis tournaments don't need a PSA URL
        batch_op.alter_column("psa_url", nullable=True)

    with op.batch_alter_table("rankings") as batch_op:
        batch_op.add_column(
            sa.Column("sport", sa.String(), nullable=False, server_default="squash")
        )


def downgrade() -> None:
    with op.batch_alter_table("rankings") as batch_op:
        batch_op.drop_column("sport")

    with op.batch_alter_table("tournaments") as batch_op:
        batch_op.alter_column("psa_url", nullable=False)
        batch_op.drop_column("sport")
