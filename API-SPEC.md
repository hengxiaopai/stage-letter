# API-SPEC.md — REST API 规范

## 1. 总则

| 项 | 规范 |
|----|------|
| Base URL | `https://api.stageletter.example.com` |
| 协议 | HTTPS only |
| 鉴权 | `Authorization: Bearer <jwt>`（除 `/auth/*` 与显式白名单） |
| 数据格式 | JSON（请求 + 响应）|
| 时间格式 | ISO 8601 (UTC)，如 `2026-08-01T20:31:00Z` |
| 错误响应 | `{ "error": { "code": "ERR_XXX", "message": "..." } }` |
| 版本 | URL 路径带 `/api/v1/` |
| 限流 | 单用户 60 req/min，单 IP 100 req/min |
| Trace | `X-Request-Id` header（自动生成） |

## 2. 错误码规范

| 类别 | 范围 | 含义 |
|------|------|------|
| 认证 | 40001-40099 | 登录态问题 |
| 资源 | 40401-40499 | 资源不存在 |
| 冲突 | 40901-40999 | 重复/状态冲突 |
| 业务 | 40010-40099 | 业务校验失败 |
| 系统 | 50001-50099 | 服务端异常 |
| 限流 | 42901-42999 | 触发限流 |

统一响应格式：

```json
{
  "error": {
    "code": "ERR_NOT_FOUND",
    "message": "Anchor not found",
    "request_id": "abc123"
  }
}
```

## 3. 认证

### POST /api/v1/auth/wechat-login

微信一键登录。

请求：
```json
{
  "code": "wx_login_code_from_wx.login()",
  "nickname": "张三",
  "avatar": "https://thirdwx.qlogo.cn/..."
}
```

响应（200）：
```json
{
  "user_id": 12345,
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "expires_at": "2026-09-01T00:00:00Z",
  "is_new_user": true
}
```

错误：
- `40001`: code 无效或过期
- `50001`: 服务端异常

### POST /api/v1/auth/refresh-token

刷新 JWT（V2 实现，V1 直接重登）。

### POST /api/v1/auth/logout

退出登录（前端清 token，后端可选失效 token）。

## 4. 主播

### POST /api/v1/anchors/parse

粘贴 URL 解析主播。

请求：
```json
{ "url": "https://v.douyin.com/abc123" }
```

响应（200）：
```json
{
  "platform": "douyin",
  "platform_user_id": "MS4wLjABAAAA...",
  "room_id": "7384567890123456789",
  "display_name": "小杨哥",
  "avatar": "https://p3-sign.douyinpic.com/...",
  "canonical_url": "https://www.douyin.com/user/MS4wLjABAAAA...",
  "is_existing": false
}
```

错误：
- `40010`: 链接格式有误
- `40011`: 平台不支持
- `40012`: 主播不存在
- `42901`: 触发限流

### GET /api/v1/anchors/{anchor_id}

获取主播详情。

Query：
- `openid` (optional): 当前查看者身份。传入后，每个平台账号返回真实关注与提醒偏好；未传时不推断用户状态。

响应（200）：
```json
{
  "id": 1,
  "display_name": "小杨哥",
  "avatar": "https://...",
  "bio": "...",
  "platforms": [
    {
      "platform_account_id": 100,
      "platform": "douyin",
      "platform_user_id": "MS4wLjABAAAA...",
      "canonical_url": "https://www.douyin.com/user/...",
      "is_live": true,
      "last_status": "ONLINE",
      "last_checked_at": "2026-08-01T20:35:00Z",
      "is_following": true,
      "reminder_enabled": true,
      "current_session": {
        "id": 92839,
        "title": "今晚给大家聊聊创业",
        "cover": "https://...",
        "started_at": "2026-08-01T20:31:00Z",
        "viewer_count": 12345
      }
    }
  ],
  "recent_sessions": [
    {
      "id": 92001,
      "started_at": "2026-07-31T19:00:00Z",
      "ended_at": "2026-07-31T22:30:00Z",
      "title": "..."
    }
  ]
}
```

错误：
- `40401`: 主播不存在

### GET /api/v1/anchors/{creator_id}/sessions

读取 Formal Creator 的直播历史。`cursor` 是不透明的稳定 keyset cursor，内部按不可变的
`opened_at + session_id` 分页；它不依赖展示用开播时间。

