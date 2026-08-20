"""Infrastructure-free notification provider contracts for Gate 1.6-4."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class ProviderOutcomeKind(str, Enum):
    """Normalized external-attempt outcome understood by the application layer."""

    ACCEPTED = "ACCEPTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CONFIG_BLOCKED = "CONFIG_BLOCKED"
    RETRYABLE = "RETRYABLE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"


class GrantEffect(str, Enum):
    """Evidence-backed local-ledger effect carried by a provider outcome.

    Gate 1.6-4 only normalizes this effect. Durable grant mutation remains part
    of the real delivery acceptance/wiring slice in Gate 1.6-5.
    """

    CONSUME = "CONSUME"
    PRESERVE = "PRESERVE"


@dataclass(frozen=True)
class WeChatLiveStartMessage:
    """Semantic live-start message before WeChat template-field translation."""

    openid: str
    template_id: str
    anchor_name: str
    room_title: str
    start_time: str
    theme: str = "开播啦"
    activity: str = "无"
    page: str | None = None
    miniprogram_state: str = "formal"

    def __post_init__(self) -> None:
        _required(self.openid, "openid")
        _required(self.template_id, "template_id")
        _required(self.anchor_name, "anchor_name")
        _required(self.room_title, "room_title")
        _required(self.start_time, "start_time")
        if self.miniprogram_state not in {"formal", "trial", "developer"}:
            raise ValueError("miniprogram_state must be formal, trial, or developer")
        if self.page is not None and not self.page.strip():
            raise ValueError("page must not be blank")


@dataclass(frozen=True)
class ProviderOutcome:
    """Normalized WeChat result with no token/secret/raw-response leakage."""

    kind: ProviderOutcomeKind
    grant_effect: GrantEffect
    provider_code: str | None = None
    provider_message: str | None = None

    @property
    def provider_accepted(self) -> bool:
        return self.kind is ProviderOutcomeKind.ACCEPTED

    @property
    def allows_automatic_retry(self) -> bool:
        return self.kind is ProviderOutcomeKind.RETRYABLE


@runtime_checkable
class WeChatNotificationProvider(Protocol):
    """Async provider boundary; concrete transport belongs to infrastructure."""

    async def send(self, message: WeChatLiveStartMessage) -> ProviderOutcome: ...
