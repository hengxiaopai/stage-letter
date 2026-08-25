"""LiveSession 领域服务(Gate 1 Domain Core)。

职责:
1. 状态机驱动: probe 结果 → 状态转换 → LiveEvent 落库
2. 开播去重: 同一 platform_account 同一时刻只有 1 个 OPEN session
   (数据库 partial unique index 兜底 + 应用层先查)
3. 事件去重: CONFIRMED_ONLINE 只在 OFFLINE/SUSPECT_OFFLINE → ONLINE 转换时产生
4. Fan-out 去重: 同一 (live_event_id, user_id) 只产生 1 个 notification_job
   (数据库 UNIQUE 兜底 + 应用层先查)

用法:
    engine = LiveSessionEngine(session)
    await engine.on_probe(platform_account_id, probe_status, probe_meta)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import (
    LiveEvent,
    LiveSession,
    LiveStatus,
    NotificationJob,
    PlatformAccount,
    UserSubscription,
)
from core.state_machine import transition

logger = logging.getLogger(__name__)

# 事件类型(与 models.EventType 一致)
EVT_SUSPECT_ONLINE = "SUSPECT_ONLINE"
EVT_CONFIRMED_ONLINE = "CONFIRMED_ONLINE"
EVT_SUSPECT_OFFLINE = "SUSPECT_OFFLINE"
EVT_CONFIRMED_OFFLINE = "CONFIRMED_OFFLINE"


class LiveSessionEngine:
    """开播检测核心引擎: 探测 → 状态转换 → 事件/会话/任务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def on_probe(
        self,
        platform_account_id: int,
        probe_status: str,
        probe_meta: dict | None = None,
        now: datetime | None = None,
    ) -> dict:
        """处理一次探测结果。

        Args:
            platform_account_id: platform_accounts.id
            probe_status: adapter 返回的 7 态(ONLINE/OFFLINE/...)
            probe_meta: 附加信息(标题/封面/观看数等)
            now: 当前时间(测试可注入)

        Returns:
            {"event": event_type_or_None, "session_id": int_or_None,
             "job_count": int, "status_changed": bool}
        """
        now = now or datetime.now(timezone.utc)
        pa = await self.db.get(PlatformAccount, platform_account_id)
        if pa is None:
            raise ValueError(f"platform_account {platform_account_id} 不存在")

        # 1. 状态机转换(非 ONLINE/OFFLINE 探测不触发转换)
        result = transition(pa.last_status, probe_status)
        new_state = result["state"]
        event_type = result["event"]

        status_changed = new_state != pa.last_status
        pa.last_status = new_state

        # P0-L3: 可信状态才刷新 last_checked_at(freshness 依据)
        # UNKNOWN/BLOCKED/RATE_LIMITED/PARSE_ERROR 是"探测失败", 不刷新 → 自然变 stale → CONFIRMING
        # NOT_FOUND 视为可信(直播间不存在 ≈ 下播)
        TRUSTED_PROBE = (
            LiveStatus.ONLINE.value,
            LiveStatus.OFFLINE.value,
            LiveStatus.NOT_FOUND.value,
        )
        if probe_status in TRUSTED_PROBE:
            pa.last_checked_at = now

        if probe_meta:
            # 透传可序列化字段
            pa.__dict__.setdefault("_probe_meta", probe_meta)

        session_id = None
        job_count = 0

        # 2026-08-14: 已在播(ONLINE)且本次仍探测 ONLINE → 尝试回填真实开播时间
        # (不触发事件, 但主播可能已开播很久, 旧 session 的 started_at 是探测时刻)
        if event_type is None and probe_status == LiveStatus.ONLINE.value and pa.last_status == LiveStatus.ONLINE.value:
            rollover_session_id = await self._refresh_open_session(pa, probe_meta, now)
            if rollover_session_id is not None:
                session_id = rollover_session_id
                event_type = EVT_CONFIRMED_ONLINE
                rollover_meta = dict(probe_meta or {})
                rollover_meta["session_boundary"] = "provider_room_changed"
                probe_meta = rollover_meta

        # 2. 根据事件类型创建/关闭 session + 产生事件
        if event_type == EVT_CONFIRMED_ONLINE:
            if session_id is None:
                session_id = await self._open_session(pa, probe_meta, now)
            event_id = await self._record_event(
                pa, event_type, session_id, probe_meta, now, confidence="normal"
            )
            # 3. Fan-out 通知任务(用真实 event_id)
            job_count = await self._fanout_jobs(pa, event_id, session_id, now)

        elif event_type == EVT_CONFIRMED_OFFLINE:
            session_id = await self._close_session(pa, now)
            await self._record_event(
                pa, event_type, session_id, probe_meta, now, confidence="normal"
            )

        elif event_type in (EVT_SUSPECT_ONLINE, EVT_SUSPECT_OFFLINE):
            # SUSPECT 事件也记录(供分析),但不创建/关闭 session
            await self._record_event(
                pa, event_type, None, probe_meta, now, confidence="normal"
            )

        await self.db.flush()
        return {
            "event": event_type,
            "session_id": session_id,
            "job_count": job_count,
            "status_changed": status_changed,
            "state": new_state,
        }

    # ── session 管理 ──

    @staticmethod
    def _viewer_count(meta: dict | None) -> int | None:
        value = (meta or {}).get("viewer_count")
        if isinstance(value, bool):
            return None
        multiplier = 1
        if isinstance(value, str):
            normalized = value.strip().replace(",", "")
            if normalized.endswith("万"):
                normalized = normalized[:-1]
                multiplier = 10_000
            elif normalized.endswith("亿"):
                normalized = normalized[:-1]
                multiplier = 100_000_000
            value = normalized
        try:
            parsed = int(float(value) * multiplier)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    async def _refresh_open_session(
        self, pa: PlatformAccount, meta: dict | None, now: datetime
    ) -> int | None:
        """Refresh normalized metadata or split a changed provider room.

        A room id is never live-state evidence. This method runs only after an
        ONLINE result has already been accepted by the state machine.
        """

        result = await self.db.execute(
            select(LiveSession)
            .where(
                LiveSession.platform_account_id == pa.id,
                LiveSession.state == "OPEN",
            )
            .order_by(LiveSession.started_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            return None

        observed_room = (meta or {}).get("room_id")
        observed_room = str(observed_room).strip() if observed_room else None
        if (
            session.provider_room_id is not None
            and observed_room is not None
            and session.provider_room_id != observed_room
        ):
            session.state = "CLOSED"
            session.ended_at = now
            await self.db.flush()
            logger.info(
                "pa=%s provider room changed %s -> %s; opening a new session",
                pa.id,
                session.provider_room_id,
                observed_room,
            )
            return await self._open_session(pa, meta, now)

        if session.provider_room_id is None and observed_room is not None:
            session.provider_room_id = observed_room
        for attribute, key in (("title", "title"), ("cover", "cover")):
            value = (meta or {}).get(key)
            if value:
                setattr(session, attribute, value)
        viewer_count = self._viewer_count(meta)
        if viewer_count is not None:
            session.viewer_count = viewer_count
        session.metadata_source = (meta or {}).get("source") or f"{pa.platform}.adapter"
        session.metadata_observed_at = now
        await self._backfill_started_at(pa, meta, now)
        return None

    async def _backfill_started_at(
        self, pa: PlatformAccount, meta: dict | None, now: datetime
    ) -> None:
        """回填真实开播时间: 已有 OPEN session 且平台返回更早的真实时间 → 修正 started_at。

        2026-08-14 新增: 旧 bug 用"探测时刻"当开播时间, 主播可能已开播很久。
        平台真实时间(unix 秒) < 当前 session.started_at 时回填。
        """
        try:
            ls_at = (meta or {}).get("live_started_at")
            if not (isinstance(ls_at, (int, float)) and ls_at > 1000000000):
                return
            real_started = datetime.fromtimestamp(ls_at, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return
        result = await self.db.execute(
            select(LiveSession)
            .where(
                LiveSession.platform_account_id == pa.id,
                LiveSession.state == "OPEN",
            )
            .order_by(LiveSession.started_at.desc())
            .limit(1)
        )
        sess = result.scalar_one_or_none()
        if sess is None:
            return
        if sess.started_at.tzinfo is None:
            sess.started_at = sess.started_at.replace(tzinfo=timezone.utc)
        if real_started < sess.started_at:
            logger.info(
                "pa=%s 回填真实开播时间 %s (旧=%s)",
                pa.id, real_started.isoformat(), sess.started_at.isoformat(),
            )
            sess.started_at = real_started
            sess.source_started_at = real_started
            sess.started_at_source = "platform"
            pa.last_live_started_at = real_started
            await self.db.flush()

    async def _open_session(
        self, pa: PlatformAccount, meta: dict | None, now: datetime
    ) -> int:
        """创建 OPEN session(应用层查重 + DB partial unique 兜底)。

        2026-08-14 修正: started_at 优先取平台真实开播时间(meta["live_started_at"], unix 秒),
        fallback 到探测时刻 now。旧代码一律用 now — 主播可能已开播很久,
        导致详情页显示"探测时刻"当作"开播时间"(用户反馈 12:38 开播其实是订阅时刻)。
        """
        # 应用层先查:同一 pa 已有 OPEN session 则不重复创建(回填交给 _backfill_started_at)
        existing = await self.db.execute(
            select(LiveSession.id)
            .where(
                LiveSession.platform_account_id == pa.id,
                LiveSession.state == "OPEN",
            )
        )
        dup_id = existing.scalar_one_or_none()
        if dup_id is not None:
            await self._backfill_started_at(pa, meta, now)
            logger.warning("pa=%s 已有 OPEN session,跳过重复创建", pa.id)
            return dup_id

        # 真实开播时间(平台返回 unix 秒) → UTC datetime; 非法/缺失 → 探测时刻
        started = now
        started_source = "probe"  # 2026-08-14: 标注来源 — probe=探测时刻兜底(非真实开播时间)
        try:
            ls_at = (meta or {}).get("live_started_at")
            if isinstance(ls_at, (int, float)) and ls_at > 1000000000:
                started = datetime.fromtimestamp(ls_at, tz=timezone.utc)
                started_source = "platform"
        except (ValueError, OSError, OverflowError):
            pass

        session = LiveSession(
            platform_account_id=pa.id,
            anchor_id=pa.anchor_id,
            platform=pa.platform,
            started_at=started,
            source_started_at=(started if started_source == "platform" else None),
            started_at_source=started_source,
            title=(meta or {}).get("title"),
            cover=(meta or {}).get("cover"),
            viewer_count=self._viewer_count(meta),
            provider_room_id=(
                str((meta or {}).get("room_id")).strip()
                if (meta or {}).get("room_id")
                else None
            ),
            metadata_source=(meta or {}).get("source") or f"{pa.platform}.adapter",
            metadata_observed_at=now,
            state="OPEN",
        )
        self.db.add(session)
        await self.db.flush()  # 拿 session.id;若撞 partial unique 会抛 IntegrityError
        pa.last_live_started_at = started
        return session.id  # type: ignore[return-value]

    async def _close_session(self, pa: PlatformAccount, now: datetime) -> int | None:
        """关闭当前 OPEN session。"""
        result = await self.db.execute(
            select(LiveSession)
            .where(
                LiveSession.platform_account_id == pa.id,
                LiveSession.state == "OPEN",
            )
            .order_by(LiveSession.started_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session is None:
            logger.warning("pa=%s CONFIRMED_OFFLINE 但无 OPEN session", pa.id)
            return None
        session.state = "CLOSED"
        session.ended_at = now
        return session.id  # type: ignore[return-value]

    # ── 事件落库(append-only)──

    async def _record_event(
        self,
        pa: PlatformAccount,
        event_type: str,
        session_id: int | None,
        meta: dict | None,
        now: datetime,
        confidence: str,
    ) -> int:
        event = LiveEvent(
            platform_account_id=pa.id,
            anchor_id=pa.anchor_id,
            live_session_id=session_id,
            event_type=event_type,
            confidence=confidence,
            occurred_at=now,
            detected_at=now,
            payload=meta,
        )
        self.db.add(event)
        await self.db.flush()  # 拿 event.id 供 fan-out 使用
        return event.id  # type: ignore[return-value]

    # ── fan-out 去重 ──

    async def _fanout_jobs(
        self,
        pa: PlatformAccount,
        live_event_id: int,
        session_id: int,
        now: datetime,
    ) -> int:
        """开播 → 给所有订阅用户创建 notification_job(去重)。"""
        subs = await self.db.execute(
            select(UserSubscription).where(
                UserSubscription.platform_account_id == pa.id,
                UserSubscription.notify_enabled.is_(True),
            )
        )
        count = 0
        for sub in subs.scalars().all():
            # 应用层先查:同一 (live_event_id, user_id) 已有 job 则跳过
            dup = await self.db.execute(
                select(NotificationJob.id).where(
                    NotificationJob.live_event_id == live_event_id,
                    NotificationJob.user_id == sub.user_id,
                )
            )
            if dup.scalar_one_or_none() is not None:
                continue
            job = NotificationJob(
                live_event_id=live_event_id,
                live_session_id=session_id,
                user_id=sub.user_id,
                anchor_id=pa.anchor_id,
                state="PENDING",
                created_at=now,
            )
            self.db.add(job)
            count += 1
        return count
