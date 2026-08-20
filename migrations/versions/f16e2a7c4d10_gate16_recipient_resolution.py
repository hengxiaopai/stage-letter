"""Gate 1.6 recipient resolution and notification-preference repair.

Revision ID: f16e2a7c4d10
Revises: d14e7c9a5b30
Create Date: 2026-08-20

This revision does not create provider/grant truth. It adds the formal fan-out
access path and deterministically repairs Follow rows that are missing the
NotificationPreference which the accepted subscription contract creates with
enabled=True by default.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f16e2a7c4d10"
down_revision: Union[str, Sequence[str], None] = "d14e7c9a5b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "idx_g16_follows_account_user"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        "follows",
        ["platform_account_id", "user_id"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO notification_preferences (
                user_id,
                platform_account_id,
                enabled,
                silent_start,
                silent_end,
                created_at,
                updated_at
            )
            SELECT
                f.user_id,
                f.platform_account_id,
                TRUE,
                NULL,
                NULL,
                f.created_at,
                f.updated_at
            FROM follows AS f
            WHERE NOT EXISTS (
                SELECT 1
                FROM notification_preferences AS np
                WHERE np.user_id = f.user_id
                  AND np.platform_account_id = f.platform_account_id
            )
            ON CONFLICT (user_id, platform_account_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Gate 1.6 formal migration is forward-only; create a corrective revision instead"
    )
