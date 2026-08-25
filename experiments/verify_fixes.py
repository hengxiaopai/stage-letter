"""验证本轮 7 个问题修复。"""
import urllib.request, urllib.parse, json, time

B = 'http://127.0.0.1:8899/api/v1'
OPENID = 'dev_miniapp_local_001'

def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=15).read().decode())

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())

def delete(url):
    req = urllib.request.Request(url, method='DELETE')
    return urllib.request.urlopen(req, timeout=15)

print("=== 1. 搜索(带 openid,查订阅状态)===")
kw = urllib.parse.quote('德云色')
items = get(f'{B}/anchors/_search?platform=bilibili&keyword={kw}&limit=15&openid={OPENID}')
print(f'  返回 {len(items)} 条 (limit=15 生效: {"OK" if len(items) > 10 else "仅" + str(len(items))})')
for it in items[:3]:
    print(f'  {it["display_name"]} | fans={it["fans"]} | 头像={"有" if it["avatar"] else "无"} | is_existing={it["is_existing"]} | sub_id={it.get("subscription_id")} | is_live={it["is_live"]}')

print("\n=== 2. 订阅(带头像)===")
# 德云色已订阅(anchor 81), 找"老实憨厚的笑笑"(mid=8739477) 重新订阅验证头像
target = next((it for it in items if it['display_name'] == '老实憨厚的笑笑'), None)
if target:
    print(f'  目标: {target["display_name"]} 头像={target["avatar"][:30]}')
    if not target['is_existing']:
        sub = post(f'{B}/subscriptions', {
            'openid': OPENID, 'platform': 'bilibili',
            'platform_user_id': target['user_id'],
            'canonical_url': target['canonical_url'],
            'display_name': target['display_name'],
            'avatar': target['avatar'],
        })
        print(f'  订阅成功 id={sub["id"]} 响应头像={"有" if sub.get("avatar") else "无"}')
    else:
        print(f'  已存在 sub_id={target.get("subscription_id")}')
        # 查 anchor 是否已有头像
        detail = get(f'{B}/anchors/{target["anchor_id"]}')
        print(f'  anchor avatar={"有" if detail.get("avatar") else "无(缺)"}')

print("\n=== 3. 订阅列表(含头像)===")
subs = get(f'{B}/subscriptions?openid={OPENID}')
for s in subs:
    print(f'  {s["display_name"]} | avatar={"有" if s.get("avatar") else "无"} | anchor_id={s["anchor_id"]}')

print("\n=== 4. 取消 → 列表移除 ===")
if subs:
    sid = subs[-1]['id']
    delete(f'{B}/subscriptions/{sid}')
    time.sleep(0.5)
    subs2 = get(f'{B}/subscriptions?openid={OPENID}')
    removed = all(s['id'] != sid for s in subs2)
    print(f'  删除 id={sid} → 列表移除 {"OK" if removed else "FAIL"}')
