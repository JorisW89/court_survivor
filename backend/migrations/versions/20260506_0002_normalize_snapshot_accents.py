"""normalize snapshot accents

Revision ID: 20260506_0002
Revises: 20260506_0001
Create Date: 2026-05-06
"""

from typing import Sequence, Union
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision: str = "20260506_0002"
down_revision: Union[str, Sequence[str], None] = "20260506_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalize_player_name(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\d+[\)\]]", "", name or "")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    return " ".join(name.split()).strip().lower()


def upgrade() -> None:
    connection = op.get_bind()
    snapshots = sa.table(
        "tournament_ranking_snapshots",
        sa.column("id", sa.Integer),
        sa.column("tournament_id", sa.Integer),
        sa.column("division", sa.String),
        sa.column("rank", sa.Integer),
        sa.column("player_name", sa.String),
        sa.column("normalized_name", sa.String),
    )

    rows = connection.execute(
        sa.select(
            snapshots.c.id,
            snapshots.c.tournament_id,
            snapshots.c.division,
            snapshots.c.rank,
            snapshots.c.player_name,
        )
    ).mappings().all()

    grouped: dict[tuple[int, str, str], list] = {}
    for row in rows:
        key = (
            row["tournament_id"],
            row["division"],
            _normalize_player_name(row["player_name"]),
        )
        grouped.setdefault(key, []).append(row)

    for duplicate_rows in grouped.values():
        if len(duplicate_rows) <= 1:
            continue
        duplicate_rows = sorted(duplicate_rows, key=lambda row: (row["rank"] or 999999, row["id"]))
        for row in duplicate_rows[1:]:
            connection.execute(snapshots.delete().where(snapshots.c.id == row["id"]))

    kept_rows = [sorted(group, key=lambda row: (row["rank"] or 999999, row["id"]))[0] for group in grouped.values()]
    for row in kept_rows:
        connection.execute(
            snapshots.update()
            .where(snapshots.c.id == row["id"])
            .values(normalized_name=_normalize_player_name(row["player_name"]))
        )


def downgrade() -> None:
    pass
