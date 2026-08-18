# PRD.md — V1 产品需求

> **v0.2 重大变更**: §F5 通知模型完全重写 / §N1 SLA 按平台分级 / 验收标准更新。详见 [CHANGELOG.md](./CHANGELOG.md)。

## 范围

V1 = 「开场信」基础版,仅服务 C 端用户。

包含:
- 微信小程序客户端(4 个核心页面)
- 后端 API + 检测引擎 + 通知引擎
- 后台 Admin(最小可用)

不包含:
- 跨平台身份合并(同一主播抖音+ B 站合并到一条 anchor)
- 海外 App
- 付费会员
- 多端

## 用户角色

V1 只有两种角色:

| 角色 | 描述 | V1 入口 |
|------|------|---------|
| 普通用户 | 注册即用,订阅主播、接收通知 | 微信小程序 |
| 管理员 | 平台健康监控、手动 disable | Admin Web(内部)|

不做客服、运营、版主等角色。

---

## 核心功能

### F1. 账号与登录

**F1.1 微信一键登录**
- 首次进入小程序 → 调 `wx.login` → 拿 code
- 服务端用 code 换 openid / unionid / session_key
- 生成 user_id,签发 JWT(30 天有效)
- session_key 不下发客户端

**F1.2 用户最小画像**
- openid / unionid(V1 明文存储,V2 KMS)
- nickname / avatar(用户首次授权时获取)
- 注册时间
- 通知 grant(详见 F5)

**F1.3 退出登录**
- 仅清除本地 token,不删除账号。

### F2. 添加订阅

**F2.1 粘贴链接添加**

用户路径:首页 → 「添加主播」→ 输入框粘贴 URL → 点「解析」。

- 客户端做轻量校验(必须包含已知平台域名)
- POST `/api/v1/anchors/parse` → 返回 anchor 候选信息
- UI 展示主播卡片(头像、昵称、平台)
- 用户点「添加订阅」→ POST `/api/v1/subscriptions`

**F2.2 必须支持的 URL 形式(V1 P0)**

| 平台 | URL 示例 |
|------|---------|
| 抖音 | `https://v.douyin.com/xxx`<br>`https://www.douyin.com/user/xxx` |
| B 站 | `https://space.bilibili.com/xxx`<br>`https://live.bilibili.com/xxx` |
| 虎牙 | `https://www.huya.com/xxx` |
| 斗鱼 | `https://www.douyu.com/xxx` |
| Twitch | `https://www.twitch.tv/xxx` |

**F2.3 重复订阅**
- 同一 user 对同一 platform_account 重复订阅 → 409 + 已有 subscription_id
- UI 提示「已订阅过」

**F2.4 解析失败**
- 链接无效 / 格式错误 → 「链接格式有误,请检查」
- 平台不支持 → 「该平台暂未支持,敬请期待」
- 主播不存在(404)→ 「找不到该主播」

**F2.5 V2 才做**
- 平台内搜索主播
- 批量导入关注列表
- 扫码添加

### F3. 我的订阅

**F3.1 列表**

两种视图:
- 全部(按"最近开播时间"排序)
- 按平台分组

**F3.2 订阅操作**

| 操作 | 行为 |
|------|------|
| 取消订阅 | DELETE |
| 通知开关 | PATCH notify_enabled(默认 ON)|
| 特别关注 | PATCH is_starred(V1 仅标记,不做差异化通知)|
| 静默 | V1 不做 UI(V2 加)|

**F3.3 主播详情**

- 头像、昵称、平台、canonical_url
- 直播状态(实时:OFFLINE / ONLINE / SUSPECT)
- 当前 LiveSession(若在直播:标题、封面、观看人数、开始时间)
- 历史 LiveSessions(最近 10 次)

### F4. 直播动态

**F4.1 首页 - 正在直播**

- Tab 1:「正在直播」 → 当前用户所有订阅中正在直播的主播列表
- Tab 2:「最近开播」 → 最近 24h 开过播的主播

**F4.2 通知记录(V1 必须)**

