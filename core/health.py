"""系统健康检查(P0-LiveTruth-02: Worker 存活纳入验收)。

- worker 每轮写 worker_heartbeat.json(文件方式, 跨进程简单可靠)
- health API 读取并判断: 超过 HEARTBEAT_STALE_S 未心跳 → UNHEALTHY

文件位置: .workbuddy/health.json
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HEALTH_FILE = PROJECT_ROOT / ".workbuddy" / "health.json"

# worker 超过该秒数未心跳 → UNHEALTHY(worker 每 30s 循环, 180s 宽松)
HEARTBEAT_STALE_S = 180


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def worker_heartbeat(accounts_probed: int = 0, errors: int = 0) -> None:
    """worker 每轮调用: 记录心跳。"""
    data = _read()
    data["worker_tick_at"] = _now_iso()
    data["worker_accounts_probed"] = accounts_probed
    data["worker_errors"] = errors
    _write(data)


def api_heartbeat() -> None:
    """API 启动/请求时调用(可选)。"""
    data = _read()
    data["api_tick_at"] = _now_iso()
    _write(data)


def _read() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(data: dict) -> None:
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_health() -> dict:
    """返回系统健康状态。"""
    data = _read()
    now = time.time()
    out = {
        "api": "HEALTHY",
        "worker": {"healthy": False, "last_tick_at": None, "age_s": None},
    }

    # Worker
    tick = data.get("worker_tick_at")
    if tick:
        try:
            t = datetime.fromisoformat(tick)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - t).total_seconds()
            out["worker"]["last_tick_at"] = tick
            out["worker"]["age_s"] = round(age, 1)
            out["worker"]["healthy"] = age <= HEARTBEAT_STALE_S
            out["worker"]["accounts_probed"] = data.get("worker_accounts_probed")
            out["worker"]["errors"] = data.get("worker_errors")
        except Exception:
            pass

    # API
    api_tick = data.get("api_tick_at")
    if api_tick:
        try:
            t = datetime.fromisoformat(api_tick)
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - t).total_seconds()
            out["api"] = "HEALTHY" if age <= HEARTBEAT_STALE_S * 2 else "STALE"
        except Exception:
            pass

    return out
