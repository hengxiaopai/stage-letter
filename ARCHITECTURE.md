# ARCHITECTURE.md — 系统架构

> **v0.2 变更**: §4.5 季度重置删除 / 新增 §5.4 分级轮询 / 新增 §6 SLA 分级 / §9 决策记录加 ADR-001。详见 [CHANGELOG.md](./CHANGELOG.md)。
>
> **v0.2.2 变更(2026-08-12,Gate 0A 实测)**: §11 决策记录 ADR-001 增补 ADR-002(grant 可累积储备,授权储备交互)。详见 [CHANGELOG.md](./CHANGELOG.md) 与 [WECHAT-NOTIFICATION-SPEC.md §11](./WECHAT-NOTIFICATION-SPEC.md)。

## 1. 设计原则

1. **多租户优先**:所有数据模型围绕 User/Anchor/Subscription 而非单机配置。
2. **去重检测**:100,000 订阅 → 18,000 主播(去重)→ 18,000 次检测,绝不按订阅数线性调度。
3. **平台隔离**:适配器彼此独立,任意平台故障不影响其他平台。
4. **状态机而非布尔**:避免抖动重复通知。
5. **事件可重放**:所有 LiveEvent 落库,支持事后补偿。
6. **微信通知是有限资源**:**v0.2 修正**——不是配额,是用户行为产生的 grant。详见 [WECHAT-NOTIFICATION-SPEC.md §2](./WECHAT-NOTIFICATION-SPEC.md)。
7. **可降级**:每个平台都可手动 disable,每个用户都可关闭通知,每个通知都可转站内。
8. **分级轮询** (v0.2 新增):不同订阅密度的主播用不同频率轮询,优化总承载量。

## 2. 总体架构

```
┌─────────────────────────────────────────────────────┐
│                微信小程序 (Client)                   │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐  │
│  │ 首页  │ │ 添加  │ │ 订阅  │ │ 我的  │ │ 通知记录  │  │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └────┬─────┘  │
└─────┼────────┼────────┼────────┼──────────┼────────┘
      │ HTTPS  │        │        │          │
      ▼        ▼        ▼        ▼          ▼
┌─────────────────────────────────────────────────────┐
│                 API Gateway (FastAPI)               │
│  /api/v1/auth /api/v1/anchors /api/v1/subscriptions│
│  /api/v1/notifications /api/v1/admin                │
└──────┬────────────────┬────────────────┬────────────┘
       │                │                │
       ▼                ▼                ▼
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│  User    │    │ Subscription │    │   Anchor     │
│ Service  │    │   Service    │    │   Service    │
└────┬─────┘    └──────┬───────┘    └──────┬───────┘
     │                 │                   │
     └────────┬────────┴───────────────────┘
              ▼
       ┌──────────────┐
       │ PostgreSQL   │
       └──────────────┘

   ══════════ Live Detection Layer ══════════

              Scheduler (APScheduler)
                  │
                  ▼
         Redis Queue (probe-jobs)
                  │
   ┌──────────┬───┴────┬──────────┬──────────┐
   ▼          ▼        ▼          ▼          ▼
Douyin    Bilibili   Huya      Douyu     Twitch
Adapter   Adapter    Adapter   Adapter   Adapter
(B 类)    (B 类)     (B 类)    (B 类)    (A 类: EventSub)
   │          │        │          │          │
   └──────────┴────┬───┴──────────┴──────────┘
                  ▼
           Live Snapshot
                  │
                  ▼
         Live State Engine
                  │
            state change?
            /          \
          No            Yes
          │              │
          ▼              ▼
        丢弃       LiveSession + LiveEvent
                          │
                          ▼
                  Notification Fanout
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
         WeChat (grant) In-App   (future: Bark/TG)
              │
              ▼
                  Delivery Log
```

## 3. 服务拆分

### 3.1 API Server

- 框架:FastAPI
- 职责:用户端 REST API + Admin API
- 无状态,可水平扩展
- 与 Worker 通过数据库/Redis 通信

### 3.2 Probe Worker

- 框架:Dramatiq(任务执行)
- 职责:周期性调度平台检测任务
- 部署:每个平台可独立 worker
  ```
  worker-douyin
  worker-bilibili
  worker-huya
  worker-douyu
  worker-twitch       # A 类,主要消费 webhook
  worker-scheduler    # APScheduler 调度
  ```

### 3.3 Notification Worker

