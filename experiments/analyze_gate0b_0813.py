# -*- coding: utf-8 -*-
"""Gate 0B/0C 收尾分析: 虎牙/斗鱼 4h soak + 盯梢 + C6"""
import json, os, sys
from collections import Counter

DATA = r"G:\workbuddy\code\stage-letter\experiments\data"
OLD = r"G:\workbuddy\code\live-radar\experiments\data"

STATES = ["ONLINE","OFFLINE","NOT_FOUND","RATE_LIMITED","BLOCKED","PARSE_ERROR","UNKNOWN"]

def load_jsonl(p):
    rows=[]
    with open(p, encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception as e: rows.append({"__parse_err__": str(e), "raw": line[:200]})
    return rows

def soak_analysis(platform, batches):
    """batches: list of filenames"""
    all_rows=[]
    for b in batches:
        p=os.path.join(DATA,b)
        if os.path.exists(p):
            all_rows += load_jsonl(p)
    if not all_rows:
        print(f"[{platform}] 无数据")
        return
    dist=Counter(r.get("result",{}).get("state","?") for r in all_rows if "result" in r)
    errs=Counter(r.get("result",{}).get("state","?") for r in all_rows if "result" in r)
    # 按 room 分
    by_room={}
    for r in all_rows:
        res=r.get("result",{})
        rid=res.get("room_id") or r.get("url")
        by_room.setdefault(rid,[]).append(res.get("state"))
    print(f"\n===== {platform} 4h soak =====")
    print(f"总样本数: {len(all_rows)}")
    print("7态分布:", {s: dist.get(s,0) for s in STATES}, "其他:", {k:v for k,v in dist.items() if k not in STATES})
    print("按房间状态:")
    for rid, sts in by_room.items():
        c=Counter(sts)
        print(f"  room={rid}: {dict(c)} (共{len(sts)}次)")
    # 转换检测: 按房间看是否出现过不同状态
    print("状态转换检测(按房间):")
    any_trans=False
    for rid, sts in by_room.items():
        prev=None
        for i,s in enumerate(sts):
            if prev is not None and s!=prev:
                print(f"  !! room={rid} 第{i}次采样 状态 {prev} -> {s}")
                any_trans=True
            prev=s
    if not any_trans:
        print("  无任何状态转换")
    # 错误分布
    err_detail=Counter()
    for r in all_rows:
        res=r.get("result",{})
        if not res.get("ok") or res.get("state") in ("RATE_LIMITED","BLOCKED","PARSE_ERROR","NOT_FOUND","UNKNOWN"):
            err_detail[(res.get("state"), res.get("error",""))]+=1
    if err_detail:
        print("异常明细:", dict(err_detail))
    else:
        print("无异常")
    return all_rows

print("="*70)
print("1) 虎牙 4h soak (0920 + 1121 两批)")
rows_h1 = soak_analysis("HUYA", ["huya_24h-20260813-0920.jsonl","huya_24h-20260813-1121.jsonl"])
print("="*70)
print("2) 斗鱼 4h soak (0920 + 1121 两批)")
rows_d1 = soak_analysis("DOUYU", ["douyu_24h-20260813-0920.jsonl","douyu_24h-20260813-1121.jsonl"])

print("\n"+"="*70)
print("3) 转换盯梢 transition_watch")
tw=load_jsonl(os.path.join(DATA,"transition_watch_log.jsonl"))
print(f"盯梢总条数: {len(tw)}")
tw_dist=Counter(r.get("state") for r in tw)
print("盯梢状态分布:", dict(tw_dist))
by_room={}
for r in tw:
    by_room.setdefault(r.get("room"),[]).append(r.get("state"))
for rid, sts in by_room.items():
    print(f"  room={rid}: {dict(Counter(sts))} (共{len(sts)}次)")
# 盯梢转换检测
print("盯梢转换检测:")
any_tw=False
for rid, sts in by_room.items():
    prev=None
    for i,s in enumerate(sts):
        if prev is not None and s!=prev:
            print(f"  !! room={rid} #{i} {prev} -> {s}")
            any_tw=True
        prev=s
if not any_tw:
    print("  无任何状态转换")

print("\n"+"="*70)
print("4) C6 因果实验 (旧目录)")
for plat, fn in [("BILIBILI","c6_bilibili.jsonl"), ("DOUYIN","c6_douyin.jsonl")]:
    p=os.path.join(OLD,fn)
    if not os.path.exists(p):
        print(f"[{plat}] 文件不存在: {p}")
        continue
    rows=load_jsonl(p)
    print(f"\n===== C6 {plat} =====")
    print(f"总样本: {len(rows)}")
    if not rows: continue
    # 首尾时间
    print(f"首条: {rows[0].get('ts')} 末条: {rows[-1].get('ts')}")
    # 状态序列
    seqs=[(r.get("seq"), r.get("state"), r.get("latency_ms"), r.get("ts")) for r in rows]
    print("状态序列: " + " -> ".join(str(s[1]) for s in seqs))
    # 限流/异常信号
    signals=[]
    for r in rows:
        st=r.get("state")
        d=r.get("detail",{})
        err = d.get("error") or r.get("error") or (r.get("ok") if "ok" in r else None)
        if st in ("RATE_LIMITED","BLOCKED","PARSE_ERROR","UNKNOWN") or (r.get("ok") is False):
            signals.append((r.get("seq"), r.get("ts"), st, err))
    print(f"限流/异常信号: {len(signals)} 条")
    for s in signals:
        print("   ", s)
    # latency 统计
    lat=[r.get("latency_ms") for r in rows if isinstance(r.get("latency_ms"),(int,float))]
    if lat:
        print(f"latency: min={min(lat)} max={max(lat)} avg={sum(lat)/len(lat):.0f} n={len(lat)}")
    # 触发限流前请求数
    for i,r in enumerate(rows):
        if r.get("state") in ("RATE_LIMITED","BLOCKED"):
            print(f"  触发 {r.get('state')} 在第 {r.get('seq')} 次请求 (seq={r.get('seq')}), 触发前成功请求数≈{i}")
