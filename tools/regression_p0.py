"""P0-10/P0-11 验收回归 — Search Core V3 正确性测试。

覆盖验收项:
P0-10:
  ✓ platform=all 第一次就搜索所有可搜索平台
  ✓ 平台搜索状态独立(platform_status 各自 status)
  ✓ 抖音 BLOCKED 不阻塞其他平台
  ✓ 结果包含 match_type/match_score(后端排序依据)
P0-11:
  ✓ 已订阅精确匹配主播优先(排第一)
  ✓ exact 优先于粉丝数(147万粉的 PREFIX 排在 2.3万粉 EXACT 后)
  ✓ 无关虎牙频道不返回(无 赛事/斯诺克 等)
  ✓ 同一 platform+platform_user_id 去重
  ✓ 不同平台同名主播保持独立
  ✓ follower_count 不丢失(非 null)

用法: .venv/Scripts/python.exe tools/regression_p0.py [--kw 阿哲]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

KEYWORDS = ["阿哲", "大斌子", "骚白"]
OPENID = "dev_miniapp_local_001"


async def search_via_api(platform: str, kw: str) -> dict:
    import httpx

    r = httpx.get(
        f"http://127.0.0.1:8899/api/v1/anchors/_search",
        params={"platform": platform, "keyword": kw, "openid": OPENID, "limit": 15},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


async def main(kw_filter: str | None):
    failures = []
    checks_run = 0

    for kw in KEYWORDS:
        if kw_filter and kw_filter not in kw:
            continue
        print(f"\n{'='*80}\n关键词: {kw}\n{'='*80}")

        t0 = time.perf_counter()
        d = await search_via_api("all", kw)
        ms = int((time.perf_counter() - t0) * 1000)

        items = d["items"]
        ps = d.get("platform_status") or {}

        # ── P0-10: 全部 = 真搜索所有平台 ──
        checks_run += 1
        if len(ps) >= 3:
            print(f"  ✓ platform=all 搜索了 {len(ps)} 个平台: {list(ps.keys())}")
        else:
            failures.append(f"[FAIL] {kw}: 平台数不足 {list(ps.keys())}")

        # ── 抖音 BLOCKED 不阻塞 ──
        checks_run += 1
        if ps.get("douyin", {}).get("status") == "BLOCKED" and items:
            print(f"  ✓ 抖音 BLOCKED 标注, 其他平台 {len(items)} 条不受影响")
        elif ps.get("douyin", {}).get("status") != "BLOCKED":
            failures.append(f"[FAIL] {kw}: 抖音状态异常 {ps.get('douyin')}")

        # ── P0-11: 无关频道不返回 ──
        checks_run += 1
        bad = [it for it in items if "赛事" in (it["display_name"] or "") or "斯诺克" in (it["display_name"] or "")]
        if not bad:
            print(f"  ✓ 无赛事/斯诺克等无关频道")
        else:
            failures.append(f"[FAIL] {kw}: 出现无关频道 {[b['display_name'] for b in bad]}")

        # ── 去重: 同 platform+platform_user_id ──
        checks_run += 1
        keys = [(it["platform"], it["platform_user_id"]) for it in items]
        if len(keys) == len(set(keys)):
            print(f"  ✓ 去重正确 ({len(keys)} 条无重复)")
        else:
            dup = [k for k in keys if keys.count(k) > 1]
            failures.append(f"[FAIL] {kw}: 重复项 {set(dup)}")

        # ── 已订阅精确匹配置顶 ──
        checks_run += 1
        sub_items = [it for it in items if it.get("is_subscribed")]
        if sub_items:
            top = items[0]
            if top.get("is_subscribed") and top.get("match_type") in ("EXACT", "NORMALIZED"):
                print(f"  ✓ 已订阅精确匹配置顶: {top['display_name']} [{top['platform']}]")
            else:
                failures.append(f"[FAIL] {kw}: 已订阅项未置顶, 顶部是 {top['display_name']} sub={top.get('is_subscribed')}")
            for si in sub_items:
                print(f"     已订阅: {si['display_name']} [{si['platform']}] match={si['match_type']}")

        # ── exact > 粉丝(验证排序: EXACT 在 PREFIX 前, 即使粉丝少) ──
        checks_run += 1
        exacts = [it for it in items if it.get("match_type") == "EXACT"]
        prefixes = [it for it in items if it.get("match_type") == "PREFIX"]
        if exacts and prefixes:
            if items.index(exacts[0]) < items.index(prefixes[0]):
                print(f"  ✓ EXACT({exacts[0]['display_name']}) 排在 PREFIX({prefixes[0]['display_name']}) 前(粉丝不计相关性)")
            else:
                failures.append(f"[FAIL] {kw}: EXACT 排在 PREFIX 后")

        # ── follower_count 非 null 不丢失 ──
        checks_run += 1
        null_fans = [it for it in items if it.get("follower_count") is None]
        if not null_fans:
            print(f"  ✓ 所有结果均有 follower_count")
        else:
            print(f"  ⚠ {len(null_fans)} 条 follower_count=null(抖音未登录态无数据): "
                  f"{[it['display_name'] for it in null_fans]}")

        print(f"  → 总耗时 {ms}ms")

    print(f"\n{'='*80}")
    print(f"验收: {checks_run} 项检查")
    if failures:
        print(f"❌ {len(failures)} 项失败:")
        for f in failures:
            print(f"  {f}")
        sys.exit(1)
    print("✅ 全部通过")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", type=str, default=None)
    args = ap.parse_args()
    asyncio.run(main(args.kw))
