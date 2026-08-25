"""C6 因果实验:连接超时 vs RATE_LIMITED 判定规则。

回答 GATE-0.md Gate 0C C6 的三个问题:
  1. 连接超时连续 N 次(如 3 次)后,是否应升级为 RATE_LIMITED?
  2. 慢响应(延迟 > 60s)是否也算限流信号?
  3. 各平台恢复时间是否随累犯延长?自动退避参数(停 2h / 4h / 8h / 24h)怎么定?

方法:单 IP 匿名,固定低频轮询,记录:
  - T0 开始
  - 每次探测的:状态 / 延迟 / 异常类型
  - 首犯时间 / 触发前累计请求数
  - 停止后恢复时间(每 10min 探测 1 次)
  - 恢复后重跑,测累犯加速

用法:
  python c6_ratelimit_causality.py --platform bilibili [--interval 300] [--phases 2] [--dry-run]

输出:
  experiments/data/c6_{platform}.json  (结构化结果)
  stdout 进度日志
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# 保证能 import platform_adapters
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platform_adapters"))

from common import LiveStatus, classify_error  # noqa: E402

ANCHOR_FILES = {
    "bilibili": ROOT / "experiments" / "test_anchors" / "bilibili.txt",
    "douyin": ROOT / "experiments" / "test_anchors" / "douyin.txt",
    "huya": ROOT / "experiments" / "test_anchors" / "huya.txt",
    "douyu": ROOT / "experiments" / "test_anchors" / "douyu.txt",
}

# 限流信号判定阈值(草案,实验后校准)
SLOW_MS = 60_000        # 延迟 > 60s 视为慢响应
VERY_SLOW_MS = 300_000  # 延迟 > 300s 视为严重慢响应
CONSECUTIVE_THRESHOLD = 3  # 连续 N 次异常视为限流


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_anchors(platform: str) -> list[str]:
    fp = ANCHOR_FILES[platform]
    anchors = []
    for line in fp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        anchors.append(line)
    return anchors


def build_adapter(platform: str):
    """按平台实例化 adapter,复用统一 get_status(url) 接口。"""
    mod = __import__(f"platform_adapters.{platform}.adapter", fromlist=["adapter"])
    # 每个 adapter 的类名不统一,用反射找含 get_status 的实例化入口
    # 常见命名:BilibiliAdapter / DouyinAdapter / HuyaAdapter / DouyuAdapter
    for name in dir(mod):
        if name.lower().startswith(platform) and "adapter" in name.lower():
            cls = getattr(mod, name)
            if isinstance(cls, type):
                return cls()
    # 兜底:直接实例化模块内的 adapter 实例(部分模块导出单例)
    for name in ("adapter", "client", "api"):
        obj = getattr(mod, name, None)
        if obj is not None and hasattr(obj, "get_status"):
            return obj
    raise RuntimeError(f"cannot instantiate adapter for {platform}")


def probe(adapter, anchor: str) -> dict:
    """单次探测,返回结构化结果(不抛异常)。"""
    start = time.monotonic()
    try:
        r = adapter.get_status(anchor)
        latency = int((time.monotonic() - start) * 1000)
        state = r.get("state", "UNKNOWN")
        # 提取异常详情(部分 adapter 返回 error 字段)
        return {
            "ok": True,
            "anchor": anchor,
            "state": state,
            "latency_ms": latency,
            "detail": {k: v for k, v in r.items() if k not in ("state",)},
        }
    except Exception as e:
        latency = int((time.monotonic() - start) * 1000)
        return {
            "ok": False,
            "anchor": anchor,
            "state": "EXCEPTION",
            "latency_ms": latency,
            "detail": {"error": f"{type(e).__name__}: {e}"},
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--platform", required=True, choices=list(ANCHOR_FILES))
    ap.add_argument("--interval", type=int, default=300, help="探测间隔秒(默认 300 = 0.02 req/s 基线)")
    ap.add_argument("--phases", type=int, default=2, help="跑几轮(默认 2:首犯 + 累犯)")
    ap.add_argument("--dry-run", action="store_true", help="只初始化不探测")
    args = ap.parse_args()

    anchors = load_anchors(args.platform)
    print(f"[C6] platform={args.platform} anchors={anchors} interval={args.interval}s phases={args.phases}")
    if args.dry_run:
        print("[C6] dry-run: adapter 初始化 + 1 次探测")
        adapter = build_adapter(args.platform)
        print(f"  adapter={type(adapter).__name__}")
        r = probe(adapter, anchors[0])
        print(f"  probe={json.dumps(r, ensure_ascii=False, default=str)[:300]}")
        return 0

    adapter = build_adapter(args.platform)
    print(f"[C6] adapter={type(adapter).__name__}", flush=True)

    # 结果容器 + 实时落盘(防进程被杀丢数据)
    OUT_JSONL = ROOT / "experiments" / "data" / f"c6_{args.platform}.jsonl"
    OUT_JSON = ROOT / "experiments" / "data" / f"c6_{args.platform}.json"
    jsonl = OUT_JSONL.open("a", encoding="utf-8")
    result = {
        "platform": args.platform,
        "started_at": now_iso(),
        "interval_s": args.interval,
        "anchor_count": len(anchors),
        "phases": [],
    }

    # 每轮:轮询直到触发限流信号,然后进入恢复探测
    for phase in range(1, args.phases + 1):
        print(f"\n===== Phase {phase}: 持续轮询(找限流信号)=====", flush=True)
        phase_data = {
            "phase": phase,
            "started_at": now_iso(),
            "requests": [],
            "first_signal_at": None,
            "requests_before_signal": 0,
            "signal_type": None,
        }
        consec_bad = 0
        slow_count = 0
        total_req = 0
        stop_flag = False

        while not stop_flag:
            for anchor in anchors:
                total_req += 1
                r = probe(adapter, anchor)
                entry = {
                    "ts": now_iso(),
                    "seq": total_req,
                    **r,
                }
                phase_data["requests"].append(entry)
                # 实时写 JSONL(防进程被杀丢数据)
                jsonl.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
                jsonl.flush()
                lat = r["latency_ms"]
                is_bad = (not r["ok"]) or (lat > VERY_SLOW_MS)
                is_slow = lat > SLOW_MS

                if r["ok"]:
                    print(f"  [{total_req:>3}] {anchor} {r['state']} {lat}ms", flush=True)
                else:
                    print(f"  [{total_req:>3}] {anchor} EXCEPTION {lat}ms {r['detail'].get('error', '')[:80]}", flush=True)

                if is_bad:
                    consec_bad += 1
                    if is_slow:
                        slow_count += 1
                else:
                    consec_bad = 0

                # 触发条件:连续 3 次异常 OR 慢响应累计 5 次
                if consec_bad >= CONSECUTIVE_THRESHOLD or slow_count >= 5:
                    phase_data["first_signal_at"] = now_iso()
                    phase_data["requests_before_signal"] = total_req
                    phase_data["signal_type"] = "slow" if slow_count >= 5 else "connection_error"
                    print(f"\n  ★ 限流信号触发: {phase_data['signal_type']}, 累计 {total_req} 请求, at {phase_data['first_signal_at']}")
                    stop_flag = True
                    break

                time.sleep(args.interval)

            # 一轮 anchors 轮完还没触发 → 继续(可能跑很久)

        # 恢复探测:每 10min 探 1 次,最多 24h
        print(f"\n===== Phase {phase}: 恢复探测(每 10min 探 1 次)=====", flush=True)
        recovery_entries = []
        for attempt in range(1, 145):  # 24h
            time.sleep(600)
            r = probe(adapter, anchors[0])
            rec = {"ts": now_iso(), "attempt": attempt, "recovery_probe": True, **r}
            recovery_entries.append(rec)
            jsonl.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            jsonl.flush()
            if r["ok"] and r["latency_ms"] < SLOW_MS:
                print(f"  ✓ 恢复 @ {rec['ts']} (attempt {attempt}, {attempt*10}min)", flush=True)
                phase_data["recovered_at"] = rec["ts"]
                phase_data["recovery_minutes"] = attempt * 10
                break
            print(f"  ⏳ 未恢复 (attempt {attempt}, {attempt*10}min) {r['state']} {r['latency_ms']}ms", flush=True)
        phase_data["recovery_probe"] = recovery_entries
        result["phases"].append(phase_data)

    jsonl.close()
    result["finished_at"] = now_iso()
    out = ROOT / "experiments" / "data" / f"c6_{args.platform}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[√] 结果已写入 {out}(完整记录在 {OUT_JSONL})", flush=True)

    # 汇总
    print("\n===== 汇总 =====", flush=True)
    for ph in result["phases"]:
        print(f"  Phase {ph['phase']}: 触发信号={ph.get('signal_type')} 请求数={ph.get('requests_before_signal')} 恢复={ph.get('recovery_minutes')}min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