每个 item 的新增时长字段：

```json
{
  "session_id": "92001",
  "started_at": "2026-07-31T15:58:00Z",
  "ended_at": "2026-07-31T17:02:00Z",
  "started_at_source": "platform",
  "duration_seconds": 3840,
  "duration_basis": "PLATFORM_START_PROBE_END",
  "duration_is_estimated": true
}
```

`duration_basis` is `PLATFORM_START_PROBE_END` only when the start is a trusted
platform timestamp and the end is a probe-confirmed transition;
`PROBE_START_PROBE_END` when both boundaries are probe-derived; and
`UNAVAILABLE` when no confirmed end exists. `duration_is_estimated` remains
`true` for all three cases; the API never claims a provider-authored end time.

### GET /api/v1/anchors/{creator_id}/calendar and /stats

Calendar and statistics evaluate their Beijing (`Asia/Shanghai`) date range by
the effective statistical start: trusted platform `source_started_at` when
`started_at_source=platform`, otherwise immutable `opened_at`. The same session
can therefore display a probe transition after midnight while correctly being
counted in the preceding calendar month. Aggregate duration objects include
`duration_is_estimated: true`; their `basis` is the shared completed-session
basis, `MIXED` for heterogeneous completed samples, or `UNAVAILABLE` if no
session has a confirmed end.

### GET/PATCH /api/v1/creators/{creator_id}/personal-profile

D3 的个人主播档案属于当前用户，持久化 identity 固定为
`(user_id, creator_id)`；请求使用登录态对应的 `openid`，响应不暴露
`user_id`。读取和写入都要求该用户当前至少关注该 Creator 的一个平台账号。

响应明确分层，平台事实与用户私有内容绝不混写：

```json
{
  "platform_facts": {
    "creator_id": "31",
    "display_name": "平台主播昵称",
    "platform_accounts": [{"account_id": "41", "platform": "douyin", "platform_user_id": "..."}]
  },
  "user_owned_profile": {
    "user_alias": "我给他的称呼",
    "note": "只看晚场",
    "group": "电竞",
    "user_tags": ["常看"],
    "reference_schedule": {
      "timezone": "Asia/Shanghai",
      "days_of_week": [1, 5],
      "start_time": "20:00",
      "end_time": "23:00"
    }
  }
}
```

PATCH body contains `openid` and only the supplied profile fields; `null` clears
an optional value. Repeating the same PATCH is idempotent. `reference_schedule`
is user-authored reference data only: it does not change platform LIVE/OFFLINE,
does not create “early/late” facts, and does not enqueue a notification. D1
notification preference remains separately keyed by `(user_id, platform_account_id)`.

When the last follow for a Creator is removed, the D3 row is retained but cannot
be read or changed until that user follows the Creator again. This preserves
private notes without making a historical follow appear active.

## 5. 订阅

### POST /api/v1/subscriptions

创建订阅。

请求：
```json
{ "url": "https://v.douyin.com/abc123" }
```

或显式 anchor_id（V2 启用）：

```json
{ "anchor_id": 1 }
```

响应（201）：
```json
{
  "subscription_id": 5678,
  "anchor_id": 1,
  "platform_account_id": 100,
  "platform": "douyin",
  "created_at": "2026-08-01T20:00:00Z"
}
```

错误：
- `40010`: 链接无效
- `40011`: 平台不支持
- `40901`: 已订阅过（返回已有 subscription_id）
- `42901`: 触发限流

### DELETE /api/v1/subscriptions/{id}

取消订阅。

响应（204）。

错误：
- `40401`: 订阅不存在

### GET /api/v1/notification-preferences/{platform_account_id}

读取当前用户对已关注平台账号的开播提醒偏好。

Query：
- `openid` (required): 当前用户身份。

响应（200）：
```json
{
  "platform_account_id": 100,
  "enabled": true,
  "updated_at": "2026-08-26T12:00:00Z"
}
```

### PATCH /api/v1/notification-preferences/{platform_account_id}

更新开播提醒偏好。写入 Formal `notification_preferences`，并在兼容期同步 Legacy `user_subscriptions.notify_enabled`。

请求：
```json
{
  "openid": "o8pzc4...",
  "enabled": false
}
```

响应同 GET。未关注该平台账号时返回 404，不允许替其他用户修改偏好。

