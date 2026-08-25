"""分析中断的 24h correctness 浸泡 JSONL 数据,输出 7-state 统计 + 状态转换。"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("experiments/data")
ALL_STATES = ["ONLINE", "OFFLINE", "NOT_FOUND", "RATE_LIMITED", "BLOCKED", "PARSE_ERROR", "UNKNOWN"]

for platform in ["bilibili", "huya", "douyu", "douyin"]:
    files = sorted(DATA.glob(f"{platform}_24h-*.jsonl"))
    if not files:
        print(f"\n### {platform}: 无数据")
        continue
    f = files[-1]
    if f.stat().st_size == 0:
        print(f"\n### {platform}: 空文件 {f.name}")
        continue

    state_counts = Counter()
    err_counts = Counter()
    latencies = []
    per_anchor_state = defaultdict(Counter)
    transitions = []  # (url, prev, cur, ts)
    last_state = {}
    rounds = set()
    samples = 0
    first_ts, last_ts = None, None

    with open(f, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = rec.get("url", "?")
            ts = rec.get("ts", "?")
            lat = rec.get("latency_ms")
            if lat is not None:
                latencies.append(lat)
            res = rec.get("result") or {}
            state = res.get("state", "UNKNOWN")
            state_counts[state] += 1
            per_anchor_state[url][state] += 1
            if not res.get("ok"):
                err_counts[res.get("errcode", res.get("errmsg", "?"))] += 1
            rounds.add(rec.get("round"))
            samples += 1
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            prev = last_state.get(url)
            if prev is not None and prev != state:
                transitions.append((url, prev, state, ts))
            last_state[url] = state

    print(f"\n### {platform} — {f.name}")
    print(f"样本数: {samples} | 轮次: {min(rounds)}-{max(rounds)} | 时间: {first_ts} ~ {last_ts}")
    print(f"7-state 分布: { {s: state_counts.get(s, 0) for s in ALL_STATES} }")
    print(f"错误分布(errno): {dict(err_counts) if err_counts else '无'}")
    if latencies:
        latencies.sort()
        n = len(latencies)
        print(f"latency: min={latencies[0]}ms p50={latencies[n//2]}ms p95={latencies[int(n*0.95)]}ms max={latencies[-1]}ms")
    print(f"状态转换数: {len(transitions)}")
    for t in transitions[:15]:
        print(f"  {t}")
    if len(transitions) > 15:
        print(f"  ... 共 {len(transitions)} 条")
    print("每个 anchor 的状态分布:")
    for url, c in per_anchor_state.items():
        print(f"  {url}: {dict(c)}")
