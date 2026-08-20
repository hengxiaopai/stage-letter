"""Gate 1.6 delivery execution indexes for retry and crash recovery.

Revision ID: a63f4b2d9e71
Revises: f16e2a7c4d10
Create Date: 2026-08-20

The delivery execution columns already exist. This forward-only revision adds
only the access paths required to select due work and stale IN_FLIGHT rows. It
does not rewrite delivery truth, grant truth, or logical delivery identity.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a63f4b2d9e71"
down_revision: Union[str, Sequence[str], None] = "f16e2a7c4d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DUE_INDEX = "idx_g163_delivery_due"
IN_FLIGHT_INDEX = "idx_g163_delivery_inflight"


def upgrade() -> None:
    op.create_index(
        DUE_INDEX,
        "notification_deliveries",
        ["state", "next_attempt_at", "id"],
        unique=False,
    )
    op.create_index(
        IN_FLIGHT_INDEX,
        "notification_deliveries",
        ["state", "in_flight_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 1.6 delivery-execution migration is forward-only; "
        "create a corrective revision instead"
    )
