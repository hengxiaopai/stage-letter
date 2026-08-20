"""Gate 5.2 append-only platform-control audit.

Revision ID: f52a9d1c4e81
Revises: e34d7a2c1b50
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f52a9d1c4e81"
down_revision: Union[str, Sequence[str], None] = "e34d7a2c1b50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_platform_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("actor_username", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("requested_action", sa.String(length=16), nullable=False),
        sa.Column("prior_state", sa.String(length=16), nullable=True),
        sa.Column("resulting_state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_admin_platform_actions_platform_created",
        "admin_platform_actions",
        ["platform", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError("Gate 5.2 administrative audit migration is forward-only")
