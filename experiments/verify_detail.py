"""验证详情响应格式化。"""
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://127.0.0.1:8899/api/v1/anchors/83', timeout=15).read().decode())
print('display_name:', d['display_name'])
print('bio:', d.get('bio'))
p = d['platforms'][0]
cs = p.get('current_session')
print('platform:', p['platform'], '| is_live:', p['is_live'])
print('session.title:', cs.get('title'))
print('session.started_at:', cs.get('started_at'))
r = d['recent_sessions'][0]
print('recent.title:', r.get('title'), '| started:', r.get('started_at'), '| ended:', r.get('ended_at'))
