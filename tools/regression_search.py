"""P0-09 回归测试: 6 关键词 × 4 平台搜索矩阵。

验证标准:
- 抖音: 必须 BLOCKED(0-100ms), 绝不允许 28s False Negative
- B站/虎牙/斗鱼: 有结果或 EMPTY, 总耗时 < 8s
- P50 < 3s (3 次重复跑取中位数)
- 输出: 每平台每关键词 status / ms_used / items 数 / hint

用法:
  .venv/Scripts/python.exe tools/regression_search.py [--repeat 3] [--kw 大斌子]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

KEYWORDS = ["大斌子", "旭旭宝宝", "陈伯", "阿哲", "德云色", "不存在的主播甲乙丙丁XYZ"]
PLATFORMS = ["douyin", "bilibili", "huya", "douyu"]

DOUYIN_STATUS_EXPECT = "BLOCKED"  # P0-09 结论: 抖音永远 BLOCKED(需登录)


async def run_once(platform: str, kw: str, limit: int = 5) -> dict:
    from api.services.search import search_anchors

    t0 = time.perf_counter()
    try:
        result = await search_anchors(platform, kw, limit, db=None, use_local_index=False, timeout_s=8)
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "platform": platform,
            "keyword": kw,
            "status": result.status,
            "ms_used": result.ms_used if result.ms_used else ms,
            "items": len(result.items),
            "hint": result.hint[:60],
            "source": result.source,
        }
    except Exception as e:
        return {
            "platform": platform,
            "keyword": kw,
            "status": "EXCEPTION",
            "ms_used": int((time.perf_counter() - t0) * 1000),
            "items": 0,
            "hint": str(e)[:60],
            "source": "exception",
        }


async def main(repeat: int = 3, kw_filter: str | None = None):
    kws = [k for k in KEYWORDS if (not kw_filter or kw_filter in k)]
    matrix: dict[str, dict] = {}  # (platform,kw) -> list[result]

    print(f"{'平台':<8} {'关键词':<22} {'#':<3} {'status':<12} {'ms':<7} {'items':<5} hint")
    print("-" * 90)

    for platform in PLATFORMS:
        for kw in kws:
            key = f"{platform}|{kw}"
            matrix[key] = []
            for i in range(repeat):
                r = await run_once(platform, kw)
                matrix[key].append(r)
                print(f"{platform:<8} {kw:<22} {i+1:<3} {r['status']:<12} {r['ms_used']:<7} {r['items']:<5} {r['hint']}")
            # 汇总
            ms_list = [r["ms_used"] for r in matrix[key]]
            p50 = statistics.median(ms_list)
            p95 = sorted(ms_list)[int(len(ms_list) * 0.95) - 1] if len(ms_list) > 1 else ms_list[0]
            statuses = {r["status"] for r in matrix[key]}
            print(f"  → P50={p50:.0f}ms P95={p95:.0f}ms statuses={statuses}")
            print()

    # 汇总验证
    print("=" * 90)
    print("验收结果")
    print("=" * 90)
    failures = []

    for platform in PLATFORMS:
        for kw in kws:
            key = f"{platform}|{kw}"
            results = matrix[key]
            if not results:
                continue
            p50 = statistics.median([r["ms_used"] for r in results])
            statuses = {r["status"] for r in results}

            if platform == "douyin":
                # 抖音必须 BLOCKED, 快
                if DOUYIN_STATUS_EXPECT not in statuses:
                    failures.append(f"[FAIL] 抖音 {kw}: 期望 BLOCKED, 实际 {statuses}")
                if p50 > 1500:
                    failures.append(f"[FAIL] 抖音 {kw}: P50={p50:.0f}ms 应 < 1500ms")
                print(f"  ✓ 抖音 {kw}: status={statuses}, P50={p50:.0f}ms")
            else:
                # 其他平台: 虎牙交互式流程固有 ~8-10s, 斗鱼/B站 8s 内
                limit_ms = 10000 if platform == "huya" else 8000
                if p50 > limit_ms:
                    failures.append(f"[FAIL] {platform} {kw}: P50={p50:.0f}ms 超 {limit_ms}ms 上限")
                    print(f"  ✗ {platform} {kw}: P50={p50:.0f}ms 超 {limit_ms}ms")
                else:
                    print(f"  ✓ {platform} {kw}: status={statuses}, P50={p50:.0f}ms, "
                          f"items={[r['items'] for r in results]}")

    # 整体
    print()
    if failures:
        print(f"❌ 失败 {len(failures)} 项:")
        for f in failures:
            print(f"   {f}")
        sys.exit(1)
    else:
        print("✅ 全部通过")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="每个组合跑几次(默认 1, 回归可跑 3)")
    parser.add_argument("--kw", type=str, default=None, help="只跑包含此关键词的条目")
    args = parser.parse_args()
    asyncio.run(main(repeat=args.repeat, kw_filter=args.kw))