### GET /api/v1/subscriptions

列出我的订阅。

Query：
- `platform` (optional): `douyin` / `bilibili` / ...
- `is_live` (optional): `true` / `false`
- `cursor` (optional): 分页游标
- `limit` (optional, default 20, max 100)

响应（200）：
```json
{
  "items": [
    {
      "subscription_id": 5678,
      "anchor": {
        "id": 1,
        "display_name": "小杨哥",
        "avatar": "https://..."
      },
      "platform": "douyin",
      "is_live": true,
      "notify_enabled": true,
      "is_starred": false,
      "subscribed_at": "2026-08-01T20:00:00Z"
    }
  ],
  "next_cursor": "eyJpZCI6NTY3OH0="
}
```

### PATCH /api/v1/subscriptions/{id}

更新订阅设置。

请求：
```json
{
  "notify_enabled": true,
  "is_starred": false
}
```

响应（200）：
```json
{
  "subscription_id": 5678,
  "notify_enabled": true,
  "is_starred": false,
  "updated_at": "2026-08-01T20:30:00Z"
}
```

错误：
- `40401`: 订阅不存在

## 6. 直播

### GET /api/v1/lives/active

获取我订阅的正在直播的主播。

响应（200）：
```json
{
  "items": [
    {
      "anchor_id": 1,
      "anchor_name": "小杨哥",
      "anchor_avatar": "https://...",
      "platform": "douyin",
      "session": {
        "id": 92839,
        "title": "...",
        "started_at": "2026-08-01T20:31:00Z",
        "viewer_count": 12345,
        "cover": "https://..."
      }
    }
  ]
}
```

### GET /api/v1/lives/recent

最近开播（24h 内）。

Query：
- `limit` (default 50, max 100)

## 7. 通知 (v0.2 grant 模型)

> **v0.2 重大变更**: 端点从 `/credits`、`/refresh` 改为 `/grants`、`/request-grant`。  
> 不再有"初始 8 次 / 季度重置 / refresh +8"。详见 [CHANGELOG.md §v0.2](./CHANGELOG.md) 与 [WECHAT-NOTIFICATION-SPEC.md §2](./WECHAT-NOTIFICATION-SPEC.md)。

### GET /api/v1/notifications/grants

查询我的微信通知 grant。

Query:
- `template_id` (optional, default = 订阅开播提醒模板): 查某个模板的 grant

响应(200):
```json
{
  "template_id": "wx_template_live_start",
  "granted_count": 5,
  "consumed_count": 2,
  "available": 3,
  "last_granted_at": "2026-08-01T20:00:00Z",
  "last_send_at": "2026-08-01T20:30:00Z",
  "last_send_error": null,
  "ledger_drift_detected": false
}
```

> **available = max(0, granted - consumed)**(应用层计算)。若 provider-authoritative
> `consumed_count` 超过本地乐观授权证据，则返回 `ledger_drift_detected=true`，而不是
> 向用户展示负数。
> 注意:`available` 不是配额,是**用户行为产生的余额**。

### POST /api/v1/notifications/request-grant

记录 `wx.requestSubscribeMessage` 的逐模板原始结果。客户端生成 `request_id`；服务端
以 `(user_id, request_id, template_id)` 持久化幂等证据。同一 key 的完全重放不会重复
累计，变更 decision 的重放返回冲突。

请求:
```json
{
  "request_id": "wx-1724140800000-a1b2c3",
  "results": [
    {
      "template_id": "configured-template-id",
      "decision": "accept"
    }
  ]
}
```

> `decision` 只允许微信原始值 `accept | reject | ban`。`accept` 为该模板累计一次本地
> 乐观 grant；`reject/ban` 只留证，不扣减既有 grant。客户端不得直接提交累计数量。

响应(200):
```json
{
  "request_id": "wx-1724140800000-a1b2c3",
  "items": [
    {
      "template_id": "configured-template-id",
      "decision": "accept",
      "recorded": true,
      "granted_count": 6,
      "consumed_count": 2,
      "available": 4
    }
  ],
  "received_at": "2026-08-01T20:30:00Z"
}
```

错误:
- HTTP `409`: 同一幂等 key 携带了不同 decision
- HTTP `422`: 模板未注册、批内模板重复或请求结构非法

