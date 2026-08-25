"""高频盯梢: 盯住刚开播的主播,直到捕获 ONLINE→OFFLINE 转换。

用法:
  python transition_watch.py [duration_minutes]
  默认盯 90 分钟,每 60s 探测一次候选房间。
"""
import sys, time, json
from pathlib import Path
import httpx

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from platform_adapters.huya.adapter import HuyaAdapter

OUT = Path('experiments/data')
_ADAPTER = None


def _adapter():
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = HuyaAdapter()
    return _ADAPTER

# 刚开播的候选(从 OFFLINE→ONLINE 验证为 ONLINE 的房间)
WATCH_ROOMS = ['142761', '31256203', '30985600', '17611785', '32233']


def get_status(rid: str) -> dict:
    """复用已验证的 HuyaAdapter.get_status(完整解析链)。"""
    try:
        r = _adapter().get_status(f'https://www.huya.com/{rid}')
        state = r.get('state', 'UNKNOWN')
        return {'state': state, 'raw': r.get('raw_status'), 'parse': r.get('parse_method')}
    except Exception as e:
        return {'state': 'EXCEPTION', 'err': str(e)[:60]}


def main() -> int:
    duration_min = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    interval = 60
    end = time.time() + duration_min * 60
    log_path = OUT / 'transition_watch_log.jsonl'
    log = open(log_path, 'a', encoding='utf-8')

    print(f'盯梢 {len(WATCH_ROOMS)} 个刚开播房间,最长 {duration_min} 分钟,每 {interval}s 探测')
    print(f'目标: 捕获至少一个 ONLINE→OFFLINE 转换')

    transitions = []
    prev = {rid: None for rid in WATCH_ROOMS}

    while time.time() < end:
        for rid in WATCH_ROOMS:
            try:
                st = get_status(rid)
            except Exception as e:
                st = {'state': 'EXCEPTION', 'err': str(e)[:50]}
            entry = {'ts': time.strftime('%Y-%m-%d %H:%M:%S'), 'room': rid, **st}
            log.write(json.dumps(entry, ensure_ascii=False) + '\n')
            log.flush()

            # 检测转换
            if prev[rid] == 'ONLINE' and st.get('state') == 'OFFLINE':
                transitions.append({'room': rid, 'at': entry['ts'], 'type': 'ONLINE→OFFLINE'})
                print(f'\n  ★★★ 捕获转换! 房间 {rid} ONLINE→OFFLINE @ {entry["ts"]} ★★★')
            if prev[rid] == 'OFFLINE' and st.get('state') == 'ONLINE':
                transitions.append({'room': rid, 'at': entry['ts'], 'type': 'OFFLINE→ONLINE'})
                print(f'\n  ★ 捕获转换! 房间 {rid} OFFLINE→ONLINE @ {entry["ts"]}')

            prev[rid] = st.get('state')
            status_str = st.get('state', '?')
            print(f'  {entry["ts"]} {rid}: {status_str}', flush=True)

        if transitions:
            # 至少一次转换,可以结束了
            break
        time.sleep(interval)

    log.close()
    result = {'transitions': transitions, 'log': str(log_path)}
    (OUT / 'transition_watch_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if transitions:
        print(f'\n✓ 捕获 {len(transitions)} 次转换,结果已存 transition_watch_result.json')
    else:
        print(f'\n⏳ {duration_min} 分钟内未捕获转换(主播可能长时间在线),可继续延长')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
