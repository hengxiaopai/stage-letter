# ROADMAP.md — 路线图

更新：2026-08-25

## 总览

```text
Gate 0 — Feasibility Evidence      ⚠️ DEGRADED（历史证据保留）
Gate 1 — Domain Core              ✅ PASS / CLOSED
Gate 2 — Detection Engine         ✅ PASS / CLOSED
Gate 3 — Notification Engine      ✅ PASS / CLOSED
Gate 4 — 微信小程序                 ✅ PASS / CLOSED
Gate 5 — Admin / Observability    ✅ PASS / CLOSED
──────────────────────────────────────────────
UI V2.1 — Streamer Detail Contract ✅ PASS WITH OPEN DELTAS
UI V2.2 — Backend/API Contract      🚧 CURRENT
V1 Alpha Hardening                  🚧 CURRENT
V1 Alpha 内测                        NEXT
V1 公开上线                           2–4 周缓冲
```

Gate 0 的长期平台真实性证据仍保持 `DEGRADED`。Gate 1–5 的完成不覆盖该历史限制。

## 当前阶段：UI V2.2 + Alpha Hardening

当前不是重新开启 Gate 4，而是在既有可运行小程序上完成产品信息架构与正式领域模型的对齐。

### UI V2 信息架构

目标顶层：

```text
首页 / 发现 / 动态 / 我的
```

主播详情：

```text
概览
记录 ─ 列表 / 日历
数据 ─ 统计 / 分析
档案
```

开播日历和月度总结属于主播详情内部，不单独占一级页面。

### UI V2.2 必做 Delta

#### D1 — Viewer Context + Reminder Preference（P0）

- 详情返回当前用户 Follow/Subscription/NotificationPreference。
- 删除详情页 `remindOn: true` 假状态。
- 提醒开关具备真实 GET/PATCH 持久化与失败回滚。

#### D2 — Session Query / Calendar / Stats（P0/P1）

- 分页直播记录。
- 按月 Session 聚合日历。
- 场次、天数、总时长、平均时长、最长/最短等统计。
- 精确时间分析只使用 `started_at_source=platform`。
- `analysis` 可在 sessions/calendar/stats 后单独切片。

#### D3 — Personal Streamer Profile（P1）

- 用户备注。
- 自定义称呼。
- 分组。
- Reference Schedule。

D3 不阻塞最小主播详情 V2。

#### D4 — Formal Consumer Parity（P0）

- legacy / formal 详情路径必须拥有等价 UI Contract。
- Formal Session 补足 UI 必需 metadata（如 title）。
- Formal 路径必须具备 live state / freshness / last probe / source started time 等消费字段。
- 不允许 Formal 路径长期依赖写死“正在直播/直播”。

详细契约：`docs/features/F-UI-V2-01-streamer-detail-contract.md`。

## Alpha Hardening

在 UI V2.2 并行进行的 Alpha 加固：

- 直播状态 `LIVE/OFFLINE/CONFIRMING/UNKNOWN/DEGRADED` 的用户语义稳定。
- 手动刷新继续使用 accepted/cooldown + 延迟回读，不返回伪即时结果。
- 状态翻转二次确认保持有界窗口；不得长期卡在“确认中”。
- provider 失败不能变成 OFFLINE。
- TikHub 作为可选供应方接入 Adapter，不成为前端直接依赖。
- 首页订阅行向整行点击 + 轻操作收敛，逐步移除两个等权 CTA。

## 历史 Gate

### Gate 0 — Feasibility Evidence

目标：微信 grant、平台 adapter、容量、稳定性和端到端通知的早期证据。

状态：⚠️ `DEGRADED`。保留原实验和报告用于审计，不补写缺失的长期生命周期证据。

详见 `GATE-0.md` 和 `reports/`。

### Gate 1 — Domain Core

状态：✅ PASS / CLOSED。

核心：Formal Domain、PostgreSQL/Alembic、状态机、LiveSession/LiveEvent、幂等与持久化边界。

### Gate 2 — Detection Engine

状态：✅ PASS / CLOSED。

核心：due selection、lease、多 worker、容量隔离、平台健康、重试/限流/熔断、重启恢复。

### Gate 3 — Notification Engine

状态：✅ PASS / CLOSED。

核心：LIVE_STARTED fan-out、grant ledger、WeChat delivery、fallback、restart、history 和投递状态机。

### Gate 4 — 微信小程序

状态：✅ PASS / CLOSED（工程链路）。

已经完成：登录、首页、发现/搜索、订阅、主播详情、通知历史、我的、真机受控通知与详情跳转。

注意：Gate 4 CLOSED 不意味着 UI V2 已完成；UI V2 是其上的产品迭代。

### Gate 5 — Admin / Observability

状态：✅ PASS / CLOSED。

核心：受保护 Admin 健康、平台 enable/disable、脱敏查询、错误聚合、重启读取。

## V1 Alpha 内测

进入条件：

- UI V2.2 的 D1 与 D4 完成。
- D2 至少完成 sessions + calendar + 基础 stats。
- 主播详情没有硬编码提醒状态或统计数据。
- README / API-SPEC / DATA-MODEL / feature contract 同步。
- 微信开发者工具逐屏验收通过。
- 至少完成一次真机状态刷新 + 提醒开关持久化验收。

目标：小规模真实用户持续使用，验证“添加主播 → 状态可信 → 收到提醒 → 查看详情”的闭环。

## V1 公开上线

前置：

- 微信审核。
- 生产域名与证书。
- secret store / key rotation。
- 监控和告警。
- 灰度策略。
- Gate 0 平台风险在发布说明中显式保留。

## V1.1 / V1.2

- 快手 / Twitch 等 P1 平台。
- 性能与缓存优化。
- 通知记录导出。
- 通知点击转化分析。
- 更丰富的平台 capability-driven UI。

## V2

- 跨平台主播身份合并。
- 用户主播档案增强。
- 静默时间段完整产品化。
- 主播动态扩展到非直播事件。
- H5 或其他客户端评估。

## V3+

- 创作者订阅情报中心。
- 直播预约与规律预测。
- 主播情报雷达。
- 高级分析与会员能力。

## 分支策略

```text
main
└─ codex/ui-v2-2-backend-contract   ← CURRENT NEXT WORK BRANCH
```

约定：

- `main` 是唯一合并基线。
- 已完成的 `codex/gate*` 分支仅保留审计，不继续承载新功能。
- UI V2 新工作使用 `codex/ui-v2-*`。
- 每次合并后，下一分支从最新 `main` 重新创建。
- 一个分支只完成一个主目标，并同步对应 feature contract 与验收证据。

## 风险

| 风险 | 触发条件 | 处理 |
| --- | --- | --- |
| 抖音/TikHub 上游变化 | 频繁 UNKNOWN/DEGRADED | 降级 UI，保护其他平台，不误判 OFFLINE |
| legacy/formal 语义分叉 | 同主播不同路径返回不同状态/标题 | D4 Formal Consumer Parity 优先处理 |
| 统计误导 | probe 时间进入精确规律分析 | 数据质量过滤，仅可信 platform start time 参与 |
| 微信 grant/模板限制 | 无可用 grant 或 provider 拒绝 | 明确 UI 状态 + durable fallback |
| UI 文档与实现漂移 | Codex 按旧原型恢复旧结构 | feature contract 先于代码，合并前强制同步 |

## 进度记录规则

每个阶段完成时：

1. 更新对应 `docs/features/`。
2. 更新 README / ROADMAP（若状态变化）。
3. 记录自动化、开发者工具、真机/真实 provider 证据。
4. 合并后从最新 `main` 建立下一工作分支。
