"""Gate 1.1 EXPAND formal domain persistence.

Revision ID: a41f6c2e9b77
Revises: e98c1011d830
Create Date: 2026-08-19

This migration is intentionally additive. It introduces the formal Gate 1
persistence shape and performs only deterministic backfills from already
persisted legacy facts. It does not fabricate historical LiveObservation rows,
source start times, event causes, or provider/grant truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a41f6c2e9b77"
down_revision: Union[str, Sequence[str], None] = "e98c1011d830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """EXPAND + deterministic backfill only; no legacy drop/rename."""

    # ------------------------------------------------------------------
    # 1. Creator / profile split. Legacy anchors remain untouched.
    # ------------------------------------------------------------------
    op.create_table(
        "creators",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "creator_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", name="uq_creator_profiles_creator"),
    )

    # Deterministic identity bridge: one legacy anchor becomes one Creator with
    # the same numeric id. The profile fields are copied as persisted facts.
    op.execute(
        sa.text(
            """
            INSERT INTO creators (id, created_at, updated_at)
            SELECT id, created_at, updated_at
            FROM anchors
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO creator_profiles (
                creator_id, display_name, avatar_url, bio, created_at, updated_at
            )
            SELECT id, display_name, avatar, bio, created_at, updated_at
            FROM anchors
            ON CONFLICT (creator_id) DO NOTHING
            """
        )
    )
    # Explicit-id backfill must advance the creators sequence for future writes.
    op.execute(
        sa.text(
            """
            SELECT setval(
                pg_get_serial_sequence('creators', 'id'),
                COALESCE((SELECT MAX(id) FROM creators), 1),
                EXISTS (SELECT 1 FROM creators)
            )
            """
        )
    )

    op.add_column("platform_accounts", sa.Column("creator_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_g11_platform_accounts_creator",
        "platform_accounts",
        "creators",
        ["creator_id"],
        ["id"],
    )
    op.create_index("idx_g11_pa_creator", "platform_accounts", ["creator_id"], unique=False)
    op.execute(
        sa.text(
            """
            UPDATE platform_accounts
            SET creator_id = anchor_id
            WHERE creator_id IS NULL
            """
        )
    )

    # ------------------------------------------------------------------
    # 2. Follow and NotificationPreference split.
    # ------------------------------------------------------------------
    op.create_table(
        "follows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_account_id", sa.BigInteger(), nullable=False),
        sa.Column("starred", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["creators.id"]),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "platform_account_id", name="uq_follows_user_account"),
    )
    op.create_index("idx_g11_follows_creator", "follows", ["creator_id"], unique=False)

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("platform_account_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("silent_start", sa.Time(), nullable=True),
        sa.Column("silent_end", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "platform_account_id",
            name="uq_notification_pref_user_account",
        ),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO follows (
                user_id, creator_id, platform_account_id, starred, created_at, updated_at
            )
            SELECT
                user_id, anchor_id, platform_account_id, is_starred, created_at, updated_at
            FROM user_subscriptions
            ON CONFLICT (user_id, platform_account_id) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO notification_preferences (
                user_id, platform_account_id, enabled,
                silent_start, silent_end, created_at, updated_at
            )
            SELECT
                user_id, platform_account_id, notify_enabled,
                silent_start, silent_end, created_at, updated_at
            FROM user_subscriptions
            ON CONFLICT (user_id, platform_account_id) DO NOTHING
            """
        )
    )

    # ------------------------------------------------------------------
    # 3. LiveObservation becomes durable first-class evidence.
    #    IMPORTANT: no historical rows are synthesized here.
    # ------------------------------------------------------------------
    op.create_table(
        "live_observations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("observation_id", sa.String(length=255), nullable=False),
        sa.Column("platform_account_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["platform_account_id"], ["platform_accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform_account_id",
            "source",
            "observation_id",
            name="uq_live_observation_identity",
        ),
    )
    op.create_index(
        "idx_g11_observation_account_time",
        "live_observations",
        ["platform_account_id", "observed_at"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 4. Session/event formal provenance fields.
    # ------------------------------------------------------------------
    op.add_column("live_sessions", sa.Column("origin", sa.String(length=32), nullable=True))
    op.add_column(
        "live_sessions",
        sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    # This is the only safe historical source_started_at backfill: the legacy
    # row itself explicitly says started_at came from the platform.
    op.execute(
        sa.text(
            """
            UPDATE live_sessions
            SET source_started_at = started_at
            WHERE source_started_at IS NULL
              AND started_at_source = 'platform'
            """
        )
    )

    op.add_column("live_events", sa.Column("event_id", sa.String(length=255), nullable=True))
    op.add_column("live_events", sa.Column("cause", sa.String(length=32), nullable=True))
    op.add_column(
        "live_events",
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Event occurrence time is directly derivable from the persisted legacy
    # detection timestamp. Event identity/cause remain NULL when unknowable.
    op.execute(
        sa.text(
            """
            UPDATE live_events
            SET occurred_at = detected_at
            WHERE occurred_at IS NULL
            """
        )
    )
    op.create_index(
        "idx_g11_event_account_time",
        "live_events",
        ["platform_account_id", "occurred_at"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 5. Event-based delivery identity and durable send runtime fields.
    # ------------------------------------------------------------------
    op.add_column(
        "notification_deliveries",
        sa.Column("live_event_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_g11_delivery_live_event",
        "notification_deliveries",
        "live_events",
        ["live_event_id"],
        ["id"],
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("in_flight_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "notification_deliveries",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Widening only; supports the accepted Gate 0D state/channel vocabulary.
    op.alter_column(
        "notification_deliveries",
        "channel",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.alter_column(
        "notification_deliveries",
        "state",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
    )

    # Deterministic delivery->event bridge already exists through the legacy
    # notification_job foreign key. No event identity is guessed.
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

    # Hardening constraints on legacy-populated tables are deliberately deferred
    # to Gate 1.1-5 after representative upgrade verification.


def downgrade() -> None:
    """Gate 1 formal migrations are forward-only by policy."""
    raise RuntimeError(
        "Gate 1.1 EXPAND migration is forward-only; create a new corrective revision instead"
    )