- 框架:Dramatiq
- 职责:消费 LiveEvent → fan-out → 投递
- 失败重试、退避

### 3.4 拆分依据

- API Server 是用户触达路径,**必须快速响应**(不能因检测阻塞)
- Probe Worker 是后台任务,**可以慢、可以堆积**
- Notification Worker 是关键时刻,**必须可重试、可降级**
- 独立部署、独立扩容、独立故障

## 4. 技术选型

### 4.1 微信端:Taro 3+ React + TypeScript

> **v0.2 决策**: Taro 3 / 4 推迟到 Gate 4 再定。详见 [CHANGELOG.md](./CHANGELOG.md)。

**候选**:
- Taro 3 + React:多端潜力 + 招人容易(京东出品)
- 微信原生 TypeScript:性能稍好,但绑死微信

**Gate 0 不决策**。先确认检测层稳定再做最终选择。

### 4.2 服务端:Python 3.13 + FastAPI

**理由**:
- Python 生态对直播平台解析最成熟
- DouyinLiveRecorder / WebMoniter / aio-dynamic-push 都是 Python
- 后续 AI/数据分析也能用
- FastAPI 性能足够(V1 阶段 1 万用户)
- 类型注解 + 自动 OpenAPI 文档

**不用 NestJS 的理由**:双技术栈增加维护成本,V1 没必要。

### 4.3 数据库:PostgreSQL 15+

**理由**:关系数据强 / JSONB / 部分 UNIQUE 索引支持 WHERE / 云厂商支持好。

### 4.4 队列 / 缓存:Redis + Dramatiq

**理由**:Redis 同时担任 cache + queue,Dramatiq 比 Celery 更轻量、API 更现代。

### 4.5 任务调度:APScheduler

- 单实例 + Redis 分布式锁
- 避免多实例重复调度
- 简单稳定

## 5. 数据流

### 5.1 添加订阅

```
User → POST /api/v1/subscriptions { url }
   ↓
API Server: Anchor Service 解析 URL
   ↓
查 anchors / platform_accounts
   ↓
若 anchor 不存在:创建 anchor + platform_account
   ↓
创建 user_subscription
   ↓
返回 subscription
```

### 5.2 开播检测(v0.2 引入分级轮询)

```
Scheduler (按 tier 分桶调度)
   ↓
   ├─ HOT 主播: 30s 一次
   ├─ WARM 主播: 5min 一次
   └─ COLD 主播: 30min 一次
   ↓
从 platform_accounts 选出 due anchors(按 polling_tier + last_checked_at)
   ↓
按平台分桶,推到 Redis queue
   ↓
worker-{platform}
   ↓
调用 adapter.get_live_snapshot(pa)
   ↓
对比 last_status
   ↓
状态变化?→ 写 LiveSession + LiveEvent → 推 notify queue
   ↓
无变化?→ 仅更新 last_checked_at
   ↓
worker-notify: fan-out → 写 notification_jobs
   ↓
投递到 WeChat / In-App
   ↓
写 notification_deliveries
```

### 5.3 状态机

```
            ┌──────────┐
            │ OFFLINE  │
            └────┬─────┘
                 │ 探测到 status=online
                 ▼
        ┌──────────────────┐
        │ SUSPECT_ONLINE   │  ← 30s 后二次确认
        └────┬─────────────┘
             │ 再次确认 online
             ▼
        ┌──────────┐         产生 LiveEvent(CONFIRMED_ONLINE)
        │  ONLINE  │ ─────── 产生 LiveSession(OPEN)
        └────┬─────┘
             │ 探测到 status=offline
             ▼
        ┌───────────────────┐
        │ SUSPECT_OFFLINE   │  ← 60s 后二次确认
        └────┬──────────────┘
             │ 再次确认 offline
             ▼
        ┌──────────┐         产生 LiveEvent(CONFIRMED_OFFLINE)
        │ OFFLINE  │ ─────── 关闭 LiveSession
        └──────────┘
```

**关键不变量**:
- 只在 OFFLINE → ONLINE 时产生一次"开播事件"
- 同一 LiveSession 内不会重复产生"开播事件"
- 抖动窗口内的反复切换不会触发通知

**二次确认时长**(可配置):
- ONLINE 确认:30s
- OFFLINE 确认:60s(容忍主播短暂断流)

**Twitch EventSub 特殊**:官方事件可信度高,可以跳过 SUSPECT 直接 ONLINE。

