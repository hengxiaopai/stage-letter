"""Transactional PostgreSQL acceptance probe for UI-V2.2 D1."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routers.anchors import get_anchor
from api.routers.subscriptions import ReminderPreferencePatch, patch_reminder_preference
from core.db import engine


async def main() -> None:
    token = uuid4().hex
    openid = f"gate-d1-{token}"

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                user_id = await session.scalar(
                    text("INSERT INTO users (openid) VALUES (:openid) RETURNING id"),
                    {"openid": openid},
                )
                creator_id = await session.scalar(
                    text("INSERT INTO creators DEFAULT VALUES RETURNING id")
                )
                anchor_id = await session.scalar(
                    text(
                        "INSERT INTO anchors (display_name) "
                        "VALUES ('D1 Probe') RETURNING id"
                    )
                )
                account_id = await session.scalar(
                    text(
                        """
                        INSERT INTO platform_accounts (
                            anchor_id, creator_id, platform, platform_user_id,
                            canonical_url, last_status, is_disabled, polling_tier
                        ) VALUES (
                            :anchor_id, :creator_id, 'douyin', :platform_user_id,
                            'https://example.invalid/d1', 'OFFLINE', false, 'warm'
                        ) RETURNING id
                        """
                    ),
                    {
                        "anchor_id": anchor_id,
                        "creator_id": creator_id,
                        "platform_user_id": f"d1-{token}",
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO follows (
                            user_id, creator_id, platform_account_id, starred
                        ) VALUES (:user_id, :creator_id, :account_id, false)
                        """
                    ),
                    {
                        "user_id": user_id,
                        "creator_id": creator_id,
                        "account_id": account_id,
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO notification_preferences (
                            user_id, platform_account_id, enabled
                        ) VALUES (:user_id, :account_id, true)
                        """
                    ),
                    {"user_id": user_id, "account_id": account_id},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO user_subscriptions (
                            user_id, anchor_id, platform_account_id,
                            notify_enabled, is_starred
                        ) VALUES (
                            :user_id, :anchor_id, :account_id, true, false
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "anchor_id": anchor_id,
                        "account_id": account_id,
                    },
                )
                await session.flush()

                detail = await get_anchor(anchor_id, openid=openid, db=session)
                platform = detail.platforms[0]
                assert platform.is_following is True
                assert platform.reminder_enabled is True

                response = await patch_reminder_preference(
                    account_id,
                    ReminderPreferencePatch(openid=openid, enabled=False),
                    session,
                )
                assert response.enabled is False

                formal_enabled = await session.scalar(
                    text(
                        """
                        SELECT enabled FROM notification_preferences
                        WHERE user_id = :user_id
                          AND platform_account_id = :account_id
                        """
                    ),
                    {"user_id": user_id, "account_id": account_id},
                )
                legacy_enabled = await session.scalar(
                    text(
                        """
                        SELECT notify_enabled FROM user_subscriptions
                        WHERE user_id = :user_id
                          AND platform_account_id = :account_id
                        """
                    ),
                    {"user_id": user_id, "account_id": account_id},
                )
                assert formal_enabled is False
                assert legacy_enabled is False
        finally:
            await transaction.rollback()

    await engine.dispose()
    print("UI-V2.2 D1 PostgreSQL probe: PASS")


if __name__ == "__main__":
    asyncio.run(main())
