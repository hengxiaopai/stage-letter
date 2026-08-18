# SECURITY.md — 安全考虑

## 1. 认证与授权

### 1.1 微信登录

- **code 一次性**：5 分钟内必须用 `code2Session` 接口换 `openid` / `session_key`
- `code` 永远不下发到前端之外的地方
- `session_key` 永远不下发到客户端
- 拿到 `unionid` 后必须用 `unionid` 关联同一用户多端，**不能只用 openid**

```python
# 后端示例
async def wechat_login(code: str):
    resp = await http.get(
        "https://api.weixin.qq.com/sns/jscode2session",
        params={
            "appid": settings.WX_APPID,
            "secret": settings.WX_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        },
    )
    data = resp.json()
    if "openid" not in data:
        raise WxLoginError(data.get("errmsg"))
    return data  # { openid, unionid?, session_key, ... }
```

### 1.2 JWT

| 项 | 规范 |
|----|------|
| 算法 | HS256（V1）/ RS256（V2）|
| Payload | `user_id`, `iat`, `exp` |
| 有效期 | 30 天 |
| 签名密钥 | KMS 托管（V1 简化：env var）|
| 撤销 | V1 不支持；V2 加黑名单 |

### 1.3 Refresh Token

- V1 不做
- 30 天到期 → 用户重新微信登录

## 2. 通信安全

| 项 | 规范 |
|----|------|
| 协议 | 全站 HTTPS（TLS 1.2+） |
| HSTS | `max-age=31536000; includeSubDomains` |
| 证书 | Let's Encrypt / 阿里云免费证书，自动续期 |
| 源站 IP | 不暴露，CDN 代理 |
| CORS | 小程序不需要 CORS；Admin 仅允许内网域名 |

## 3. 数据保护

### 3.1 敏感字段 (v0.2 明确决策)

| 字段 | 保护 |
|------|------|
| `users.openid` | **V1 明文存储**(DB 内可见),V2 升级 AES-256-GCM + KMS |
| `users.unionid` | 同上 |
| `session_key` | 服务端内存,**不落库** |
| 通知内容 | 含主播 ID + 平台,无个人隐私,正常 |

> **v0.2 决策**: 不再"V1 简化:明文;V2 AES+KMS"两套并存。**统一为 V1 明文 / V2 KMS**。  
> V1 阶段明文存储是因为:数据规模小(预计 1 万用户)、访问只在 DB 内部、运维需要直接可见;加密后调试复杂度上升。  
> 接受明文风险:V1 内 DB 访问权限等同于敏感数据访问权限,严格限制 DB user。

### 3.2 数据生命周期

| 数据 | 保留期 |
|------|--------|
| `users` | 账号存活期 |
| `user_subscriptions` | 用户取消订阅后保留 90 天，再清理 |
| `live_sessions` | 永久（append-only，partition by month） |
| `live_events` | 永久 |
| `notification_deliveries` | 90 天后归档 cold storage |
| `probe_runs` | 30 天 |

### 3.3 用户数据导出/删除（V2 必备）

V1 不做，V2 必做：
- 导出：用户可下载自己所有数据
- 删除：用户注销后 30 天内物理删除

## 4. 速率限制

### 4.1 维度

| 维度 | 限制 | 实现 |
|------|------|------|
| 单 IP | 100 req/min | Redis 计数器 |
| 单用户 | 60 req/min | Redis 计数器 |
| 登录 | 10 次 / 小时 | Redis 计数器 |
| 订阅创建 | 30 次 / 小时 | Redis 计数器 |
| 通知 refresh | 5 次 / 小时 | Redis 计数器 |

### 4.2 实现

用 `slowapi` 或自己包一个 `RateLimiter`：

```python
class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check(self, key: str, limit: int, window: int):
        """滑动窗口限流。"""
        now = time.time()
        key = f"rl:{key}:{int(now // window)}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, window)
        return count <= limit
```

## 5. 反爬与风控

### 5.1 我们是爬虫场景

- 单平台探测 QPS 严格控制（见 [PLATFORM-ADAPTER-SPEC.md §8.1](./PLATFORM-ADAPTER-SPEC.md)）
- 请求带真实 UA / Referer
- 失败后冷却（指数退避）
- **不存用户 Cookie**：绝不接触用户登录态

### 5.2 我们的反爬

防被恶意用户薅羊毛：

| 场景 | 检测 | 应对 |
|------|------|------|
| 短时间大量订阅 | 单 user 1h > 50 | 二次校验 / 临时封禁 |
| 短时间大量 refresh | 单 user 1h > 5 | 拒绝 refresh |
| 异常登录 | 异地、多端并发 | 告警 + 强制重登 |
| 异常通知 | 单 user 1h > 20 次发送 | 自动暂停 + 人工 review |

