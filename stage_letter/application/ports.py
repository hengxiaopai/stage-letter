"""Infrastructure-free repository and transaction ports for Gate 1.

These protocols define what the application layer may ask persistence to do.
They deliberately avoid SQLAlchemy, Redis, FastAPI, Dramatiq, provider SDKs,
and imports from experiments/*.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol, runtime_checkable

from stage_letter.domain.creators import Creator, CreatorProfile, PlatformAccount
from stage_letter.domain.follows import Follow, NotificationPreference
from stage_letter.domain.live import LiveEvent, LiveObservation, LiveSession
from stage_letter.domain.notifications import DeliveryKey, NotificationDelivery


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
        """Return one durable logical observation regardless of provider source.

        Gate 1.4 uses this lookup to reuse an already-persisted logical probe when
        the scheduler retries the same probe_id.
        """
        ...

    async def append_observation(self, observation: LiveObservation) -> bool:
        """Insert the observation if permitted by durable identity constraints.

        Return True when this transaction inserted the row and False when a
        concurrent/idempotent write already owns the same durable identity.
        """
        ...

    async def list_monitor_observations(
        self,
        account_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> tuple[ObservationReplayRecord, ...]:
        """Return formal ``monitor:*`` observations in durable persistence order.

        The opaque sequence exists only for restart replay/paging. Legacy and
        manually inserted non-monitor observations are deliberately excluded from
        Gate 1.5 canonical state reconstruction because their participation in the
        formal scheduler pipeline is not provable.
        """
        ...

    async def get_latest_observation(self, account_id: str) -> LiveObservation | None: ...

    async def get_open_session(self, account_id: str) -> LiveSession | None: ...

    async def save_session(self, session: LiveSession) -> None: ...

    async def append_event(self, event: LiveEvent) -> None: ...

    async def get_event(self, event_id: str) -> LiveEvent | None: ...


@runtime_checkable
class NotificationRepository(Protocol):
    async def get_delivery(self, key: DeliveryKey) -> NotificationDelivery | None: ...

    async def create_delivery(self, delivery: NotificationDelivery) -> bool:
        """Create iff absent; return False when the logical delivery already exists."""
        ...

    async def save_delivery(self, delivery: NotificationDelivery) -> None: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Atomic persistence boundary for one application use-case.

    Gate 0B established that observation/state/session/event mutation must survive
    restart atomically. Implementations must therefore commit those writes as one
    transaction where the use-case requires it.
    """

    creators: CreatorRepository
    follows: FollowRepository
    live: LiveRepository
    notifications: NotificationRepository

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
