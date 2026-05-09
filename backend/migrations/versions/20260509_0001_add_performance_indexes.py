"""add performance indexes on frequently queried FK columns

Revision ID: 20260509_0001
Revises: 20260507_0001
Create Date: 2026-05-09
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260509_0001"
down_revision: Union[str, None] = "20260507_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_rounds_tournament_id", "rounds", ["tournament_id"])
    op.create_index("ix_rounds_tournament_division", "rounds", ["tournament_id", "division"])
    op.create_index("ix_matches_tournament_id", "matches", ["tournament_id"])
    op.create_index("ix_matches_round_id", "matches", ["round_id"])
    op.create_index("ix_matches_player1_id", "matches", ["player1_id"])
    op.create_index("ix_matches_player2_id", "matches", ["player2_id"])
    op.create_index("ix_picks_game_id", "picks", ["game_id"])
    op.create_index("ix_picks_user_id", "picks", ["user_id"])
    op.create_index("ix_picks_round_id", "picks", ["round_id"])
    op.create_index("ix_game_participants_game_id", "game_participants", ["game_id"])
    op.create_index("ix_game_participants_user_id", "game_participants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_rounds_tournament_id", "rounds")
    op.drop_index("ix_rounds_tournament_division", "rounds")
    op.drop_index("ix_matches_tournament_id", "matches")
    op.drop_index("ix_matches_round_id", "matches")
    op.drop_index("ix_matches_player1_id", "matches")
    op.drop_index("ix_matches_player2_id", "matches")
    op.drop_index("ix_picks_game_id", "picks")
    op.drop_index("ix_picks_user_id", "picks")
    op.drop_index("ix_picks_round_id", "picks")
    op.drop_index("ix_game_participants_game_id", "game_participants")
    op.drop_index("ix_game_participants_user_id", "game_participants")
