"""高频盯梢: 盯住 4 个 LOL 电竞主播,捕获 ONLINE→OFFLINE 转换(Gate 0B 关键证据)。

背景: 24h soak(600s 间隔)和 transition scanner(20min 间隔)都太慢,
      电竞主播下播可能只有 30-60 分钟窗口,间隔大会错过转换。
      本脚本 30s 探测一次,任一转 ONLINE→OFFLINE 即记录并退出。

用法:
  python watch_esports.py [duration_minutes] [interval_seconds]
  默认盯 180 分钟,30s 间隔。
"""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from platform_adapters.huya.adapter import HuyaAdapter

ROOMS = {
    "333003": "Zz1tai姿态",
    "222523": "kRYST4L水晶哥",
    "980312": "Ning宁王",
    "149361": "解说米勒",
}
OUT = Path("experiments/data")
LOG = OUT / "watch_esports_log.jsonl"
_adapter = None


def _a():
    global _adapter
    if _adapter is None:
        _adapter = HuyaAdapter()
    return _adapter


def main() -> int:
    duration_min = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    end_at = time.time() + duration_min * 60
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(LOG, "a", encoding="utf-8")

    states = {r: None for r in ROOMS}
    first_round = True
    transitions = []

    print(f"⚡ 盯梢 {duration_min}min × {interval}s: {', '.join(ROOMS.values())}")
    while time.time() < end_at:
        for rid, nick in ROOMS.items():
            try:
                st = _a().get_status(f"https://www.huya.com/{rid}").get("state", "UNKNOWN")
            except Exception as e:
                st = "EXCEPTION"
            prev = states[rid]
            states[rid] = st
            entry = {
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "room": rid,
                "nick": nick,
                "state": st,
                "prev": prev,
            }
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
            print(f"[{entry['ts']}] {nick}: {st}" + (f"  ← 之前 {prev}" if prev and prev != st and not first_round else ""))

            # 捕获转换(跳过第一轮,因为 prev 是 None)
            if not first_round and prev and prev != st:
                if prev == "ONLINE" and st == "OFFLINE":
                    print(f"\n  ★★★ 捕获 ONLINE→OFFLINE: {nick} ({rid}) ★★★")
                    transitions.append({"room": rid, "nick": nick, "ts": entry["ts"]})
                    log.close()
                    (OUT / "watch_esports_result.json").write_text(
                        json.dumps({"transitions": transitions}, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    return 0
                if prev == "OFFLINE" and st == "ONLINE":
                    print(f"\n  ★ 捕获 OFFLINE→ONLINE: {nick} ({rid}) ★")
                    transitions.append({"room": rid, "nick": nick, "ts": entry["ts"]})
        first_round = False
        time.sleep(interval)

    log.close()
    (OUT / "watch_esports_result.json").write_text(
        json.dumps({"transitions": transitions, "final_states": states}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n⏳ {duration_min}min 内未捕获 ONLINE→OFFLINE(主播未下播)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
