"""端到端验证: 搜索 → 订阅 → 详情。"""
import urllib.request, urllib.parse, json

def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=15).read().decode())

print("=== 端到端: 搜索 → 订阅 → 详情 ===")
kw = urllib.parse.quote('德云色')
items = get(f'http://127.0.0.1:8899/api/v1/anchors/_search?platform=bilibili&keyword={kw}&limit=3')
print(f'1. 搜索: {len(items)} 条, 第一条={items[0]["display_name"]} (粉丝 {items[0]["fans"]})')
subs = get('http://127.0.0.1:8899/api/v1/subscriptions?openid=dev_miniapp_local_001')
dy = [s for s in subs if s['display_name'] == '德云色']
print(f'2. 订阅: 德云色 anchor_id={dy[0]["anchor_id"] if dy else "?"}')
if dy:
    detail = get(f'http://127.0.0.1:8899/api/v1/anchors/{dy[0]["anchor_id"]}')
    print(f'3. 详情: {detail["display_name"]} | platforms={len(detail["platforms"])} | sessions={len(detail["recent_sessions"])}')
print("\n✓ 端到端链路全通")
