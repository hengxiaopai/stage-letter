from __future__ import annotations

import unittest

from stage_letter.application.notification_providers import GrantEffect, ProviderOutcomeKind
from stage_letter.infrastructure.notifications.wechat import (
    ERR_INVALID_OPENID,
    WeChatRawResponse,
    normalize_wechat_response,
)


class Gate16WeChatInvalidOpenIdEvidenceTests(unittest.TestCase):
    def test_40003_is_explicit_auth_repair_and_preserves_grant(self) -> None:
        outcome = normalize_wechat_response(
            WeChatRawResponse(
                200,
                {"errcode": ERR_INVALID_OPENID, "errmsg": "invalid openid"},
            )
        )

        self.assertEqual(ProviderOutcomeKind.AUTH_REQUIRED, outcome.kind)
        self.assertEqual(GrantEffect.PRESERVE, outcome.grant_effect)
        self.assertEqual("40003", outcome.provider_code)
        self.assertFalse(outcome.provider_accepted)
        self.assertFalse(outcome.allows_automatic_retry)


if __name__ == "__main__":
    unittest.main()
