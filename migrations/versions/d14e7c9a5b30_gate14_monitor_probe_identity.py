"""Gate 1.4 harden durable monitoring probe identity.

Revision ID: d14e7c9a5b30
Revises: c91e8d2f4a10
Create Date: 2026-08-19

Gate 1.4 scheduler-generated observations use observation_id values beginning
with ``monitor:``. The historical observation uniqueness remains source-scoped
for legacy/provider evidence, so two independent workers could otherwise commit
the same logical monitoring probe under different source strings.

This forward-only migration adds a partial unique index for formal monitoring
probe rows only. Legacy observation ids are not rewritten or deduplicated.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d14e7c9a5b30"
down_revision: Union[str, Sequence[str], None] = "c91e8d2f4a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "uq_g14_monitor_probe_identity"
PREDICATE = "observation_id LIKE 'monitor:%'"


def upgrade() -> None:
    """Protect one durable row per formal scheduler probe/account pair."""

    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            """
            SELECT platform_account_id, observation_id, COUNT(*) AS row_count
            FROM live_observations
            WHERE observation_id LIKE 'monitor:%'
            GROUP BY platform_account_id, observation_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Gate 1.4 durability migration found duplicate formal monitor probe rows; "
            "do not delete or rewrite evidence automatically"
        )

    op.create_index(
        INDEX_NAME,
        "live_observations",
        ["platform_account_id", "observation_id"],
        unique=True,
        postgresql_where=sa.text(PREDICATE),
    )


def downgrade() -> None:
    """Gate 1 formal migrations are forward-only by policy."""
    raise RuntimeError(
        "Gate 1.4 durability migration is forward-only; create a corrective revision instead"
    )