> Intake 是客户端回调证据，不是微信 provider 余额查询。发送结果 `errcode=0` 和
> `43101` 等既有 provider-authoritative 结果仍通过原子 finalizer 推进
> `consumed_count`；V1 不声称可主动查询微信余额或实现 exactly-once。

### GET /api/v1/notifications/history

读取正式 `notification_deliveries` 的用户通知历史。只返回具备 formal event/session
上下文的 Gate 1.6+ delivery；不再依赖 legacy `notification_jobs`。

Query：
- `limit`：1–50，默认 20
- `cursor`：上一页返回的 delivery-id keyset cursor；不是 offset

响应（200）：
```json
{
  "items": [
    {
      "id": 1,
      "anchor_id": 1,
      "account_id": 101,
      "display_name": "小杨哥",
      "avatar": "...",
      "platform": "douyin",
      "live_event_id": "live-event:...",
      "live_session_id": 92839,
      "started_at": "2026-08-01T20:31:00Z",
      "ended_at": null,
      "channel": "WECHAT_SUBSCRIBE",
      "state": "SENT",
      "error_code": null,
      "created_at": "2026-08-01T20:31:02Z",
      "sent_at": "2026-08-01T20:32:00Z",
      "miniapp_path": "pages/detail/index?id=1",
      "api_path": "/api/v1/anchors/1"
    }
  ],
  "next_cursor": "1"
}
```

`miniapp_path` 是 Gate 3.4 唯一主播详情路由契约，同一路径也写入微信订阅消息的
`page` 字段。小程序内部导航时在其前面补 `/`。微信 accepted、设备收到、用户点击和
详情页读取仍是四种不同证据，本接口不声称用户已读。

### GET /api/v1/notifications/inbox

站内消息列表（unread 优先）。

## 8. Admin

> 内部接口，IP 白名单 + admin token 双因子。

### GET /api/v1/admin/platforms/health

平台健康度。

响应（200）：
```json
[
  {
    "platform": "douyin",
    "state": "HEALTHY",
    "success_rate_24h": 98.1,
    "avg_latency_ms_24h": 230,
    "consecutive_failures": 0,
    "last_success_at": "2026-08-01T20:35:00Z",
    "last_failure_at": "2026-08-01T15:00:00Z"
  },
  {
    "platform": "bilibili",
    "state": "DEGRADED",
    "success_rate_24h": 72.3,
    "avg_latency_ms_24h": 450,
    "consecutive_failures": 8,
    "last_success_at": "2026-08-01T20:30:00Z"
  }
]
```

### POST /api/v1/admin/platforms/{platform}/disable

禁用平台。

响应（200）：
```json
{ "platform": "douyin", "state": "DISABLED" }
```

### POST /api/v1/admin/platforms/{platform}/enable

启用平台。

### GET /api/v1/admin/users

用户列表(分页)。

Query:
- `cursor` / `limit`
- `keyword` (optional): 搜 nickname / masked_openid

> **v0.2 修正**: openid 默认 mask,如 `o***********abc`。  
> 仅在用户主动点"查看完整 openid"并输入 admin 二次密码时返回完整值。

### GET /api/v1/admin/users/{user_id}

用户详情。

> openid 字段同上,默认 mask。

### POST /api/v1/admin/wechat-templates/{template_id}/disable

禁用某个微信模板(因 40037 错误等)。

> **v0.2 新增**: 微信模板独立管理。  
> **不要** 通过 `POST /api/v1/admin/platforms/{platform}/disable` 禁用平台来"间接"处理微信模板错误。

### GET /api/v1/admin/notifications

全局通知查询。

### GET /api/v1/admin/errors/recent

最近错误日志。

## 9. 内部接口

### POST /api/v1/internal/twitch/webhook

Twitch EventSub webhook 接收点。

> 公开 endpoint，但通过 signature 验证来源。

## 10. 分页规范

所有列表接口统一：

- 请求：`cursor`（不透明字符串，从上一次响应的 `next_cursor` 取）+ `limit`
- 响应：`items` + `next_cursor`（无下一页时为 `null`）

避免 offset-based pagination（性能差 + 不稳定）。

## 11. 版本与兼容

- 任何 breaking change 必须升 v2
- 同一 v1 内只允许 additive change（新 optional field）
- Deprecation 走 `Sunset` header，告知客户端至少 3 个月后移除