### 5.3 IP 池（V2）

- V1 用云厂商 NAT
- V2 引入代理池（每平台独立 IP 段）
- 真实用户与爬虫 IP 严格隔离

## 6. 注入防护

| 类型 | 防护 |
|------|------|
| SQL | SQLAlchemy 参数化（不拼字符串） |
| XSS | 前端不渲染用户输入的 HTML；JSON 自动转义 |
| SSRF | URL 解析器拒绝内网 IP；主播 URL 必须含平台域名白名单 |
| CSRF | 小程序 + JWT，无 cookie，天然免疫 |
| 命令注入 | 平台 URL 解析器只做字符串操作，不调 shell |
| 文件上传 | V1 不接受文件上传 |

### 6.1 URL 解析防 SSRF

```python
ALLOWED_DOMAINS = {
    'douyin.com', 'v.douyin.com',
    'bilibili.com', 'live.bilibili.com', 'b23.tv', 'space.bilibili.com',
    'huya.com',
    'douyu.com',
    'twitch.tv',
}

def parse_anchor_url(url: str):
    parsed = urlparse(url)
    if parsed.netloc not in ALLOWED_DOMAINS:
        raise BadURL("Unsupported platform")
    # ... 解析 platform_user_id
```

## 7. 微信生态特殊

### 7.1 AppSecret 保护

- 不下发给前端
- 存服务端 env var
- 定期轮换（每 90 天）

### 7.2 access_token 缓存

- 服务端缓存 `access_token`（2 小时有效）
- Redis 存，全局唯一
- 失效时统一刷新

### 7.3 微信回调签名验证

Twitch 等 webhook 必须验签：

```python
def verify_twitch_signature(request: Request):
    msg_id = request.headers['Twitch-Eventsub-Message-Id']
    msg_ts = request.headers['Twitch-Eventsub-Message-Timestamp']
    msg_sig = request.headers['Twitch-Eventsub-Message-Signature']
    body = await request.body()
    expected = hmac_sha256(SECRET, msg_id + msg_ts + body)
    if not hmac.compare_digest(msg_sig, expected):
        raise HTTPException(403)
```

## 8. 内部权限

### 8.1 Admin API

- 单独路由前缀 `/api/v1/admin/*`
- 中间件检查:
  - 客户端 IP 在内网白名单
  - `X-Admin-Token` 有效
- V2:完整 RBAC(admin / operator / viewer 三角色)
- **v0.2 新增**:Admin 响应中**默认 mask** 敏感字段(openid / unionid / 手机号等)
  - 默认响应:`openid: "o***********abc"`
  - 想看完整 openid:必须二次验证(短时效 token 或 admin 二次密码)
  - 完整查看操作必须写入 `audit_logs`
- **v0.2 新增**:`wechat-templates` 子路由有独立 disable 能力,**禁止** 通过 disable 平台 adapter 来"间接"处理微信模板错误

### 8.2 数据库权限

- API Server 用独立 DB user，只有 DML 权限
- Migration 用独立 user，有 DDL 权限
- Worker 用独立 user，限制表访问

## 9. 监控告警

### 9.1 安全相关告警

- 异常登录（异地、并发）
- 异常订阅（短时间大量）
- 异常 refresh（短时间大量）
- 微信 4xx 错误率突增
- Admin 越权访问

### 9.2 审计日志

```sql
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    actor       VARCHAR(64),  -- user_id / admin / system
    action      VARCHAR(64),  -- 'disable_platform' / 'refresh_credit' / ...
    target      VARCHAR(64),  -- 目标 ID
    payload     JSONB,
    ip          INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- Admin 所有写操作必须留 audit log
- 90 天保留

## 10. 合规

### 10.1 必备

- 隐私政策（小程序必须展示）
- 用户协议（注册时勾选）
- 平台内容免责声明

### 10.2 注意事项

- 不存主播原视频（合规风险）
- 不展示主播联系方式
- 不允许用户上传个人数据（V1 不接文件上传）

## 11. 依赖安全

- `pip-audit` / `safety` 定期扫描
- Dependabot 自动 PR
- 关键依赖 pin 版本

## 12. 备份与恢复

| 数据 | 备份策略 | RPO | RTO |
|------|---------|-----|-----|
| PostgreSQL | 每日 pg_dump + WAL 归档 | 5min | 1h |
| Redis | 开启 AOF | 1min | 10min |
| 配置 | Git 仓库 | 0 | 5min |
