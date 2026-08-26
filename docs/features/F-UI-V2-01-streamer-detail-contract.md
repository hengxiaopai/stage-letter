# F-UI-V2-01 — 主播详情 V2 Contract

更新：2026-08-25  
状态：**UI V2.1 CONTRACT FROZEN / BACKEND DELTAS OPEN**

## 1. 产品目标

主播详情从“单页状态查看”升级为“属于用户自己的主播动态档案”。V2 不以堆叠第三方字段为目标，而是围绕四个问题组织信息：

- 这个主播现在是否开播？
- 过去什么时候播过？
- 直播规律是什么？
- 这个主播对当前用户意味着什么？

一级信息架构冻结为：

```text
主播详情
├─ 概览
├─ 记录
│  ├─ 列表
│  └─ 日历
├─ 数据
│  ├─ 统计
│  └─ 分析
└─ 档案
```

“开播日历 / 月度总结”属于主播详情内部，不单独作为一级页面。

## 2. UI 状态契约

前端只消费以下五个 UI 状态：

| Backend state | UI state | 用户文案 |
| --- | --- | --- |
| `LIVE` | `LIVE` | 正在直播 |
| `OFFLINE` | `OFFLINE` | 未开播 |
| `CONFIRMING` / `CHECKING` | `CHECKING` | 正在确认 |
| `UNKNOWN` | `UNKNOWN` | 状态待确认 |
| `DEGRADED` | `ERROR` | 暂时无法获取 |

禁止将 `RATE_LIMITED`、`BLOCKED`、`PARSE_ERROR`、`SUSPECT_ONLINE`、`SUSPECT_OFFLINE` 等工程状态直接展示给用户。

### 状态语义

- `CHECKING` 是短暂过渡态，表示系统正在积极获取第二个独立证据。
- `UNKNOWN` 表示当前证据不足，不等于 loading，也不等于 `OFFLINE`。
- `ERROR` 表示平台/供应方能力降级；前端不得显示 TikHub/HTTP 原始错误。
- provider 请求失败永远不能被降格成“未开播”。

## 3. 字段能力等级

所有设计字段必须标注：

- `NOW`：已有稳定来源。
- `DERIVED`：可由 StageLetter 历史数据计算。
- `OPTIONAL`：provider/adapter 质量达标时才展示。
- `FUTURE`：当前不实现，不允许前端写假数据占位。

### 概览

| 字段 | 等级 | 来源 / 规则 |
| --- | --- | --- |
| 昵称、头像、简介、平台 | NOW | Creator/Profile/PlatformAccount |
| 当前直播状态 | NOW | Current Live State Contract |
| 当前直播标题 | NOW* | Provider snapshot 已有；Formal persistence 需补齐 |
| 真实开播时间 | NOW | 仅 `started_at_source=platform` 精确显示 |
| 已直播时长 | DERIVED | `now - started_at` |
| 最近确认时间 | NOW | last probe / successful probe |
| 直播间链接 | NOW | canonical URL |
| 开播提醒开关 | NOW-PLANNED | 必须来自 NotificationPreference，禁止硬编码 |
| 在线人数 | OPTIONAL | 有可靠数据时显示，否则隐藏 |

### 记录 / 列表

每个 LiveSession 需要至少返回：

```text
session_id
platform_account_id
platform
started_at
ended_at
started_at_source
title?
```

时长由 started/ended 派生。进行中 Session 明确标记“进行中”。

### 记录 / 日历

日历的基础语义：

- `●`：当天检测到至少一场直播。
- 数字角标：当天多场直播。
- 空白：未检测到直播，不自动等同“主播确定没播”。
- `?`：监测覆盖不足或数据质量不足。
- “请假”：仅在有明确来源或用户人工标记时允许出现。

月度摘要包括直播天数、场次、总时长等 DERIVED 指标。

### 数据 / 统计

支持时间窗口：`7d / 30d / month / 90d / all`。

基础指标：

- 直播天数
- 直播场次
- 总直播时长
- 平均每场时长
- 最长 / 最短直播
- 开播时段分布
- 星期分布

其中开播时段分布只使用 `started_at_source=platform` 的可信 Session。

### 数据 / 分析