- 列出我收到过的开播通知
- 字段:主播、平台、开播时间、送达状态、送达渠道
- 未送达原因(如 grant 用尽 → 显示「微信提醒已用完,已转站内消息」)

### F5. 通知 grant 与触达 (v0.2 重写)

> **核心变更**: v0.1 的"通知额度(8 / 季度重置 / refresh +8)"是错的。  
> v0.2 改为"微信订阅 grant(用户主动 accept 产生)"。  
> 详见 [WECHAT-NOTIFICATION-SPEC.md](./WECHAT-NOTIFICATION-SPEC.md) 与 ADR-001。
>
> **✅ v0.2.2(Gate 0A 实测 2026-08-12)**:grant **可累积储备**(连续授权 N 次 = N 条额度)。V1 增加"授权储备"交互(关注主播时一次授权 3-5 次,后续开播免打扰推送)。详见 ADR-002。

#### F5.1 grant 规则

| 项 | 规则 |
|----|------|
| 初始 grant | **0**(不是 8)|
| grant 来源 | **用户每次主动调** `wx.requestSubscribeMessage` 且 accept |
| 每次 grant 增量 | **+1**(每次 accept;**可累积储备**,ADR-002)|
| 真实 send 消耗 | **+1** consumed |
| 无 grant 时 | 自动转站内消息 |
| 无季度重置 | 不存在该机制 |

#### F5.2 grant 请求流程

1. 用户点「开启开播提醒」按钮
2. 小程序调 `wx.requestSubscribeMessage({ tmplIds: [...] })`
3. 用户同意 → 客户端收到 accept
4. 客户端调 `POST /api/v1/notifications/request-grant`
5. 服务端:`wechat_subscription_grants.granted_count += 1`
6. 返回新额度

#### F5.3 触达决策树(v0.2)

```
主播开播事件
   ↓
Notification Service: 查 subscribers
   ↓
对每个 user:
   ├─ notify_enabled = false → 跳过
   ├─ available_grant > 0 → 尝试 wechat
   │   ├─ 成功 → consumed + 1
   │   ├─ 4xx(用户拒收/模板错误) → 记录 grant 失效
   │   └─ 5xx / 网络 → 重试,grant 保留
   └─ available_grant = 0 → 站内消息(reason='no_grant')
   ↓
DB UNIQUE (user_id, live_session_id, channel) 保证不重复
```

#### F5.4 与订阅绑定的 UX

把 grant 请求与订阅创建合并:

```
用户添加订阅 → 弹窗"是否同时开启开播提醒?"
   ↓
用户同意 → 同时记录 subscription + grant
   ↓
完成
```

#### F5.5 通知点击行为

- 用户点微信通知
- 跳到 `pages/anchor/detail?id={anchor_id}&session_id={session_id}`
- 详情页显示「前往观看」按钮
- 点击按钮 → 走 `PlatformDeepLinkAdapter`(不同平台不同跳转策略)

### F6. 平台支持

V1 P0(必须):
- 抖音
- B 站
- 虎牙
- 斗鱼

V1 P1(理想):
- 快手
- Twitch

V1 P2(不强求):
- YouTube
- 小红书

**进入正式开发前必须通过 Gate 0 验证 P0 4 个平台**。

### F7. Admin 后台(V1 最小可用)

Web Admin(内部使用,不开放公网),至少包含:

| 模块 | 功能 |
|------|------|
| 平台健康 | 平台列表 + 状态 + 24h 成功率 + 平均延迟 + sustained_qps + max_anchors |
| 适配器开关 | 手动 disable / enable 平台 |
| 用户列表 | 查 user、订阅数、grant 余额(**openid 默认 mask**)|
| 通知记录 | 全局查投递结果 |
| 错误日志 | 平台/worker 错误聚合 |
| 微信模板管理 | 模板 enable / disable(出错时手动 disable)|

> v0.2 新增:微信模板管理(因为 40037 不再 disable 平台,需要独立管理)。

不做:用户管理、权限系统、订单/支付、数据分析。

---

## 非功能需求

