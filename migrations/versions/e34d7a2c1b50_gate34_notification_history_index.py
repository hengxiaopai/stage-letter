"""Gate 3.4 notification-history keyset index.

Revision ID: e34d7a2c1b50
Revises: d33c4e8a1b60
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e34d7a2c1b50"
down_revision: Union[str, Sequence[str], None] = "d33c4e8a1b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_g34_delivery_user_history",
        "notification_deliveries",
        ["user_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 3.4 history-index migration is forward-only; create a corrective revision instead"
    )
