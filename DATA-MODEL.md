# DATA-MODEL.md — 数据库模型

> 数据库:PostgreSQL 15+
> ORM:SQLAlchemy 2.0 (async) + Alembic
> **v0.2 重大变更**: §7 表替换,§4 UNIQUE 调整,§11 probe_runs 挪位置,§12 不变量更新。详见 [CHANGELOG.md](./CHANGELOG.md)。

## ER 概览

```
                 users
                   │
                   │ 1:N
                   ▼
         user_subscriptions
                   │
                   │ N:1
                   ▼
                 anchors ◄──── platform_accounts
                   │              │  (V1 一个 anchor ≈ 一个平台账号)
                   │              │
                   │              ▼
                   │         live_sessions
                   │              │
                   │              ▼
                   │         live_events
                   │
                   └─── wechat_subscription_grants (1:N user × template)
                   │
                   └─── notification_jobs ──── notification_deliveries
                                                │
                                                ▼
                                          platform_health
```

## 1. users

用户主表。

```sql
CREATE TABLE users (
    id              BIGSERIAL PRIMARY KEY,
    openid          VARCHAR(64) UNIQUE NOT NULL,
    unionid         VARCHAR(64),
    nickname        VARCHAR(64),
    avatar          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at  TIMESTAMPTZ
);

CREATE INDEX idx_users_unionid ON users(unionid);
```

> **v0.2 决策**: V1 明文存储 openid/unionid,V2 升级到 AES-256-GCM + KMS。  
> 详见 [SECURITY.md §3.1](./SECURITY.md)。

## 2. anchors

主播身份(逻辑上的"主播",跨平台统一)。

```sql
CREATE TABLE anchors (
    id              BIGSERIAL PRIMARY KEY,
    display_name    VARCHAR(128) NOT NULL,
    avatar          TEXT,
    bio             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> **V1 不做跨平台身份合并**。  
> 同一主播在不同平台视为不同 anchor。V2 再做合并。

## 3. platform_accounts

主播在某平台的具体账号。

```sql
CREATE TABLE platform_accounts (
    id                    BIGSERIAL PRIMARY KEY,
    anchor_id             BIGINT NOT NULL REFERENCES anchors(id),
    platform              VARCHAR(32) NOT NULL,    -- douyin / bilibili / huya / douyu / twitch / ...
    platform_user_id      VARCHAR(128) NOT NULL,  -- 平台侧 user_id
    room_id               VARCHAR(128),
    canonical_url         TEXT NOT NULL,
    last_status           VARCHAR(16) NOT NULL DEFAULT 'OFFLINE',  -- OFFLINE / SUSPECT_ONLINE / ONLINE / SUSPECT_OFFLINE
    last_checked_at       TIMESTAMPTZ,
    last_live_started_at  TIMESTAMPTZ,
    adapter_version       VARCHAR(32),
    is_disabled           BOOLEAN NOT NULL DEFAULT false,
    polling_tier          VARCHAR(16) NOT NULL DEFAULT 'warm',  -- hot / warm / cold
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(platform, platform_user_id)
);

CREATE INDEX idx_platform_accounts_anchor ON platform_accounts(anchor_id);
CREATE INDEX idx_platform_accounts_due
    ON platform_accounts(platform, is_disabled, last_checked_at)
    WHERE is_disabled = false;
CREATE INDEX idx_platform_accounts_tier
    ON platform_accounts(platform, polling_tier, is_disabled)
    WHERE is_disabled = false;
```

> **v0.2 新增字段** `polling_tier` —— 分级轮询的关键字段。详见 [ARCHITECTURE.md §5.4](./ARCHITECTURE.md)。

## 4. user_subscriptions

用户 ↔ anchor 的关注关系。

```sql
CREATE TABLE user_subscriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id),
    anchor_id           BIGINT NOT NULL REFERENCES anchors(id),
    platform_account_id BIGINT NOT NULL REFERENCES platform_accounts(id),
    notify_enabled      BOOLEAN NOT NULL DEFAULT true,
    is_starred          BOOLEAN NOT NULL DEFAULT false,
    silent_start        TIME,
    silent_end          TIME,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- v0.2 修改: UNIQUE 改为 (user_id, platform_account_id) 更直接
    UNIQUE(user_id, platform_account_id)
);

