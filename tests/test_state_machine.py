"""状态机单元测试:OFFLINE → SUSPECT_ONLINE → ONLINE → SUSPECT_OFFLINE → OFFLINE。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import transition  # noqa: E402


def test_offline_to_online_full_cycle():
    # OFFLINE + probe ONLINE → SUSPECT_ONLINE
    r1 = transition("OFFLINE", "ONLINE")
    assert r1["state"] == "SUSPECT_ONLINE"
    assert r1["event"] == "SUSPECT_ONLINE"

    # SUSPECT_ONLINE + probe ONLINE → ONLINE(触发开播)
    r2 = transition(r1["state"], "ONLINE")
    assert r2["state"] == "ONLINE"
    assert r2["event"] == "CONFIRMED_ONLINE"

    # ONLINE + probe OFFLINE → SUSPECT_OFFLINE
    r3 = transition(r2["state"], "OFFLINE")
    assert r3["state"] == "SUSPECT_OFFLINE"
    assert r3["event"] == "SUSPECT_OFFLINE"

    # SUSPECT_OFFLINE + probe OFFLINE → OFFLINE(触发下播)
    r4 = transition(r3["state"], "OFFLINE")
    assert r4["state"] == "OFFLINE"
    assert r4["event"] == "CONFIRMED_OFFLINE"


def test_jitter_handling():
    # SUSPECT_ONLINE 后探测 OFFLINE → 回 OFFLINE,不触发开播
    r1 = transition("OFFLINE", "ONLINE")
    r2 = transition(r1["state"], "OFFLINE")
    assert r2["state"] == "OFFLINE"
    assert r2["event"] is None

    # SUSPECT_OFFLINE 后探测 ONLINE → 回 ONLINE,不触发下播
    r3 = transition("ONLINE", "OFFLINE")
    r4 = transition(r3["state"], "ONLINE")
    assert r4["state"] == "ONLINE"
    assert r4["event"] is None


def test_non_live_status_no_transition():
    # 限流/被墙/解析错误 不改变状态
    for bad in ("RATE_LIMITED", "BLOCKED", "NOT_FOUND", "PARSE_ERROR", "UNKNOWN"):
        r = transition("ONLINE", bad)
        assert r["state"] == "ONLINE"
        assert r["event"] is None


if __name__ == "__main__":
    test_offline_to_online_full_cycle()
    test_jitter_handling()
    test_non_live_status_no_transition()
    print("✓ 状态机测试全部通过")
