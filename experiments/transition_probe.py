"""主动找状态转换: 对比两个时间点的虎牙在播列表,找出 ONLINE→OFFLINE 的房间。

用法:
  python transition_probe.py snapshot1.json  # 拉第二次快照并对比
"""
import httpx, json, sys, time
from pathlib import Path

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0'
headers = {'User-Agent': UA, 'Referer': 'https://www.huya.com/'}
OUT = Path('experiments/data')


def fetch_live() -> dict:
    live = {}
    for page in range(1, 4):
        r = httpx.get(f'https://www.huya.com/cache.php?m=LiveList&do=getLiveListByPage&tagAll=0&page={page}', headers=headers, timeout=15)
        d = r.json()
        for room in d.get('data', {}).get('datas', []):
            rid = str(room.get('roomid') or room.get('profileRoom'))
            live[rid] = room.get('nick', '?')
    return live


def main() -> int:
    snap_path = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / 'transition_probe_snapshot1.json'
    snap1 = json.loads(snap_path.read_text(encoding='utf-8'))
    print(f'第一次快照: {len(snap1)} 个在播房间 @ {snap_path.name}')

    # 拉第二次
    snap2 = fetch_live()
    print(f'第二次快照: {len(snap2)} 个在播房间 @ {time.strftime("%H:%M:%S")}')
    json.dump(snap2, open(OUT / 'transition_probe_snapshot2.json', 'w'), ensure_ascii=False)

    # 对比: 第一次在播但第二次不在 = ONLINE→OFFLINE(候选转换)
    gone = {rid: nick for rid, nick in snap1.items() if rid not in snap2}
    # 第二次在播但第一次不在 = OFFLINE→ONLINE(候选转换)
    new = {rid: nick for rid, nick in snap2.items() if rid not in snap1}

    print(f'\n=== ONLINE→OFFLINE 候选: {len(gone)} 个 ===')
    for rid, nick in list(gone.items())[:20]:
        print(f'  {rid}: {nick}')
    print(f'\n=== OFFLINE→ONLINE 候选: {len(new)} 个 ===')
    for rid, nick in list(new.items())[:20]:
        print(f'  {rid}: {nick}')

    result = {'time1': snap_path.name, 'time2': 'now', 'online_to_offline': gone, 'offline_to_online': new}
    (OUT / 'transition_probe_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n结果已存 transition_probe_result.json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