CREATE INDEX idx_user_subs_user ON user_subscriptions(user_id);
CREATE INDEX idx_user_subs_anchor ON user_subscriptions(anchor_id);
CREATE INDEX idx_user_subs_pa ON user_subscriptions(platform_account_id);
```

> **v0.2 关键变更**: UNIQUE 由 `(user_id, anchor_id)` 改为 `(user_id, platform_account_id)`,避免一个用户在不同平台订阅同一个主播(逻辑上)时被错误合并。  
> V1 anchor 与 platform_account 1:1,但 UNIQUE 选择 platform_account_id 更直接、更反映业务。

### Formal follow / notification preference（Gate 1+）

`follows` 表示“用户关注了哪个 Creator/PlatformAccount”；`notification_preferences` 表示独立的提醒策略。两者不得折叠。

```sql
CREATE TABLE notification_preferences (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id),
    platform_account_id BIGINT NOT NULL REFERENCES platform_accounts(id),
    enabled             BOOLEAN NOT NULL DEFAULT true,
    silent_start        TIME,
    silent_end          TIME,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, platform_account_id)
);
```

唯一约束同时支持按 `(user_id, platform_account_id)` 的所有权读取。兼容迁移期间，偏好写操作必须同步 `user_subscriptions.notify_enabled`；Formal 记录是新接口的读取真相。

## 5. live_sessions

一次直播会话。

```sql
CREATE TABLE live_sessions (
    id                  BIGSERIAL PRIMARY KEY,
    platform_account_id BIGINT NOT NULL REFERENCES platform_accounts(id),
    anchor_id           BIGINT NOT NULL REFERENCES anchors(id),
    platform            VARCHAR(32) NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL,
    ended_at            TIMESTAMPTZ,
    title               TEXT,
    cover               TEXT,
    viewer_count        INTEGER,
    state               VARCHAR(16) NOT NULL DEFAULT 'OPEN',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_live_sessions_pa_open
    ON live_sessions(platform_account_id)
    WHERE state = 'OPEN';
CREATE INDEX idx_live_sessions_anchor_started
    ON live_sessions(anchor_id, started_at DESC);
```

**关键 UNIQUE**:同一时刻一个 platform_account 只能有 1 个 OPEN session。

```sql
CREATE UNIQUE INDEX uniq_open_session_per_pa
    ON live_sessions(platform_account_id)
    WHERE state = 'OPEN';
```

> 这是状态机正确性的兜底。即使代码 bug 创建了多个 OPEN,DB 会拒绝。

## 6. live_events

状态变化事件(不可变 append-only)。

```sql
CREATE TABLE live_events (
    id                  BIGSERIAL PRIMARY KEY,
    platform_account_id BIGINT NOT NULL REFERENCES platform_accounts(id),
    anchor_id           BIGINT NOT NULL REFERENCES anchors(id),
    live_session_id     BIGINT REFERENCES live_sessions(id),
    event_type          VARCHAR(32) NOT NULL,
    -- SUSPECT_ONLINE / CONFIRMED_ONLINE / SUSPECT_OFFLINE / CONFIRMED_OFFLINE
    confidence          VARCHAR(16) NOT NULL DEFAULT 'normal',  -- v0.2 新增: normal / low (DEGRADED 平台)
    detected_at         TIMESTAMPTZ NOT NULL,
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_live_events_pa_detected
    ON live_events(platform_account_id, detected_at DESC);
CREATE INDEX idx_live_events_session
    ON live_events(live_session_id);
```

> **v0.2 新增** `confidence` 字段:DEGRADED 平台产生的事件标记 low confidence(详见 [PLATFORM-ADAPTER-SPEC.md §7](./PLATFORM-ADAPTER-SPEC.md))。

## 7. wechat_subscription_grants (v0.2 替换 notification_entitlements)

**用户授权 grant 的乐观账本**。详见 [WECHAT-NOTIFICATION-SPEC.md §2](./WECHAT-NOTIFICATION-SPEC.md) 与 ADR-001 / ADR-002。

> **✅ Gate 0A 实测修正(2026-08-12,ADR-002)**:`granted_count` **可累积储备** — 连续授权 N 次 = 储备 N 条额度,可跨时间段消耗(实测:授权 2 次 → 2 条全部送达)。原"每次授权独立计次"描述已修正。

```sql
CREATE TABLE wechat_subscription_grants (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    template_id     VARCHAR(64) NOT NULL,
    granted_count   INTEGER NOT NULL DEFAULT 0,  -- 用户主动 accept 次数(可累积储备)
    consumed_count  INTEGER NOT NULL DEFAULT 0,  -- 真实 send 成功 / 失败次数
    last_granted_at TIMESTAMPTZ,
    last_send_at    TIMESTAMPTZ,
    last_send_error VARCHAR(255),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id, template_id)
);

CREATE INDEX idx_wsg_user ON wechat_subscription_grants(user_id);
```

**`available = granted - consumed`**(应用层计算,不存)。

| 触发 | granted | consumed |
|------|---------|----------|
| 初始 | 0 | 0 |
| 用户点 accept | +1 | - |
| send 返回 0 | - | +1 |
| send 返回 43101(用户拒收) | - | +1(grant 失效) |
| send 返回 40037(模板错误) | - | -(**报警,disable 模板**) |
| send 返回 45009 / 5xx / 网络 | - | -(grant 保留,重试) |

## 8. notification_jobs

一次开播 → fan-out 出来的投递任务。

```sql
CREATE TABLE notification_jobs (
    id              BIGSERIAL PRIMARY KEY,
    live_event_id   BIGINT NOT NULL REFERENCES live_events(id),
    live_session_id BIGINT REFERENCES live_sessions(id),
    user_id         BIGINT NOT NULL REFERENCES users(id),
    anchor_id       BIGINT NOT NULL REFERENCES anchors(id),
    state           VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    -- PENDING / PROCESSING / DONE / FAILED
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,

    UNIQUE(live_event_id, user_id)
);

CREATE INDEX idx_nj_state ON notification_jobs(state, created_at);
```

## 9. notification_deliveries

每个 channel 的投递结果。

```sql
CREATE TABLE notification_deliveries (
    id                  BIGSERIAL PRIMARY KEY,
    notification_job_id BIGINT NOT NULL REFERENCES notification_jobs(id),
    user_id             BIGINT NOT NULL REFERENCES users(id),
    live_session_id     BIGINT REFERENCES live_sessions(id),
    channel             VARCHAR(16) NOT NULL,  -- wechat / in_app / email / bark / ...
    state               VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    error_code          VARCHAR(64),
    error_message       TEXT,
    attempt             INTEGER NOT NULL DEFAULT 0,
    sent_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id, live_session_id, channel)
);

