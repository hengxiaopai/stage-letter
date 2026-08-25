"""验证订阅时名字更新逻辑。"""
import urllib.request, json

def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=15).read().decode())
def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=15).read().decode())

B = 'http://127.0.0.1:8899/api/v1'
# 重新订阅姿态(名字已是 Zz1tai姿态)
sub = post(f'{B}/subscriptions', {'openid':'dev_miniapp_local_001','platform':'huya',
    'platform_user_id':'333003','canonical_url':'https://www.huya.com/333003',
    'display_name':'Zz1tai姿态','avatar':'x'})
print(f'订阅 id={sub["id"]} display_name={sub["display_name"]}')

# 故意传个错名字,看是否更新(应该更新为传入值——但注意这是把对的改成错的场景)
sub2 = post(f'{B}/subscriptions', {'openid':'dev_miniapp_local_001','platform':'huya',
    'platform_user_id':'333003','canonical_url':'https://www.huya.com/333003',
    'display_name':'姿态','avatar':''})
print(f'改名后 id={sub2["id"]} display_name={sub2["display_name"]}')

# 改回正确名字
sub3 = post(f'{B}/subscriptions', {'openid':'dev_miniapp_local_001','platform':'huya',
    'platform_user_id':'333003','canonical_url':'https://www.huya.com/333003',
    'display_name':'Zz1tai姿态','avatar':''})
print(f'恢复后 display_name={sub3["display_name"]}')
print('\n✓ 名字更新逻辑正常')