### 5.4 分级轮询(v0.2 新增)

| Tier | 检测频率 | 调度逻辑 | 适用 |
|------|---------|---------|------|
| **HOT** | 30s | 高优先级队列 | 订阅数 > 100 / 刚开播 5min 内 |
| **WARM** | 5min | 默认 | 订阅数 1-99 的常规主播 |
| **COLD** | 30min | 低优先级队列 | 连续 7 天 OFFLINE |

**Tier 动态调整**(由 worker 触发):

```python
async def adjust_tier(platform_account):
    subscriptions_count = await count_subscriptions(platform_account.anchor_id)
    
    if subscriptions_count >= 100:
        platform_account.polling_tier = 'hot'
    elif platform_account.last_live_started_at:
        last_live = platform_account.last_live_started_at
        if now() - last_live > timedelta(days=7):
            platform_account.polling_tier = 'cold'  # 长期没开播,降频
        else:
            platform_account.polling_tier = 'warm'
    else:
        platform_account.polling_tier = 'warm'
    
    await platform_account.save()
```

**容量放大效应**:

```
COLD 30min: 1 req/30min = 0.00056 req/s
WARM 5min:  1 req/5min  = 0.0033 req/s
HOT  30s:   1 req/30s   = 0.033 req/s

对于 sustained_qps=1 的平台:
  假设 80% WARM + 15% COLD + 5% HOT
  avg_qps = 0.8 × 0.0033 + 0.15 × 0.00056 + 0.05 × 0.033
         = 0.00264 + 0.000084 + 0.00165
         = 0.0044 req/s
  
  → 1 / 0.0044 ≈ 227 max_anchors
```

> **分级轮询可显著放大容量**,但具体数字依赖主播分布,需 Gate 0C 实测。

## 6. SLA 分级(v0.2 新增)

> **v0.2 修正**: v0.1 的"<3min p95 统一 SLA"在数学上不可能(5min 轮询 + 30s 二次确认 = 5.5min+)。  
> v0.2 改为按平台分级,SLA 是 **provisional**,Gate 0C/D 完成后定稿。

| 平台 | 检测方式 | SLA p95 | 备注 |
|------|---------|---------|------|
| **Twitch** | EventSub webhook | **< 30s** | 官方事件,可信,几乎实时 |
| **B 站** | API 轮询(假设 2 req/s + WARM 5min) | **< 5min** | 待 Gate 0C 验证 |
| **虎牙** | API 轮询 | **< 5min** | 待 Gate 0C 验证 |
| **斗鱼** | API 轮询 | **< 5min** | 待 Gate 0C 验证 |
| **抖音** | 网页/接口轮询 | **< 8min** | 受限最多,可能要降主播数或加 COLD 比例 |

**SLA 公式**(估算):

```
worst_case_latency = polling_interval + suspect_confirm_window + send_latency
                   ≈ 5 min          + 30 sec                  + 2 sec
                   ≈ 5.5 min
```

> 主播开播 → 通知送达,理论下界就是 5.5min(以 WARM 为例)。

## 7. 通知流(v0.2 重写 grant 模型)

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

详见 [WECHAT-NOTIFICATION-SPEC.md §3](./WECHAT-NOTIFICATION-SPEC.md)。

## 8. 容错

### 8.1 平台故障

```
Adapter 失败
   ↓
写 platform_health.error_count += 1
consecutive_failures += 1
   ↓
consecutive_failures > 5 或 success_rate < 0.7
   ↓
adapter 标记为 DEGRADED
   ↓
DEGRADED 行为(v0.2):
  - 检测频率:WARM 15min
  - 二次确认:60s × 3 次
  - LiveEvent.confidence = 'low'
  - 仍通知(用户标记低 confidence)
  - Admin 报警
```

**单平台故障不波及其他平台**:
- 平台 A 故障时,worker-A 自己的 Redis 队列堆积不影响 worker-B
- 调度器对 disabled 平台直接跳过

### 8.2 任务失败

- Dramatiq 自动重试 3 次(指数退避 1s / 5s / 30s)
- 仍失败 → 写 dead_letter_queue
- Admin 后台可见

### 8.3 重复事件

- `notification_deliveries` UNIQUE `(user_id, live_session_id, channel)`
- 即使 worker 重试、平台接口重发,DB 唯一约束保证不重复

### 8.4 微信模板错误

