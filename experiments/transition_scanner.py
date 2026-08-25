"""全站转换扫描器(替代盯梢): 批量列表对比找真实转换。

原理: 每 N 分钟拉虎牙前 K 页列表(在播集合),对比上一次快照,
      "消失"的房间 = ONLINE→OFFLINE 候选(用 adapter 二次验证排除排序波动)。
      "新出现"的房间 = OFFLINE→ONLINE 候选(验证后即为真实开播)。

用法:
    python transition_scanner.py [interval_minutes] [max_rounds]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from platform_adapters.huya.adapter import HuyaAdapter

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"
HEADERS = {"User-Agent": UA, "Referer": "https://www.huya.com/"}
OUT = Path("experiments/data")
PAGES = 5  # 拉前 5 页(600 房间)


def fetch_live() -> dict:
    """拉当前在播房间集合 {room_id: nick}。"""
    live = {}
    for page in range(1, PAGES + 1):
        r = httpx.get(
            f"https://www.huya.com/cache.php?m=LiveList&do=getLiveListByPage&tagAll=0&page={page}",
            headers=HEADERS, timeout=15,
        )
        for room in r.json().get("data", {}).get("datas", []):
            rid = str(room.get("profileRoom") or room.get("roomid"))
            live[rid] = room.get("nick", "?")
    return live


def verify(rid: str) -> str:
    """adapter 验证房间当前状态,排除列表排序波动。"""
    try:
        return HuyaAdapter().get_status(f"https://www.huya.com/{rid}").get("state", "UNKNOWN")
    except Exception:
        return "ERROR"


def main() -> int:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    max_rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 12

    log_path = OUT / "transition_scanner_log.jsonl"
    log = open(log_path, "a", encoding="utf-8")
    print(f"全站转换扫描器启动: {PAGES} 页/{interval}min 间隔, 最长 {max_rounds} 轮")

    prev = None
    transitions = []

    for round_no in range(1, max_rounds + 1):
        now = fetch_live()
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "round": round_no,
            "live_count": len(now),
        }

        if prev is not None:
            # 消失 = ONLINE→OFFLINE 候选
            gone = {r: n for r, n in prev.items() if r not in now}
            # 新增 = OFFLINE→ONLINE 候选
            new = {r: n for r, n in now.items() if r not in prev}

            # 验证候选(排除列表排序波动)
            verified_gone = {}
            for rid, nick in gone.items():
                state = verify(rid)
                if state == "OFFLINE":
                    verified_gone[rid] = nick
                time.sleep(0.3)
            verified_new = {}
            for rid, nick in new.items():
                state = verify(rid)
                if state == "ONLINE":
                    verified_new[rid] = nick
                time.sleep(0.3)

            entry["gone_candidates"] = len(gone)
            entry["verified_offline"] = verified_gone
            entry["new_candidates"] = len(new)
            entry["verified_online"] = verified_new

            if verified_gone:
                transitions.append({"round": round_no, "type": "ONLINE→OFFLINE", "rooms": verified_gone})
                print(f"\n  ★★★ 第 {round_no} 轮: 捕获 {len(verified_gone)} 个真实下播! ★★★")
                for rid, nick in verified_gone.items():
                    print(f"      {rid}: {nick}")
            if verified_new:
                transitions.append({"round": round_no, "type": "OFFLINE→ONLINE", "rooms": verified_new})
                print(f"\n  ★ 第 {round_no} 轮: 捕获 {len(verified_new)} 个真实开播! ★")
                for rid, nick in verified_new.items():
                    print(f"      {rid}: {nick}")

            print(f"[{entry['ts']}] 轮 {round_no}: 在播 {len(now)} | 消失候选 {len(gone)} → 真下播 {len(verified_gone)} | 新增候选 {len(new)} → 真开播 {len(verified_new)}")

        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.flush()
        prev = now

        # 目标: 捕获 ONLINE→OFFLINE(下播)。只捕获开播(OF模式LINE→ONLINE)不退出,继续跑
        has_offline_transition = any(t["type"] == "ONLINE→OFFLINE" for t in transitions)
        if has_offline_transition:
            break
        if round_no < max_rounds:
            print(f"  等待 {interval}min 后下一轮...")
            time.sleep(interval * 60)

    log.close()
    result = {"transitions": transitions, "log": str(log_path)}
    (OUT / "transition_scanner_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if transitions:
        print(f"\n✓ 捕获 {len(transitions)} 组转换!结果: transition_scanner_result.json")
    else:
        print(f"\n⏳ {max_rounds} 轮内未捕获转换(可能都是长播主播),可加长时间/换时段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
