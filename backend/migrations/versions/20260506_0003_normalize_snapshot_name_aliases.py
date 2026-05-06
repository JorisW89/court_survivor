"""normalize snapshot name aliases

Revision ID: 20260506_0003
Revises: 20260506_0002
Create Date: 2026-05-06
"""

from typing import Sequence, Union
import re
import unicodedata

from alembic import op
import sqlalchemy as sa


revision: str = "20260506_0003"
down_revision: Union[str, Sequence[str], None] = "20260506_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FIRST_NAME_ALIASES = {
    "samuel": "sam",
}


def _normalize_player_name(name: str) -> str:
    name = re.sub(r"\s*[\(\[]\d+[\)\]]", "", name or "")
    name = unicodedata.normalize("NFKD", name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = re.sub(r"[-–—]", " ", name)
    normalized = " ".join(name.split()).strip().lower()
    parts = normalized.split(" ", 1)
    if parts and parts[0] in FIRST_NAME_ALIASES:
        parts[0] = FIRST_NAME_ALIASES[parts[0]]
        normalized = " ".join(parts)
    return normalized


def _normalize_snapshots(connection) -> None:
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


def _normalize_players(connection) -> None:
    players = sa.table(
        "players",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("normalized_name", sa.String),
    )
    rows = connection.execute(sa.select(players.c.id, players.c.name)).mappings().all()
    for row in rows:
        connection.execute(
            players.update()
            .where(players.c.id == row["id"])
            .values(normalized_name=_normalize_player_name(row["name"]))
        )


def upgrade() -> None:
    connection = op.get_bind()
    _normalize_snapshots(connection)
    _normalize_players(connection)


def downgrade() -> None:
    pass
