"""WeChat notification-template configuration truth for Gate 3.2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class WeChatTemplateState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class WeChatTemplateStateSource(str, Enum):
    REGISTRATION = "REGISTRATION"
    PROVIDER_40037 = "PROVIDER_40037"
    ADMINISTRATOR = "ADMINISTRATOR"


@dataclass(frozen=True)
class WeChatTemplateRegistration:
    template_id: str
    state: WeChatTemplateState
    state_source: WeChatTemplateStateSource
    updated_by: str
    updated_at: datetime
    disabled_reason: str | None = None
    disabled_at: datetime | None = None

    def __post_init__(self) -> None:
        _required(self.template_id, "template_id")
        _required(self.updated_by, "updated_by")
        if self.state is WeChatTemplateState.DISABLED:
            if self.disabled_reason is None:
                raise ValueError("disabled template requires disabled_reason")
            _required(self.disabled_reason, "disabled_reason")
            if self.disabled_at is None:
                raise ValueError("disabled template requires disabled_at")
        elif self.disabled_reason is not None or self.disabled_at is not None:
            raise ValueError("enabled template cannot retain disabled metadata")

    @property
    def enabled(self) -> bool:
        return self.state is WeChatTemplateState.ENABLED
