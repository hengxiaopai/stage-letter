"""C1 持续 QPS 阶梯压测。

测每平台单 IP 匿名可持续的最高 QPS(sustained_qps):
  基线 0.02 req/s → 0.5 → 1 → 2 → 5 req/s,每阶梯固定时长,
  触发限流信号(慢响应>60s / 连接拒连)即停,记录触发前可持续时间。

用法:
  python c1_qps_ladder.py --platform bilibili [--duration 1800] [--dry-run]

输出:
  experiments/data/c1_{platform}.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platform_adapters"))
sys.path.insert(0, str(ROOT / "experiments"))

from throughput_test.c6_ratelimit_causality import (  # noqa: E402
    ANCHOR_FILES,
    build_adapter,
    probe,
)

# 阶梯: (label, qps, 单次间隔秒, 持续秒)
LADDER = [
    ("baseline", 0.02, 300, 1800),   # 基线:与 Gate 0B soak 相同频率
    ("step1", 0.5, 2, 1800),         # 0.5 req/s
    ("step2", 1.0, 1, 1800),         # 1 req/s
    ("step3", 2.0, 0.5, 1800),       # 2 req/s
    ("step4", 5.0, 0.2, 1800),       # 5 req/s
]

SLOW_MS = 60_000
VERY_SLOW_MS = 300_000
CONSECUTIVE_THRESHOLD = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--platform", required=True, choices=list(ANCHOR_FILES))
    ap.add_argument("--duration", type=int, default=1800, help="每阶梯持续秒(默认 1800 = 30min)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    adapter = build_adapter(args.platform)
    anchors = []
    for line in ANCHOR_FILES[args.platform].read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            anchors.append(line)

    print(f"[C1] platform={args.platform} adapter={type(adapter).__name__} anchors={len(anchors)}")
    if args.dry_run:
        r = probe(adapter, anchors[0])
        print(f"[C1] dry-run probe: {r['state']} {r['latency_ms']}ms")
        return 0

    result = {
        "platform": args.platform,
        "started_at": now_iso(),
        "duration_s": args.duration,
        "steps": [],
    }

    for label, qps, interval, duration in LADDER:
        print(f"\n===== {label}: {qps} req/s (interval={interval}s, max {duration}s) =====")
        step = {
            "label": label,
            "qps": qps,
            "interval_s": interval,
            "started_at": now_iso(),
            "requests": 0,
            "ok": 0,
            "bad": 0,
            "slow_entries": [],
            "triggered_at": None,
            "triggered_reason": None,
        }
        start = time.monotonic()
        consec_bad = 0
        stop = False

        while time.monotonic() - start < duration:
            for anchor in anchors:
                r = probe(adapter, anchor)
                step["requests"] += 1
                lat = r["latency_ms"]
                is_bad = (not r["ok"]) or lat > VERY_SLOW_MS
                is_slow = lat > SLOW_MS

                if r["ok"]:
                    step["ok"] += 1
                else:
                    step["bad"] += 1

                if is_slow:
                    step["slow_entries"].append({
                        "ts": now_iso(), "anchor": anchor,
                        "state": r["state"], "latency_ms": lat,
                        "error": r["detail"].get("error", "") if not r["ok"] else None,
                    })
                    if len(step["slow_entries"]) <= 3:
                        print(f"  ⚠️ 慢响应 {lat}ms @ {anchor}")

                if is_bad:
                    consec_bad += 1
                else:
                    consec_bad = 0

                if consec_bad >= CONSECUTIVE_THRESHOLD or len(step["slow_entries"]) >= 5:
                    step["triggered_at"] = now_iso()
                    step["triggered_reason"] = "connection_error" if consec_bad >= CONSECUTIVE_THRESHOLD else "slow"
                    print(f"  ★ 触发限流: {step['triggered_reason']} @ 第 {step['requests']} 请求")
                    stop = True
                    break

                time.sleep(interval)
            if stop:
                break

        step["duration_actual_s"] = round(time.monotonic() - start, 1)
        step["sustained_qps_actual"] = round(step["requests"] / max(step["duration_actual_s"], 1), 4)
        result["steps"].append(step)
        print(f"  → 汇总: {step['requests']} 请求, ok={step['ok']}, bad={step['bad']}, "
              f"持续 {step['duration_actual_s']}s, 实际 {step['sustained_qps_actual']} req/s")

        if step["triggered_at"]:
            # 触发后停止整个实验(该平台已到上限)
            result["sustained_qps"] = result["steps"][-2]["sustained_qps_actual"] if len(result["steps"]) > 1 else 0.02
            print(f"\n[√] {args.platform} sustained_qps ≈ {result['sustained_qps']} req/s (触发于 {label})")
            break
    else:
        # 全阶梯跑完没触发
        result["sustained_qps"] = LADDER[-1][1]
        print(f"\n[√] {args.platform} 全阶梯无触发,sustained_qps ≥ {LADDER[-1][1]} req/s")

    result["finished_at"] = now_iso()
    out = ROOT / "experiments" / "data" / f"c1_{args.platform}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
