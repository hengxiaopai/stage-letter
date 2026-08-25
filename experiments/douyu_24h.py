"""
Douyu 24h 稳定性实验 — Gate 0B

与 bilibili_24h.py 结构一致,仅 adapter 不同。
详见 experiments/bilibili_24h.py 顶部注释。
"""
import argparse
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from platform_adapters.douyu.adapter import DouyuAdapter  # noqa: E402
from platform_adapters.common import LiveStatus, ALL_STATES  # noqa: E402

ANCHORS_FILE = ROOT / "experiments" / "test_anchors" / "douyu.txt"
DATA_DIR = ROOT / "experiments" / "data"

CST = timezone(timedelta(hours=8))


def load_anchors(path: Path) -> list:
    if not path.exists():
        raise FileNotFoundError(f"找不到主播列表: {path}")
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.isupper() and "PLACEHOLDER" in line:
            continue
        lines.append(line)
    if not lines:
        print(f"WARNING: {path} 没有可用的 anchor,将以空列表跑(只验证 adapter 稳定性)", file=sys.stderr)
    return lines


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def setup_logging(log_path: Path) -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("douyu_24h")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def run(duration_seconds: int, interval_seconds: int, anchors: list, soak_type: str = "correctness") -> dict:
    ts = datetime.now(CST).strftime("%Y%m%d-%H%M")
    log_path = DATA_DIR / f"douyu_24h-{ts}.log"
    jsonl_path = DATA_DIR / f"douyu_24h-{ts}.jsonl"

    logger = setup_logging(log_path)
    adapter = DouyuAdapter(min_interval=max(2, interval_seconds / 2))

    logger.info("=== Douyu 24h 稳定性实验启动 ===")
    logger.info("主播数: %d, 轮询间隔: %ds, 持续时长: %ds (~%.1fh)", len(anchors), interval_seconds, duration_seconds, duration_seconds / 3600)
    logger.info("日志: %s", log_path)
    logger.info("样本: %s", jsonl_path)

    end_at = time.time() + duration_seconds
    total_rounds = 0
    total_checks = 0
    state_counts = {s: 0 for s in ALL_STATES}
    live_transitions: list = []
    state_transitions: list = []
    error_counts: dict = {}
    latency_ms_list: list = []

    jsonl_f = open(jsonl_path, "a", encoding="utf-8")
    last_state_map: dict = {a: None for a in anchors}

    try:
        round_idx = 0
        while time.time() < end_at:
            round_idx += 1
            round_start = time.time()
            round_msgs = []

            for url in anchors:
                t0 = time.time()
                result = adapter.get_status(url)
                latency_ms = int((time.time() - t0) * 1000)
                latency_ms_list.append(latency_ms)

                record = {
                    "ts": now_cst(),
                    "url": url,
                    "round": round_idx,
                    "latency_ms": latency_ms,
                    "result": result,
                }
                jsonl_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                jsonl_f.flush()

                total_checks += 1
                state = result.get("state", LiveStatus.UNKNOWN.value)
                state_counts[state] = state_counts.get(state, 0) + 1

                prev = last_state_map.get(url)
                if prev is not None and prev != state:
                    state_transitions.append((url, prev, state, now_cst()))
                    if prev == LiveStatus.ONLINE.value or state == LiveStatus.ONLINE.value:
                        live_transitions.append((url, prev, state, now_cst()))
                last_state_map[url] = state

                if result.get("ok"):
                    round_msgs.append(f"[{result.get('room_id')}] state={state} ({latency_ms}ms)")
                else:
                    err = result.get("errcode", -1)
                    error_counts[err] = error_counts.get(err, 0) + 1
                    round_msgs.append(f"[{state}] err={err} {result.get('errmsg', '?')[:50]} ({latency_ms}ms)")

            total_rounds += 1
            elapsed = int(time.time() - round_start)
            logger.info("Round %d 完成, 用时 %ds, live_transitions=%d, errors=%s", round_idx, elapsed, len(live_transitions), dict(error_counts))
            for m in round_msgs:
                logger.info("  - %s", m)

            sleep_for = interval_seconds - elapsed
            if sleep_for > 0 and time.time() + sleep_for < end_at:
                time.sleep(sleep_for)

    except KeyboardInterrupt:
        logger.warning("用户中断(Ctrl-C),正在收尾...")
    finally:
        jsonl_f.close()

    p50 = statistics.median(latency_ms_list) if latency_ms_list else 0
    p95 = (
        statistics.quantiles(latency_ms_list, n=20)[-1] if len(latency_ms_list) >= 20 else max(latency_ms_list, default=0)
    )
    summary = {
        "platform": "douyu",
        "soak_type": soak_type,
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "anchors": anchors,
        "rounds": total_rounds,
        "total_checks": total_checks,
        "state_distribution": state_counts,
        "live_transitions": [{"url": t[0], "from": t[1], "to": t[2], "at": t[3]} for t in live_transitions],
        "all_state_transitions": [{"url": t[0], "from": t[1], "to": t[2], "at": t[3]} for t in state_transitions],
        "error_distribution": dict(error_counts),
        "latency_ms": {
            "p50": int(p50),
            "p95": int(p95),
            "min": int(min(latency_ms_list)) if latency_ms_list else 0,
            "max": int(max(latency_ms_list)) if latency_ms_list else 0,
        },
        "log_path": str(log_path),
        "samples_path": str(jsonl_path),
        "ended_at": now_cst(),
    }
    summary_path = DATA_DIR / f"douyu_24h-{ts}.summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("=== 实验结束 ===")
    logger.info("Summary: %s", json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser(description="Douyu 24h 稳定性实验")
    p.add_argument("--duration-hours", type=float, default=24.0)
    p.add_argument("--interval-seconds", type=int, default=300)
    p.add_argument("--smoke", action="store_true")
    p.add_argument(
        "--soak-type",
        choices=["correctness", "transport", "error-path"],
        default="correctness",
    )
    args = p.parse_args()

    anchors = load_anchors(ANCHORS_FILE)
    if args.smoke:
        run(duration_seconds=60, interval_seconds=10, anchors=anchors, soak_type=args.soak_type)
    else:
        run(duration_seconds=int(args.duration_hours * 3600), interval_seconds=args.interval_seconds, anchors=anchors, soak_type=args.soak_type)


if __name__ == "__main__":
    main()
