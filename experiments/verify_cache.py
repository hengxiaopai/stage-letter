"""验证搜索缓存 + 全链路。"""
import urllib.request, urllib.parse, json, time

B = 'http://127.0.0.1:8899/api/v1'
def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=15).read().decode())

kw = urllib.parse.quote('德云色')
url = f'{B}/anchors/_search?platform=bilibili&keyword={kw}&limit=15&openid=dev_miniapp_local_001'

t0 = time.time()
items = get(url)
t1 = time.time()
print(f'第1次(上游): {len(items)} 条, {int((t1-t0)*1000)}ms')

t2 = time.time()
items2 = get(url)
t3 = time.time()
print(f'第2次(缓存): {len(items2)} 条, {int((t3-t2)*1000)}ms')

if items:
    it = items[0]
    print(f'第一条: {it["display_name"]} | fans={it["fans"]} | 头像={"有" if it["avatar"] else "无"} | is_live={it["is_live"]} | sub_id={it.get("subscription_id")}')
    # 验证详情页头像链路: 订阅带头像
    def post(url, data):
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
        return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    sub = post(f'{B}/subscriptions', {
        'openid':'dev_miniapp_local_001','platform':'bilibili',
        'platform_user_id':it['user_id'],'canonical_url':it['canonical_url'],
        'display_name':it['display_name'],'avatar':it['avatar']})
    print(f'订阅: id={sub["id"]} avatar={"有" if sub.get("avatar") else "无"}')
    subs = get(f'{B}/subscriptions?openid=dev_miniapp_local_001')
    print(f'列表: {[(s["display_name"], "有头像" if s.get("avatar") else "无头像") for s in subs]}')