- 40037 触发 `WeChatTemplateDisabledError`
- **只 disable 微信模板 ID**,不影响平台 adapter
- 修复后人工 re-enable

## 9. 监控

### 9.1 Metrics

| 指标 | 来源 |
|------|------|
| 每个平台:探测次数、成功率、平均延迟、sustained_qps | Probe Worker |
| 每个 worker:队列长度、任务耗时 | Dramatiq |
| 通知:投递成功率、各 channel 成功率、grant 利用率 | Notification Worker |
| 微信:grant_request_total / grant_waste_rate | Notification Worker |
| 用户:DAU、新增订阅、通知发送量 | API Server |

V1 用 `prometheus_client` 暴露 `/metrics`,Grafana 可视化(V1.1+)。

### 9.2 Logging

- 结构化 JSON 日志(`loguru` 或 `structlog`)
- 字段:`timestamp`, `level`, `trace_id`, `user_id`, `anchor_id`, `platform`, `event_type`
- 集中到 stdout,由 Docker 收集

### 9.3 Tracing(V2)

- OpenTelemetry
- 跨服务追踪一次开播事件链路

## 10. 目录结构

```
stage-letter/
├── api/                    # FastAPI
│   ├── main.py
│   ├── deps.py
│   ├── routers/
│   ├── services/
│   ├── schemas/
│   └── models/
├── workers/
│   ├── probe/
│   │   ├── scheduler.py
│   │   ├── douyin.py
│   │   ├── bilibili.py
│   │   └── ...
│   └── notify/
│       ├── fanout.py
│       ├── wechat.py
│       └── in_app.py
├── platform_adapters/
│   ├── base.py
│   ├── douyin/
│   ├── bilibili/
│   ├── huya/
│   ├── douyu/
│   ├── twitch/
│   ├── registry.py
│   └── {platform}/capacity.md    ← v0.2 新增
├── core/
│   ├── config.py
│   ├── db.py
│   ├── redis.py
│   ├── state_machine.py
│   └── models.py
├── admin/                  # 内部 Admin Web
├── migrations/             # Alembic
├── tests/
├── docker-compose.yml
├── Dockerfile
├── experiments/            # Gate 0 实验代码
├── reports/                # Gate 0 实验报告
└── docs/                   # 立项文档
```

## 11. 关键决策记录

| 决策 | 选择 | 理由 | 备选 |
|------|------|------|------|
| 服务端语言 | Python 3.13 + FastAPI | 直播解析生态成熟 | NestJS / Go |
| 客户端框架 | **微信原生**(ADR-003,2026-08-13 定)| V1 只做微信,原生性能最优 + 包体积最小;Taro 4 未发布,跨端暂不需要 | Taro 3 |
| 数据库 | PostgreSQL | 关系 + JSONB + 部分 UNIQUE | MySQL / MongoDB |
| 队列 | Dramatiq + Redis | 轻量现代 | Celery / RQ |
| 适配器模型 | A/B 类分类 | Twitch 与抖音本质不同 | 统一轮询 |
| 状态机 | SUSPECT → CONFIRMED | 抗抖动 | 简单布尔 |
| 微信通知模型 | 乐观 grant 账本(ADR-001 + ADR-002 增量:grant 可累积储备)| 真实反映微信机制 + Gate 0A 实测验证 | 伪造额度 |
| 检测调度 | 去重 anchor + 分级轮询(v0.2)| 100K 订阅 ≠ 100K 探测 | 按订阅数探测 |
| SLA | 按平台分级(provisional)| 物理上不可能统一 < 3min | 统一 SLA |
| DEGRADED 行为 | 仍通知 + 标低 confidence | 用户错过通知更糟 | 一刀切静默 |

> **ADR-003(2026-08-13,Gate 4 选型)**:客户端用**微信小程序原生开发**,不用 Taro。
> 依据(2026-05 腾讯云实战选型调研):
> - **Taro 4 尚未正式发布**(2026-04 仍是 Taro 3 主流),生产环境不应选开发中版本
> - **V1 只做微信小程序**——框架价值在"跨",不跨端则抽象层是负担(实测:原生首屏 320ms vs Taro3 450ms;点赞响应 16ms vs 35ms;包体积 +150-200KB 逼近 2MB 限制)
> - 未来若需多端(V2+),再评估 Taro 4 成熟度或 uni-app,届时单页迁移成本可控
> - 后端 API 已按 REST 设计(API-SPEC.md),与前端框架无关,不影响