分析不是简单统计，必须明确算法和数据质量：

- 常见开播时间
- 近 30 天稳定性
- 相对历史变化
- 连续直播天数 / 最长停播区间
- 准时 / 迟到 / 早到（只有 Reference Schedule 建立后才能启用）

Reference Schedule 可来自：

1. 用户明确设定；或
2. 系统基于最近足量可信 Session 推断，并在 UI 标注“根据最近 N 场推算”。

默认规则建议：±15 分钟视为准时；具体阈值必须在产品层冻结后实现。

### 档案

基础资料可先使用现有 Profile；用户个性化字段后续增加：

- remark / 我的备注
- alias / 自定义称呼
- group / 分组
- reference_schedule / 参考开播时间
- followed_at / 关注日期

热梗、名场面、社区内容属于 FUTURE，不阻塞 V2 首版。

## 4. Backend Delta

### D1 — Viewer Context + Reminder Preference（P0）

当前详情页 `remindOn: true` 是 UI 假状态。必须新增 viewer-aware contract：

```text
GET /api/v1/anchors/{id}?openid=...
```

详情返回：

```json
{
  "viewer": {
    "is_following": true,
    "subscription_id": 123,
    "notification_preference": {
      "enabled": true,
      "silent_start": null,
      "silent_end": null
    }
  }
}
```

并提供真实持久化更新接口，例如：

```text
PATCH /api/v1/subscriptions/{id}/notification-preference
```

失败时前端必须回滚开关。

### D2 — Session Query / Calendar / Stats（P0/P1）

新增建议接口：

```text
GET /api/v1/anchors/{id}/sessions?cursor=&limit=
GET /api/v1/anchors/{id}/calendar?month=YYYY-MM
GET /api/v1/anchors/{id}/stats?window=30d
GET /api/v1/anchors/{id}/analysis?window=30d
```

`analysis` 可以晚于 sessions/calendar/stats 实现。

### D3 — Personal Streamer Profile（P1）

增加用户与主播之间的个性化关系字段，不修改全局主播资料：

```text
remark
alias
group
reference_schedule
```

这些字段属于用户私有数据。

### D4 — Formal Consumer Parity（P0）

Formal Creator/LiveSession 消费路径必须与 legacy 路径返回等价 UI Contract，至少包括：

- live state
- freshness
- last probe
- session title
- source started time
- started_at_source
- canonical URL

禁止出现 legacy 路径能显示真实标题，而 Formal 路径只能写死“正在直播/直播”的长期分叉。

## 5. 数据质量规则

- `started_at_source=probe` 只证明“检测到正在直播”，不能用于精确开播时间规律、准时/迟到分析。
- 统计结果必须区分“没有直播记录”和“监测覆盖不足”。
- Session/Event 数据是 StageLetter 自己的历史资产，月报与统计优先从自身数据派生，不依赖第三方月报接口。
- OPTIONAL 字段数据源异常时应直接隐藏，不显示大量“暂无”。
- 所有设计示例数字都是视觉占位，正式实现不得写死。

## 6. UI 交互约束

- 主播详情顶部一级 Tab：`概览 / 记录 / 数据 / 档案`。
- `记录` 内二级切换：`列表 / 日历`。
- `数据` 内二级切换：`统计 / 分析`。
- 概览只显示高频信息和入口，不把所有统计塞进首屏。
- 首页订阅行整行可进入详情；V2 不再使用“进入详情 / 管理提醒”两个等权按钮挤占信息空间。
- 当前小程序只能复制直播间链接时，按钮必须写“复制直播间链接”；具备真实跳转能力后才能改成“进入直播间”。

## 7. 验收

UI V2.2 进入实现前至少满足：

- D1 真实提醒状态契约冻结。
- D2 sessions/calendar/stats API schema 冻结。
- D4 legacy/formal 详情字段矩阵完成。
- 五态 UI State Gallery 有完整 loading/empty/error/no-permission 场景。
- 所有 UI 字段均标记 NOW / DERIVED / OPTIONAL / FUTURE。
- 前端没有硬编码主播数据、统计数字或提醒状态。

实现完成后必须分别进行：自动化回归、微信开发者工具逐屏验收、真机状态/提醒交互验收。
