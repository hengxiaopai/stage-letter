"""Gate 1.2 relax legacy-only write bridges for formal repositories.

Revision ID: c91e8d2f4a10
Revises: b63e4f9a1c20
Create Date: 2026-08-19

The Gate 1.1 EXPAND path intentionally preserved legacy columns while the formal
schema was proven. Gate 1.2 now needs to write canonical domain rows without
fabricating obsolete anchor/job/status/provenance facts. This forward-only
compatibility revision therefore relaxes legacy-only NOT NULL requirements and
removes the obsolete session-keyed delivery uniqueness that conflicts with the
accepted event-keyed identity. It does not drop data columns or rewrite
historical rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c91e8d2f4a10"
down_revision: Union[str, Sequence[str], None] = "b63e4f9a1c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Permit new formal writes to leave non-canonical legacy facts unknown."""

    # PlatformAccount canonical ownership is creator_id. New formal accounts do
    # not require a fabricated legacy Anchor, stale live-status snapshot, or
    # polling tier. canonical_url is optional in the formal domain.
    op.alter_column(
        "platform_accounts",
        "anchor_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "platform_accounts",
        "canonical_url",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "platform_accounts",
        "last_status",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.alter_column(
        "platform_accounts",
        "polling_tier",
        existing_type=sa.String(length=16),
        nullable=True,
    )

    # Formal LiveSession truth is account + opened/closed time + origin.
    # Legacy anchor/platform/state/source-marker fields remain readable for old
    # rows but are no longer mandatory for new formal rows.
    op.alter_column(
        "live_sessions",
        "anchor_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "live_sessions",
        "platform",
        existing_type=sa.String(length=32),
        nullable=True,
    )
    op.alter_column(
        "live_sessions",
        "state",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.alter_column(
        "live_sessions",
        "started_at_source",
        existing_type=sa.String(length=16),
        nullable=True,
    )

    # Formal LiveEvent truth is event_id/account/session/type/cause/occurred_at.
    # Confidence and detected_at are legacy evidence fields and must not be
    # invented for new events merely to satisfy the old table shape.
    op.alter_column(
        "live_events",
        "anchor_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "live_events",
        "confidence",
        existing_type=sa.String(length=16),
        nullable=True,
    )
    op.alter_column(
        "live_events",
        "detected_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    # Formal delivery identity is (user_id, live_event_id, channel). A legacy
    # notification_job row is supporting queue bookkeeping, not canonical truth.
    op.alter_column(
        "notification_deliveries",
        "notification_job_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )

    # The old session-keyed uniqueness is strictly weaker/wrong for the formal
    # event-keyed model: two distinct LIVE_STARTED events may belong to the same
    # session across recovery/reconciliation scenarios. Gate 1.1 already created
    # uq_g11_delivery_user_event_channel, so the obsolete legacy uniqueness can
    # now be removed without losing the canonical idempotency guarantee.
    op.drop_constraint(
        "uq_nd_user_session_channel",
        "notification_deliveries",
        type_="unique",
    )


def downgrade() -> None:
    """Gate 1 formal migrations are forward-only by policy."""
    raise RuntimeError(
        "Gate 1.2 bridge migration is forward-only; create a corrective revision instead"
    )
