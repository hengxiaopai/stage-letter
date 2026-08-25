"""Gate 1 formal SQLAlchemy persistence models.

This module describes the post-Gate-1.2 compatibility persistence shape for the
ten frozen V0.1 domain entities. Existing legacy tables/columns remain readable
during the migration window; bridge fields are explicitly named ``legacy_*``
and are not part of the formal domain vocabulary.

Alembic remains the schema-change authority. Do not use ``metadata.create_all``
as a substitute for the forward-only Gate 1 migration chain.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    openid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    unionid: Mapped[str | None] = mapped_column(String(64))
    nickname: Mapped[str | None] = mapped_column(String(64))
    avatar: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreatorModel(Base):
    __tablename__ = "creators"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreatorProfileModel(Base):
    __tablename__ = "creator_profiles"
    __table_args__ = (UniqueConstraint("creator_id", name="uq_creator_profiles_creator"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformAccountModel(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_pa_platform_user"),
        Index("idx_g11_pa_creator", "creator_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False)
    legacy_anchor_id: Mapped[int | None] = mapped_column("anchor_id", BigInteger, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    room_id: Mapped[str | None] = mapped_column(String(128))
    canonical_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Administrative configuration only. Runtime health is persisted separately.
    is_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FollowModel(Base):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("user_id", "platform_account_id", name="uq_follows_user_account"),
        Index("idx_g11_follows_creator", "creator_id"),
        Index("idx_g16_follows_account_user", "platform_account_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), nullable=False)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), nullable=False)
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationPreferenceModel(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "platform_account_id", name="uq_notification_pref_user_account"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    silent_start: Mapped[time | None] = mapped_column(Time)
    silent_end: Mapped[time | None] = mapped_column(Time)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveObservationModel(Base):
    __tablename__ = "live_observations"
    __table_args__ = (
        UniqueConstraint(
            "platform_account_id",
            "source",
            "observation_id",
            name="uq_live_observation_identity",
        ),
        CheckConstraint(
            "status IN ('LIVE', 'OFFLINE', 'UNKNOWN')",
            name="ck_g11_live_observation_status",
        ),
        Index("idx_g11_observation_account_time", "platform_account_id", "observed_at"),
        Index(
            "uq_g14_monitor_probe_identity",
            "platform_account_id",
            "observation_id",
            unique=True,
            postgresql_where=text("observation_id LIKE 'monitor:%'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveSessionModel(Base):
    __tablename__ = "live_sessions"
    __table_args__ = (
        CheckConstraint(
            "origin IS NULL OR origin IN ('TRANSITION', 'BOOTSTRAP_LIVE')",
            name="ck_g11_live_session_origin",
        ),
        Index(
            "uq_g11_open_session_per_account",
            "platform_account_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index(
            "idx_live_sessions_account_room_started",
            "platform_account_id",
            "provider_room_id",
            "started_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), nullable=False)
    legacy_anchor_id: Mapped[int | None] = mapped_column("anchor_id", BigInteger, nullable=True)
    legacy_platform: Mapped[str | None] = mapped_column("platform", String(32), nullable=True)
    opened_at: Mapped[datetime] = mapped_column("started_at", DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column("ended_at", DateTime(timezone=True))
    origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    viewer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_room_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legacy_state: Mapped[str | None] = mapped_column("state", String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiveEventModel(Base):
    __tablename__ = "live_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_g11_live_event_id"),
        CheckConstraint(
            "cause IS NULL OR cause IN ('TRANSITION', 'BOOTSTRAP_LIVE')",
            name="ck_g11_live_event_cause",
        ),
        Index("idx_g11_event_account_time", "platform_account_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # event_id/cause remain nullable only for legacy rows whose truth was never persisted.
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), nullable=False)
    live_session_id: Mapped[int | None] = mapped_column(ForeignKey("live_sessions.id"))
    legacy_anchor_id: Mapped[int | None] = mapped_column("anchor_id", BigInteger, nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cause: Mapped[str | None] = mapped_column(String(32), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    legacy_detected_at: Mapped[datetime | None] = mapped_column(
        "detected_at", DateTime(timezone=True), nullable=True
    )
    legacy_confidence: Mapped[str | None] = mapped_column("confidence", String(16), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationDeliveryModel(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "live_event_id",
            "channel",
            name="uq_g11_delivery_user_event_channel",
        ),
        Index("idx_g11_delivery_state", "state"),
        Index(
            "idx_g163_delivery_due",
            "state",
            "next_attempt_at",
            "id",
        ),
        Index(
            "idx_g163_delivery_inflight",
            "state",
            "in_flight_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    legacy_notification_job_id: Mapped[int | None] = mapped_column(
        "notification_job_id", BigInteger, nullable=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    live_event_id: Mapped[int] = mapped_column(ForeignKey("live_events.id"), nullable=False)
    live_session_id: Mapped[int | None] = mapped_column(ForeignKey("live_sessions.id"))
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    in_flight_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
