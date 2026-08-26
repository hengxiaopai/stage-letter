"""D2 session history keyset indexes.

Revision ID: b71f6d2a4c90
Revises: a54e8b3c2d61
Create Date: 2026-08-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b71f6d2a4c90"
down_revision: Union[str, Sequence[str], None] = "a54e8b3c2d61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_d2_session_account_cursor",
        "live_sessions",
        ["platform_account_id", "started_at", "id"],
        unique=False,
    )
    op.create_index(
        "idx_d2_session_anchor_cursor",
        "live_sessions",
        ["anchor_id", "started_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError("D2 session insight indexes are forward-only")