CREATE INDEX idx_nd_state ON notification_deliveries(state);
```

## 10. platform_health

平台适配器健康度。

```sql
CREATE TABLE platform_health (
    platform              VARCHAR(32) PRIMARY KEY,
    state                 VARCHAR(16) NOT NULL DEFAULT 'HEALTHY',
    -- HEALTHY / DEGRADED / DISABLED
    last_success_at       TIMESTAMPTZ,
    last_failure_at       TIMESTAMPTZ,
    success_rate_24h      NUMERIC(5, 2),
    avg_latency_ms_24h    INTEGER,
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    error_count_24h       INTEGER NOT NULL DEFAULT 0,
    success_count_24h     INTEGER NOT NULL DEFAULT 0,
    -- v0.2 新增: 容量上限(由 Gate 0C 测量后写入)
    sustained_qps         NUMERIC(6, 2),
    max_anchors           INTEGER,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> **v0.2 新增** `sustained_qps` 与 `max_anchors` —— Gate 0C 测量后填入,作为容量计算的依据。

## 11. probe_runs (v0.2 调整位置)

> **v0.2 调整**: 从"V1.1 可选"挪到 **Gate 2 必须**(轻量 probe telemetry)。

```sql
CREATE TABLE probe_runs (
    id                  BIGSERIAL PRIMARY KEY,
    platform_account_id BIGINT NOT NULL REFERENCES platform_accounts(id),
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    success             BOOLEAN,
    error_message       TEXT,
    snapshot            JSONB
);

CREATE INDEX idx_pr_pa_started ON probe_runs(platform_account_id, started_at DESC);
```

> 用于 Gate 2+ 排障、容量统计、回放审计。

## 12. 关键不变量 (Invariant) - v0.2 更新

| # | 不变量 | 实现 |
|---|--------|------|
| 1 | 同一 `(user_id, platform_account_id)` 唯一 | `user_subscriptions` UNIQUE |
| 2 | 同一 `(platform, platform_user_id)` 唯一 | `platform_accounts` UNIQUE |
| 3 | 同一 `platform_account` 同一时刻只能有 1 个 OPEN LiveSession | `live_sessions` UNIQUE partial index |
| 4 | 同一 `(live_event_id, user_id)` 只产生 1 个 notification_job | `notification_jobs` UNIQUE |
| 5 | 同一 `(user_id, live_session_id, channel)` 只投递 1 次 | `notification_deliveries` UNIQUE |
| 6 | 同一 `(user_id, template_id)` 唯一 grant 记录 | `wechat_subscription_grants` UNIQUE |
| 7 | 同 anchor 不同平台的 subscriptions 互不干扰 | §4 UNIQUE 选择 platform_account_id 保证 |

> v0.2 删除原 §6 "季度重置"相关不变量(该字段不存在了)。

## 13. 常用查询

### Q1. 给主播找所有订阅者(用于 fan-out)

```sql
SELECT us.user_id
FROM user_subscriptions us
WHERE us.anchor_id = $1
  AND us.notify_enabled = true;
```

> v0.2 简化:不再 JOIN notification_entitlements。

### Q2. 选出 due 的 platform_accounts(按 tier)

```sql
-- HOT: 30s 一次
SELECT * FROM platform_accounts
WHERE platform = $1
  AND is_disabled = false
  AND polling_tier = 'hot'
  AND last_checked_at < now() - interval '30 seconds'
ORDER BY last_checked_at NULLS FIRST
LIMIT 100;

-- WARM: 5min 一次
SELECT * FROM platform_accounts
WHERE platform = $1
  AND is_disabled = false
  AND polling_tier = 'warm'
  AND last_checked_at < now() - interval '5 minutes'
ORDER BY last_checked_at NULLS FIRST
LIMIT 100;

-- COLD: 30min 一次
SELECT * FROM platform_accounts
WHERE platform = $1
  AND is_disabled = false
  AND polling_tier = 'cold'
  AND last_checked_at < now() - interval '30 minutes'
ORDER BY last_checked_at NULLS FIRST
LIMIT 100;
```

### Q3. 当前 OPEN 的 LiveSession

```sql
SELECT *
FROM live_sessions
WHERE platform_account_id = $1
  AND state = 'OPEN';
```

(应保证只有 1 行;UNIQUE partial index 保证)

### Q4. 用户可用 grant 数

```sql
SELECT granted_count - consumed_count AS available
FROM wechat_subscription_grants
WHERE user_id = $1
  AND template_id = $2;
```

### Q5. 用户最近通知记录

```sql
SELECT nd.*, ls.started_at, a.display_name
FROM notification_deliveries nd
JOIN live_sessions ls ON ls.id = nd.live_session_id
JOIN anchors a ON a.id = ls.anchor_id
WHERE nd.user_id = $1
ORDER BY nd.created_at DESC
LIMIT 50;
```

## 14. 迁移策略

- 使用 Alembic 管理 schema 迁移
- 每次 Gate 升级前必须能 `alembic upgrade head` 从空库成功
- 禁止手工改表,所有变更走 migration

### v0.2 必须的 migration

```python
# alembic/versions/v0_2_grant_model.py

def upgrade():
    # 1. 新增 wechat_subscription_grants
    op.create_table(
        'wechat_subscription_grants',
        sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('user_id', sa.BigInteger, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('template_id', sa.String(64), nullable=False),
        sa.Column('granted_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('consumed_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_granted_at', sa.DateTime(timezone=True)),
        sa.Column('last_send_at', sa.DateTime(timezone=True)),
        sa.Column('last_send_error', sa.String(255)),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'template_id', name='uq_wsg_user_template'),
    )

    # 2. 改 user_subscriptions UNIQUE
    op.drop_constraint('user_subscriptions_user_id_anchor_id_key', 'user_subscriptions')
    op.create_unique_constraint(
        'uq_user_subs_user_pa',
        'user_subscriptions',
        ['user_id', 'platform_account_id']
    )

    # 3. 删 notification_entitlements
    op.drop_table('notification_entitlements')

    # 4. 新增字段
    op.add_column('platform_accounts', sa.Column('polling_tier', sa.String(16), server_default='warm'))
    op.add_column('live_events', sa.Column('confidence', sa.String(16), server_default='normal'))
    op.add_column('platform_health', sa.Column('sustained_qps', sa.Numeric(6, 2)))
    op.add_column('platform_health', sa.Column('max_anchors', sa.Integer))

def downgrade():
    # ... reverse
    pass
```

## 15. 备份与归档

- 每日 pg_dump
- notification_deliveries 90 天后归档到 cold storage(V1 暂不做,V2 规划)
- live_events 不归档(append-only,partition by month 即可)
- wechat_subscription_grants 不归档(必须保留 reconciliation 能力)
