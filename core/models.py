"""StageLetter SQLAlchemy ORM 模型(Gate 1 Domain Core)。

严格对应 DATA-MODEL.md 的 11 张表 + v0.2 不变量。
v0.2.2(2026-08-12,Gate 0A 实测): wechat_subscription_grants 的 granted_count
注释更新为"可累积储备"(ADR-002)。
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import JSON, TypeDecorator


class JSONBCompat(TypeDecorator):
    """方言兼容 JSONB:PG 原生 JSONB,其他方言(SQLite 单测)退化为 JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Base(DeclarativeBase):
    pass


# ============================================================
# 枚举(与 7 态 / 事件类型对应)
# ============================================================


class LiveStatus(str, enum.Enum):
    """平台账号的实时状态(v0.2 7 态)。"""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    BLOCKED = "BLOCKED"
    PARSE_ERROR = "PARSE_ERROR"
    UNKNOWN = "UNKNOWN"

    # 状态机中间态(platform_accounts.last_status 专用)
    SUSPECT_ONLINE = "SUSPECT_ONLINE"
    SUSPECT_OFFLINE = "SUSPECT_OFFLINE"


class PollingTier(str, enum.Enum):
    """分级轮询档位(v0.2)。"""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class SessionState(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EventType(str, enum.Enum):
    SUSPECT_ONLINE = "SUSPECT_ONLINE"
    CONFIRMED_ONLINE = "CONFIRMED_ONLINE"
    SUSPECT_OFFLINE = "SUSPECT_OFFLINE"
    CONFIRMED_OFFLINE = "CONFIRMED_OFFLINE"


class JobState(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class DeliveryState(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class DeliveryChannel(str, enum.Enum):
    WECHAT = "wechat"
    IN_APP = "in_app"
    BARK = "bark"
    TELEGRAM = "telegram"


class PlatformHealthState(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


# ============================================================
# 1. users
# ============================================================


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    openid = Column(String(64), unique=True, nullable=False)
    unionid = Column(String(64))
    nickname = Column(String(64))
    avatar = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_active_at = Column(DateTime(timezone=True))

    subscriptions = relationship("UserSubscription", back_populates="user")


# ============================================================
# 2. anchors
# ============================================================


class Anchor(Base):
    __tablename__ = "anchors"

    id = Column(BigInteger, primary_key=True)
    display_name = Column(String(128), nullable=False)
    avatar = Column(Text)
    bio = Column(Text)
    # P0-11: Profile 持久化 — 搜索到 remote follower_count 时沉淀, null 不覆盖
    follower_count = Column(BigInteger)
    profile_last_verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    platform_accounts = relationship("PlatformAccount", back_populates="anchor")


# ============================================================
# 3. platform_accounts
# ============================================================


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_pa_platform_user"),
        Index("idx_pa_anchor", "anchor_id"),
        Index(
            "idx_pa_due",
            "platform",
            "is_disabled",
            "last_checked_at",
            postgresql_where="is_disabled = false",
        ),
        Index(
            "idx_pa_tier",
            "platform",
            "polling_tier",
            "is_disabled",
            postgresql_where="is_disabled = false",
        ),
    )

    id = Column(BigInteger, primary_key=True)
    anchor_id = Column(BigInteger, ForeignKey("anchors.id"), nullable=False)
    # Gate 1 canonical ownership.  The legacy API mapper intentionally keeps
    # ``anchor_id`` during the compatibility window, but every new row must
    # also satisfy the formal creator foreign key in PostgreSQL.
    creator_id = Column(BigInteger, nullable=False)
    platform = Column(String(32), nullable=False)
    platform_user_id = Column(String(128), nullable=False)
    room_id = Column(String(128))
    canonical_url = Column(Text, nullable=False)
    last_status = Column(
        String(16), nullable=False, default=LiveStatus.OFFLINE.value
    )
    last_checked_at = Column(DateTime(timezone=True))
    # P0: 状态新鲜度字段(2026-08-14 新增)
    #   last_probe_at: 最近一次探测执行时间(任何探测, 证明心跳活着)
    #   last_successful_probe_at: 最近一次可信探测时间(ONLINE/OFFLINE/NOT_FOUND)
    #   consecutive_probe_failures: 连续不可信探测次数(>阈值 → DEGRADED)
    last_probe_at = Column(DateTime(timezone=True))
    last_successful_probe_at = Column(DateTime(timezone=True))
    consecutive_probe_failures = Column(Integer, nullable=False, default=0)
    last_live_started_at = Column(DateTime(timezone=True))
    adapter_version = Column(String(32))
    is_disabled = Column(Boolean, nullable=False, default=False)
    polling_tier = Column(String(16), nullable=False, default=PollingTier.WARM.value)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    anchor = relationship("Anchor", back_populates="platform_accounts")
    subscriptions = relationship("UserSubscription", back_populates="platform_account")
    live_sessions = relationship("LiveSession", back_populates="platform_account")


# ============================================================
# 4. user_subscriptions
# ============================================================


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "platform_account_id", name="uq_sub_user_pa"
        ),
        Index("idx_subs_user", "user_id"),
        Index("idx_subs_anchor", "anchor_id"),
        Index("idx_subs_pa", "platform_account_id"),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    anchor_id = Column(BigInteger, ForeignKey("anchors.id"), nullable=False)
    platform_account_id = Column(
        BigInteger, ForeignKey("platform_accounts.id"), nullable=False
    )
    notify_enabled = Column(Boolean, nullable=False, default=True)
    is_starred = Column(Boolean, nullable=False, default=False)
    silent_start = Column(Time)
    silent_end = Column(Time)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="subscriptions")
    platform_account = relationship("PlatformAccount", back_populates="subscriptions")


# ============================================================
# 5. live_sessions
# ============================================================


class LiveSession(Base):
    __tablename__ = "live_sessions"
    __table_args__ = (
        Index("idx_session_pa_open", "platform_account_id", postgresql_where="state = 'OPEN'"),
        Index("idx_session_anchor_started", "anchor_id", "started_at"),
    )

    id = Column(BigInteger, primary_key=True)
    platform_account_id = Column(
        BigInteger, ForeignKey("platform_accounts.id"), nullable=False
    )
    anchor_id = Column(BigInteger, ForeignKey("anchors.id"), nullable=False)
    platform = Column(String(32), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    # 2026-08-14: 开播时间来源 — platform=平台真实开播时间 / probe=探测确认时刻(兜底, 非真实)
    started_at_source = Column(String(16), nullable=False, server_default="probe")
    ended_at = Column(DateTime(timezone=True))
    title = Column(Text)
    cover = Column(Text)
    viewer_count = Column(Integer)
    state = Column(String(16), nullable=False, default=SessionState.OPEN.value)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    platform_account = relationship("PlatformAccount", back_populates="live_sessions")

    # 不变量 #3:同一 platform_account 同一时刻只能有 1 个 OPEN session(partial unique index)


# 部分唯一索引:OPEN session 每 platform_account 只能一个
# (SQLAlchemy 2.x 用 Index + postgresql_where)
Index(
    "uniq_open_session_per_pa",
    LiveSession.platform_account_id,
    unique=True,
    postgresql_where="state = 'OPEN'",
)


# ============================================================
# 6. live_events (append-only)
# ============================================================


class LiveEvent(Base):
    __tablename__ = "live_events"
    __table_args__ = (
        Index("idx_events_pa_detected", "platform_account_id", "detected_at"),
        Index("idx_events_session", "live_session_id"),
    )

    id = Column(BigInteger, primary_key=True)
    platform_account_id = Column(
        BigInteger, ForeignKey("platform_accounts.id"), nullable=False
    )
    anchor_id = Column(BigInteger, ForeignKey("anchors.id"), nullable=False)
    live_session_id = Column(BigInteger, ForeignKey("live_sessions.id"))
    event_type = Column(String(32), nullable=False)
    confidence = Column(String(16), nullable=False, default="normal")
    detected_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSONBCompat)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================
# 7. wechat_subscription_grants
# ============================================================
# ADR-002 (2026-08-12): granted_count 可累积储备 — 连续授权 N 次 = N 条额度
# 一次授权 = 一条额度;微信侧 grant 可跨时间累积消耗(实验 A3-4 变体实证)


class WechatSubscriptionGrant(Base):
    __tablename__ = "wechat_subscription_grants"
    __table_args__ = (
        UniqueConstraint("user_id", "template_id", name="uq_grant_user_template"),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    template_id = Column(String(64), nullable=False)
    granted_count = Column(
        Integer, nullable=False, default=0,
        comment="用户主动 accept 次数(可累积储备,ADR-002)",
    )
    consumed_count = Column(Integer, nullable=False, default=0)
    last_granted_at = Column(DateTime(timezone=True))
    last_send_at = Column(DateTime(timezone=True))
    last_send_error = Column(String(255))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================
# 8. notification_jobs
# ============================================================


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (
        UniqueConstraint("live_event_id", "user_id", name="uq_nj_event_user"),
        Index("idx_nj_state", "state", "created_at"),
    )

    id = Column(BigInteger, primary_key=True)
    live_event_id = Column(BigInteger, ForeignKey("live_events.id"), nullable=False)
    live_session_id = Column(BigInteger, ForeignKey("live_sessions.id"))
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    anchor_id = Column(BigInteger, ForeignKey("anchors.id"), nullable=False)
    state = Column(String(16), nullable=False, default=JobState.PENDING.value)
    attempt = Column(Integer, nullable=False, default=0)  # 投递尝试次数(重试用)
    next_retry_at = Column(DateTime(timezone=True))  # 下次重试时间(指数退避)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at = Column(DateTime(timezone=True))

    deliveries = relationship("NotificationDelivery", back_populates="job")


# ============================================================
# 9. notification_deliveries
# ============================================================


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("user_id", "live_session_id", "channel", name="uq_nd_user_session_channel"),
        Index("idx_nd_state", "state"),
    )

    id = Column(BigInteger, primary_key=True)
    notification_job_id = Column(
        BigInteger, ForeignKey("notification_jobs.id"), nullable=False
    )
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    live_session_id = Column(BigInteger, ForeignKey("live_sessions.id"))
    channel = Column(String(16), nullable=False)
    state = Column(String(16), nullable=False, default=DeliveryState.PENDING.value)
    error_code = Column(String(64))
    error_message = Column(Text)
    attempt = Column(Integer, nullable=False, default=0)
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job = relationship("NotificationJob", back_populates="deliveries")


# ============================================================
# 10. platform_health
# ============================================================


class PlatformHealth(Base):
    __tablename__ = "platform_health"

    platform = Column(String(32), primary_key=True)
    state = Column(String(16), nullable=False, default=PlatformHealthState.HEALTHY.value)
    last_success_at = Column(DateTime(timezone=True))
    last_failure_at = Column(DateTime(timezone=True))
    success_rate_24h = Column(Numeric(5, 2))
    avg_latency_ms_24h = Column(Integer)
    consecutive_failures = Column(Integer, nullable=False, default=0)
    error_count_24h = Column(Integer, nullable=False, default=0)
    success_count_24h = Column(Integer, nullable=False, default=0)
    # v0.2 新增:Gate 0C 测量后写入
    sustained_qps = Column(Numeric(6, 2))
    max_anchors = Column(Integer)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================
# Gate 5 — administrative audit (operational only)
# ============================================================


class AdminPlatformAction(Base):
    __tablename__ = "admin_platform_actions"
    __table_args__ = (
        Index("idx_admin_platform_actions_platform_created", "platform", "created_at"),
    )

    id = Column(BigInteger, primary_key=True)
    actor_username = Column(String(128), nullable=False)
    platform = Column(String(32), nullable=False)
    requested_action = Column(String(16), nullable=False)
    prior_state = Column(String(16))
    resulting_state = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


# ============================================================
# 11. probe_runs (Gate 2 必须,轻量 telemetry)
# ============================================================


class ProbeRun(Base):
    __tablename__ = "probe_runs"
    __table_args__ = (
        Index("idx_pr_pa_started", "platform_account_id", "started_at"),
    )

    id = Column(BigInteger, primary_key=True)
    platform_account_id = Column(
        BigInteger, ForeignKey("platform_accounts.id"), nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    success = Column(Boolean)
    error_message = Column(Text)
    snapshot = Column(JSONBCompat)
