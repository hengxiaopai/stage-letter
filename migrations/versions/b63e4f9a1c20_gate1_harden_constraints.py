"""Gate 1.1 harden formal persistence constraints.

Revision ID: b63e4f9a1c20
Revises: a41f6c2e9b77
Create Date: 2026-08-19

This revision remains additive/non-destructive. It hardens only facts that are
already deterministic after the Gate 1 EXPAND migration. Historical event
identity/cause/session origin remain nullable when they were not persisted.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b63e4f9a1c20"
down_revision: Union[str, Sequence[str], None] = "a41f6c2e9b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Harden deterministic Gate 1 constraints without deleting legacy data."""

    # creator_id is deterministic because EXPAND created Creator(id=anchor_id)
    # for every legacy anchor and copied platform_accounts.anchor_id.
    op.execute(
        sa.text(
            """
            UPDATE platform_accounts
            SET creator_id = anchor_id
            WHERE creator_id IS NULL
            """
        )
    )
    op.alter_column(
        "platform_accounts",
        "creator_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    # Canonical observation truth is exactly LIVE/OFFLINE/UNKNOWN.
    op.create_check_constraint(
        "ck_g11_live_observation_status",
        "live_observations",
        "status IN ('LIVE', 'OFFLINE', 'UNKNOWN')",
    )

    # Legacy sessions may have no provable origin, so NULL remains valid.
    op.create_check_constraint(
        "ck_g11_live_session_origin",
        "live_sessions",
        "origin IS NULL OR origin IN ('TRANSITION', 'BOOTSTRAP_LIVE')",
    )
    # Formal open-session truth is closed_at/ended_at IS NULL. If historical
    # rows violate this invariant, migration must stop instead of inventing an
    # end time or silently choosing a winner.
    op.create_index(
        "uq_g11_open_session_per_account",
        "live_sessions",
        ["platform_account_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    # occurred_at is directly backfilled from non-null detected_at in EXPAND.
    op.execute(
        sa.text(
            """
            UPDATE live_events
            SET occurred_at = detected_at
            WHERE occurred_at IS NULL
            """
        )
    )
    op.alter_column(
        "live_events",
        "occurred_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    # event_id remains nullable for legacy-unclassified rows; PostgreSQL UNIQUE
    # still permits multiple NULLs while protecting all formal event ids.
    op.create_unique_constraint(
        "uq_g11_live_event_id",
        "live_events",
        ["event_id"],
    )
    op.create_check_constraint(
        "ck_g11_live_event_cause",
        "live_events",
        "cause IS NULL OR cause IN ('TRANSITION', 'BOOTSTRAP_LIVE')",
    )

    # delivery->event is deterministic through the existing non-null
    # notification_job_id -> notification_jobs.live_event_id relation.
    op.execute(
        sa.text(
            """
            UPDATE notification_deliveries AS nd
            SET live_event_id = nj.live_event_id
            FROM notification_jobs AS nj
            WHERE nd.notification_job_id = nj.id
              AND nd.live_event_id IS NULL
            """
        )
    )
    op.alter_column(
        "notification_deliveries",
        "live_event_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )

    # Legacy channel "wechat" is an exact predecessor of the formal
    # WECHAT_SUBSCRIBE channel. Normalize it before creating event-keyed
    # idempotency so old and new sends cannot occupy different logical keys.
    op.execute(
        sa.text(
            """
            UPDATE notification_deliveries
            SET channel = 'WECHAT_SUBSCRIBE'
            WHERE channel = 'wechat'
            """
        )
    )
    op.create_unique_constraint(
        "uq_g11_delivery_user_event_channel",
        "notification_deliveries",
        ["user_id", "live_event_id", "channel"],
    )

    # updated_at is operational bookkeeping, deterministically derived for old
    # rows and required for formal writes. No provider outcome is inferred.
    op.execute(
        sa.text(
            """
            UPDATE notification_deliveries
            SET updated_at = COALESCE(updated_at, sent_at, created_at)
            WHERE updated_at IS NULL
            """
        )
    )
    op.alter_column(
        "notification_deliveries",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    """Gate 1 formal migrations are forward-only by policy."""
    raise RuntimeError(
        "Gate 1.1 hardening migration is forward-only; create a corrective revision instead"
    )
