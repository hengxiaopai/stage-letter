"""Infrastructure-free repository and transaction ports for Gate 1.

These protocols define what the application layer may ask persistence to do.
They deliberately avoid SQLAlchemy, Redis, FastAPI, Dramatiq, provider SDKs,
and imports from experiments/*.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, runtime_checkable

from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import (
    LiveEvent,
    LiveObservation,
    LiveSession,
    SessionOrigin,
)
from stage_letter.domain.notifications import (
    DeliveryChannel,
    DeliveryKey,
    NotificationDelivery,
    WeChatGrantLedger,
)
from stage_letter.domain.grant_intake import WeChatGrantIntake
from stage_letter.domain.notification_templates import WeChatTemplateRegistration
from stage_letter.domain.notification_history import NotificationHistoryEntry


@dataclass(frozen=True)
class ObservationReplayRecord:
    """Persistence-order cursor plus one durable formal monitoring observation.

    ``sequence`` is an opaque replay cursor, not a domain identity. Gate 1.5 uses
    it only to reproduce durable arrival order across process restart without
    inventing a new canonical state entity.
    """

    sequence: int
    observation: LiveObservation

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("observation replay sequence must be positive")


@runtime_checkable
class CreatorRepository(Protocol):
    async def get_creator(self, creator_id: str) -> Creator | None: ...

    async def get_profile(self, creator_id: str) -> CreatorProfile | None: ...

    async def get_account(self, account_id: str) -> PlatformAccount | None: ...

    async def get_account_by_platform_identity(
        self,
        platform: str,
        platform_user_id: str,
    ) -> PlatformAccount | None: ...

    async def list_enabled_accounts(
        self,
        *,
        after_account_id: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformAccount, ...]:
        """Return explicitly enabled accounts in stable account-id order."""
        ...

    async def save_creator(self, creator: Creator) -> None: ...

    async def save_profile(self, profile: CreatorProfile) -> None: ...

    async def save_account(self, account: PlatformAccount) -> None: ...


@runtime_checkable
class FollowRepository(Protocol):
    async def get_follow(self, user_id: str, account_id: str) -> Follow | None: ...

    async def list_follows_for_account(
        self,
        account_id: str,
        *,
        created_at_lte: datetime | None = None,
        after_user_id: str | None = None,
        limit: int = 500,
    ) -> tuple[Follow, ...]:
        """Return followers in stable user-id order, optionally event-time bounded."""
        ...

    async def save_follow(self, follow: Follow) -> None: ...

    async def delete_follow(self, user_id: str, account_id: str) -> None: ...

    async def get_notification_preference(
        self,
        user_id: str,
        account_id: str,
    ) -> NotificationPreference | None: ...

    async def save_notification_preference(
        self,
        preference: NotificationPreference,
    ) -> None: ...


@runtime_checkable
class LiveRepository(Protocol):
    async def has_observation(
        self,
        account_id: str,
        source: str,
        observation_id: str,
    ) -> bool:
        """Return whether the exact source-scoped durable observation exists."""
        ...

    async def get_observation(
        self,
        account_id: str,
        observation_id: str,
    ) -> LiveObservation | None:
        """Return one durable logical observation regardless of provider source."""
        ...

    async def append_observation(self, observation: LiveObservation) -> bool:
        """Insert the observation if permitted by durable identity constraints."""
        ...

    async def list_monitor_observations(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[ObservationReplayRecord, ...]:
        """Return formal ``monitor:*`` observations in durable persistence order."""
        ...

    async def get_latest_observation(self, account_id: str) -> LiveObservation | None: ...

    async def acquire_transition_lock(self, account_id: str) -> None:
        """Serialize canonical session/event mutation for one account transaction.

        This is a persistence coordination primitive only. It does not imply
        exactly-once worker or provider execution and must be released by the
        surrounding transaction boundary on commit/rollback.
        """
        ...

    async def get_open_session(self, account_id: str) -> LiveSession | None: ...

    async def get_session(self, session_id: str) -> LiveSession | None:
        """Return a canonical formal session by persistence-owned identity."""
        ...

    async def create_session(
        self,
        account_id: str,
        *,
        opened_at: datetime,
        origin: SessionOrigin,
        source_started_at: datetime | None = None,
        observation: LiveObservation | None = None,
    ) -> LiveSession:
        """Allocate a persistence-owned BIGINT session identity and return it.

        The application/domain layers never derive a numeric session id from an
        observation, provider identity, hash, or timestamp.
        """
        ...

    async def save_session(self, session: LiveSession) -> None: ...

    async def append_event(self, event: LiveEvent) -> bool:
        """Insert a canonical event iff its deterministic event_id is absent."""
        ...

    async def get_event(self, event_id: str) -> LiveEvent | None: ...


@runtime_checkable
class NotificationRepository(Protocol):
    async def get_delivery(self, key: DeliveryKey) -> NotificationDelivery | None: ...

    async def create_delivery(self, delivery: NotificationDelivery) -> bool:
        """Create iff absent; return False when the logical delivery already exists."""
        ...

    async def save_delivery(self, delivery: NotificationDelivery) -> None: ...

    async def list_due_delivery_keys(
        self,
        now: datetime,
        *,
        limit: int = 100,
        channel: DeliveryChannel | None = None,
    ) -> tuple[DeliveryKey, ...]:
        """Return PENDING / due WAITING_RETRY keys in stable persistence order."""
        ...

    async def list_stale_in_flight_keys(
        self,
        stale_before: datetime,
        *,
        limit: int = 100,
        channel: DeliveryChannel | None = None,
    ) -> tuple[DeliveryKey, ...]:
        """Return stale IN_FLIGHT keys for conservative crash recovery."""
        ...

    async def lock_delivery(self, key: DeliveryKey) -> NotificationDelivery | None:
        """Lock one logical delivery if available, skipping an already-locked row."""
        ...

    async def list_history_for_user(
        self,
        user_id: str,
        *,
        before_delivery_id: int | None = None,
        limit: int = 21,
    ) -> tuple[NotificationHistoryEntry, ...]:
        """Return formal deliveries newest-first using a stable id cursor."""
        ...


@runtime_checkable
class GrantRepository(Protocol):
    async def get_wechat_grant(
        self,
        user_id: str,
        template_id: str,
    ) -> WeChatGrantLedger | None:
        """Return the optimistic local WeChat grant ledger, or None when absent."""
        ...

    async def consume_wechat_grant(
        self,
        user_id: str,
        template_id: str,
        *,
        sent_at: datetime,
        error_code: str | None = None,
    ) -> WeChatGrantLedger | None:
        """Record one provider-authoritative consumed send opportunity.

        The row is locked by persistence. Consumption is allowed to exceed the
        optimistic granted_count because the provider send result is stronger
        evidence than the local ledger and Gate 0A explicitly permits drift.
        None means the expected ledger row is missing.
        """
        ...

    async def create_wechat_grant_intake(
        self,
        intake: WeChatGrantIntake,
    ) -> bool:
        """Insert client evidence iff its user/request/template key is absent."""
        ...

    async def get_wechat_grant_intake(
        self,
        user_id: str,
        request_id: str,
        template_id: str,
    ) -> WeChatGrantIntake | None: ...

    async def increment_wechat_grant(
        self,
        user_id: str,
        template_id: str,
        *,
        granted_at: datetime,
    ) -> WeChatGrantLedger:
        """Atomically add one accepted client-reported grant opportunity."""
        ...


@runtime_checkable
class WeChatTemplateRepository(Protocol):
    async def get_wechat_template(
        self,
        template_id: str,
    ) -> WeChatTemplateRegistration | None: ...

    async def register_enabled(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration: ...

    async def disable_from_40037(
        self,
        template_id: str,
        *,
        now: datetime,
    ) -> WeChatTemplateRegistration: ...

    async def enable_by_administrator(
        self,
        template_id: str,
        *,
        administrator: str,
        now: datetime,
    ) -> WeChatTemplateRegistration: ...

@runtime_checkable
class UnitOfWork(Protocol):
    """Atomic persistence boundary for one application use-case."""

    creators: CreatorRepository
    follows: FollowRepository
    live: LiveRepository
    notifications: NotificationRepository
    grants: GrantRepository
    templates: WeChatTemplateRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
