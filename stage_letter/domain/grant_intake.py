"""Client-reported WeChat grant intake evidence.

The WeChat client callback is useful evidence, but it is not provider balance
truth. Provider send outcomes remain authoritative for consumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class GrantIntakeDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    BAN = "ban"


@dataclass(frozen=True)
class WeChatGrantIntake:
    user_id: str
    request_id: str
    template_id: str
    decision: GrantIntakeDecision
    received_at: datetime

    def __post_init__(self) -> None:
        for value, field in (
            (self.user_id, "user_id"),
            (self.request_id, "request_id"),
            (self.template_id, "template_id"),
        ):
            if not value.strip():
                raise ValueError(f"{field} is required")
        if len(self.request_id) > 64:
            raise ValueError("request_id must not exceed 64 characters")
        if len(self.template_id) > 64:
            raise ValueError("template_id must not exceed 64 characters")
        if self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