### N1. SLA(v0.2 按平台分级)

> **v0.2 修正**: v0.1 的"<3min p95 统一 SLA"在数学上不可能。  
> SLA 是 **provisional**,Gate 0C/D 完成后定稿。

| 平台 | 检测方式 | SLA p95 |
|------|---------|---------|
| **Twitch** | EventSub webhook | **< 30s** |
| **B 站** | API 轮询 | **< 5min** |
| **虎牙** | API 轮询 | **< 5min** |
| **斗鱼** | API 轮询 | **< 5min** |
| **抖音** | 网页/接口 | **< 8min**(或降低 V1 主播上限)|

**计算依据**(WARM 5min):
```
worst_case_latency = polling_interval + suspect_confirm + send
                   = 5 min          + 30 sec         + 2 sec
                   ≈ 5.5 min
```

### N2. 性能

| 指标 | 目标 |
|------|------|
| 列表页响应 | < 500ms (p95) |
| 添加订阅响应 | < 2s (p95) |
| Admin 页面响应 | < 1s (p95) |

### N3. 可用性

- 单平台故障不影响其他平台
- 适配器可独立 disable
- 主进程重启 → 30s 内恢复检测

### N4. 容量(v0.2 改为按平台倒推)

> **v0.2 修正**: v0.1 的"18,000 主播"假设与 Adapter QPS 矛盾。  
> V1 真实容量 = Σ 各平台 max_anchors,由 Gate 0C 实测。

| 平台 | sustained_qps(预估)| polling_interval | max_anchors(预估)|
|------|---------------------|------------------|-------------------|
| 抖音 | 1 req/s | 5min | **300** |
| B 站 | 2 req/s | 5min | **600** |
| 虎牙 | 2 req/s | 5min | **600** |
| 斗鱼 | 2 req/s | 5min | **600** |
| Twitch | EventSub | - | **∞**(基本无限)|
| **合计** | | | **~2,100**(远低于 v0.1 的 18,000)|

> **关键决策点**: Gate 0C 必须验证每平台 sustained_qps。  
> 若 B 站 / 虎牙 / 斗鱼有 batch endpoint,容量会显著放大。  
> 若抖音 1 req/s 实测做不到,可能需要降级到 P1 平台。

### N5. 安全

- 仅微信登录,不开放邮箱/手机号注册
- 所有 API 鉴权(除显式白名单)
- 速率限制:单用户 60 req/min,单 IP 100 req/min
- **V1 openid/unionid 明文存储;V2 KMS 加密**
- 详细见 [SECURITY.md](./SECURITY.md)

### N6. 观测

- 关键指标埋点(见 [ARCHITECTURE.md §9](./ARCHITECTURE.md))
- 结构化 JSON 日志
- 错误聚合上报

---

## 验收标准(V1 上线前)

产品:
- [ ] 微信登录可用
- [ ] 可添加 4 个 P0 平台订阅
- [ ] 主播开播按平台 SLA 收到微信通知(Twitch < 30s,其他 < 5/8min)
- [ ] 用户 grant 正确记录,转站内消息时机正确
- [ ] 不会重复通知同一 LiveSession
- [ ] 通知点击能跳到对应主播详情页

工程:
- [ ] 单平台 disable 不波及其他平台
- [ ] 状态机二次确认生效(人为注入抖动不重复通知)
- [ ] 单平台故障进入 DEGRADED 仍可通知,标记低 confidence
- [ ] 微信 40037 触发后 disable 模板而非平台
- [ ] Admin 平台健康页可用
- [ ] Admin openid 默认 mask
- [ ] 限流、重试、熔断在测试场景中生效

合规:
- [ ] 隐私政策上线
- [ ] 用户协议上线
- [ ] 微信小程序审核通过

---

## 显式延期(不做)

- 主播搜索(V2)
- 跨平台身份合并(V2)
- 海外平台(V3)
- 通知静默时间段(V2)
- 主播动态 / 新视频(V2)
- 直播预约(V3)
- 付费会员(暂不规划)
- 跨主播聚合推送(暂不规划)