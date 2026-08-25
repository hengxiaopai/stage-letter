"""端到端: 虎牙搜索 → 订阅 → 详情(浏览器搜索链路)。"""
import urllib.request, urllib.parse, json, time

B = 'http://127.0.0.1:8899/api/v1'
OPENID = 'dev_miniapp_local_001'

def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read().decode())

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

print("=== 虎牙浏览器搜索(经 API)===")
kw = urllib.parse.quote('姿态')
items = get(f'{B}/anchors/_search?platform=huya&keyword={kw}&limit=5&openid={OPENID}')
print(f'返回 {len(items)} 条')
for it in items[:3]:
    print(f'  {it["display_name"]} | rid={it["user_id"]} | 头像={"有" if it["avatar"] else "无"}')

if items:
    print("\n=== 订阅第一条 ===")
    t = items[0]
    sub = post(f'{B}/subscriptions', {
        'openid': OPENID, 'platform': t['platform'],
        'platform_user_id': t['user_id'], 'canonical_url': t['canonical_url'],
        'display_name': t['display_name'], 'avatar': t['avatar']})
    print(f'订阅 id={sub["id"]} anchor_id={sub["anchor_id"]}')
    print("\n=== 详情(含头像)===")
    detail = get(f'{B}/anchors/{sub["anchor_id"]}')
    print(f'名称: {detail["display_name"]} | 头像={"有" if detail.get("avatar") else "无"} | 平台数: {len(detail["platforms"])}')

print("\n=== 抖音搜索(预期 501 提示)===")
try:
    items = get(f'{B}/anchors/_search?platform=douyin&keyword={urllib.parse.quote("天蚕土豆")}&limit=3')
    print(f'抖音搜索: {len(items)} 条(意外成功?)')
except urllib.error.HTTPError as e:
    print(f'抖音搜索: HTTP {e.code} → 符合预期(需登录)')
