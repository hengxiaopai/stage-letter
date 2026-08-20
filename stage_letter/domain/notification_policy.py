"""Pure notification eligibility policy for Gate 1.6 and Gate 3.1.

This module carries the accepted Gate 0D notification truth into formal runtime
without importing experiments/* or provider code. It decides only whether one
canonical LiveEvent and one already-resolved user target are eligible to enter
a notification channel, then builds the logical pending delivery value. Durable
idempotency remains the NotificationRepository boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .live import LiveEvent, LiveEventCause, LiveEventType
from .notifications import (
    DeliveryChannel,
    DeliveryKey,
    GrantState,
    NotificationDelivery,
)


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required")


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    WRONG_EVENT_TYPE = "WRONG_EVENT_TYPE"
    BOOTSTRAP_LIVE = "BOOTSTRAP_LIVE"
    NOT_FOLLOWING = "NOT_FOLLOWING"
    NOTIFICATION_DISABLED = "NOTIFICATION_DISABLED"
    GRANT_NOT_GRANTED = "GRANT_NOT_GRANTED"


@dataclass(frozen=True)
class NotificationTarget:
    """Resolved notification truth for one user/account/channel decision.

    ``grant_state`` is channel/provider truth supplied to the policy. This type
    does not imply that grant state belongs on Creator, PlatformAccount, Follow,
    or NotificationPreference, and it does not define how grant truth is stored.
    """

    user_id: str
    account_id: str
    following: bool
    notification_enabled: bool
    grant_state: GrantState

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.account_id, "account_id")


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: EligibilityReason
    user_id: str
    live_event_id: str
    channel: DeliveryChannel

    def __post_init__(self) -> None:
        _required(self.user_id, "user_id")
        _required(self.live_event_id, "live_event_id")
        if self.eligible != (self.reason is EligibilityReason.ELIGIBLE):
            raise ValueError("eligible decision must use ELIGIBLE reason exclusively")


def evaluate_notification_eligibility(
    event: LiveEvent,
    target: NotificationTarget,
    *,
    channel: DeliveryChannel = DeliveryChannel.WECHAT_SUBSCRIBE,
) -> EligibilityDecision:
    """Apply the accepted Gate 0D eligibility matrix.

    Eligibility requires all of:
      * LIVE_STARTED
      * TRANSITION cause
      * active Follow truth
      * enabled notification preference
      * GRANTED channel/provider grant truth for WECHAT_SUBSCRIBE only

    IN_APP is an internal delivery channel and therefore never requires a
    WeChat grant. It still requires the same canonical event, Follow, and
    notification-preference truth.
    """

    if target.account_id != event.account_id:
        raise ValueError("target account_id does not match live event account_id")

    if event.event_type is not LiveEventType.LIVE_STARTED:
        reason = EligibilityReason.WRONG_EVENT_TYPE
    elif event.cause is LiveEventCause.BOOTSTRAP_LIVE:
        reason = EligibilityReason.BOOTSTRAP_LIVE
    elif not target.following:
        reason = EligibilityReason.NOT_FOLLOWING
    elif not target.notification_enabled:
        reason = EligibilityReason.NOTIFICATION_DISABLED
    elif (
        channel is DeliveryChannel.WECHAT_SUBSCRIBE
        and target.grant_state is not GrantState.GRANTED
    ):
        reason = EligibilityReason.GRANT_NOT_GRANTED
    else:
        reason = EligibilityReason.ELIGIBLE

    return EligibilityDecision(
        eligible=reason is EligibilityReason.ELIGIBLE,
        reason=reason,
        user_id=target.user_id,
        live_event_id=event.event_id,
        channel=channel,
    )


def build_pending_delivery(
    decision: EligibilityDecision,
    event: LiveEvent,
    target: NotificationTarget,
) -> NotificationDelivery | None:
    """Build the logical PENDING delivery value iff the decision is eligible.

    The logical idempotency key is exactly ``(user_id, live_event_id, channel)``.
    This function does not persist or send anything; repository uniqueness owns
    durable duplicate suppression and later Gate 1.6 slices own provider work.
    """

    if decision.user_id != target.user_id:
        raise ValueError("eligibility decision user_id does not match target")
    if decision.live_event_id != event.event_id:
        raise ValueError("eligibility decision live_event_id does not match event")
    if target.account_id != event.account_id:
        raise ValueError("target account_id does not match live event account_id")

    if not decision.eligible:
        return None

    # EligibilityDecision enforces ELIGIBLE reason when eligible=True.
    return NotificationDelivery(
        key=DeliveryKey(
            user_id=target.user_id,
            live_event_id=event.event_id,
            channel=decision.channel,
        ),
        account_id=event.account_id,
        session_id=event.session_id,
        created_at=event.occurred_at,
    )
