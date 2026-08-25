# 小程序 UI 实施基线

更新：2026-08-25

## 1. 视觉系统

StageLetter V2 采用克制的冷白 / 浅蓝视觉语言：

- 页面背景：`#F6F8FC` / `#F8FAFC`。
- 主品牌蓝：`#2F6BFF`（实现中已有 `#2563EB/#2C6EF2` 可逐步统一）。
- 主文字：`#15213A` / 深蓝黑。
- 次级文字：蓝灰。
- `LIVE` 红色只用于正在直播和强实时状态。
- 橙色只用于 UNKNOWN / ERROR / 降级提示。
- 不使用大面积高饱和渐变、Emoji 操作图标或装饰性“AI UI”光效。
- 卡片以白底、轻边框、轻阴影和中等圆角为主。

微信小程序优先使用系统字体和本地资产，不依赖网页字体下载。

## 2. 顶层信息架构

目标 TabBar：

```text
首页 / 发现 / 动态 / 我的
```

当前代码仍为 `首页 / 发现 / 消息 / 我的`。在“动态”页面的事件模型与 UI Contract 冻结后再改名，禁止仅改文字而保留消息式信息架构。

### 首页

首页只回答两个问题：

1. 谁正在直播？
2. 我订阅了谁？

规则：

- 0 个订阅：显示直播空态和订阅空态。
- 有订阅、0 个已确认 LIVE：显示紧凑空态/确认态，同时继续展示订阅列表。
- 1 个 LIVE：允许较大横向卡片。
- 2 个及以上 LIVE：横向滑动卡片，右侧提供“查看全部”。
- “查看全部”进入纵向完整直播列表。
- 订阅行整行可点击进入详情；V2 不再保留“进入详情 / 管理提醒”两个等权按钮挤占主列表。
- 提醒管理通过铃铛状态或详情页完成。

订阅排序：`LIVE → CHECKING → UNKNOWN/ERROR → OFFLINE`。

### 发现

搜索框统一文案：

> 搜索主播、昵称或粘贴直播/主页链接

检测到支持的平台链接时，切换为链接识别流程。抖音昵称搜索和链接解析必须按 adapter/provider 实际能力降级，不伪造空结果。

### 动态

“动态”表示主播世界发生的事实，不等同通知投递：

- LIVE_STARTED
- LIVE_ENDED
- 状态恢复/异常
- 后续标题变化、特殊活动等

“通知历史”则表示 StageLetter 是否成功向用户投递通知；二者必须保持边界。

### 我的

我的页面负责：用户信息、订阅管理、通知历史、提醒说明、设置和关于。未建立真实等级/积分系统前，不展示 `Lv.X`、积分或伪权益。

## 3. 主播详情 V2

主播详情冻结为四个一级入口：

```text
概览 / 记录 / 数据 / 档案
```

### 概览

首屏只回答：是谁、现在播没播、我能做什么。

推荐顺序：

1. 头像 / 名称 / 平台 / 订阅关系。
2. 当前状态。
3. 当前直播标题与可信开播信息。
4. 主操作：当前只能复制链接时必须写“复制直播间链接”。
5. 开播提醒。
6. 最近直播。
7. 近 7 天速览和“查看完整数据”入口。

### 记录

二级切换：`列表 / 日历`。

列表按 Session 展示开播、下播、时长、标题和进行中状态。

日历语义：

- 蓝点：检测到直播。
- 数字角标：同日多场。
- 空白：未检测到直播，不等于确定未播。
- `?`：数据覆盖不足。
- “请假”：只有明确来源或用户人工标记才允许出现。

月度总结作为日历底部摘要，不单独占一级 Tab。

### 数据

二级切换：`统计 / 分析`。

统计负责事实型指标：场次、天数、总时长、平均时长、最长/最短、时间分布和星期分布。

分析负责解释性结果：常见开播时间、稳定性、相对历史变化、准时/迟到/早到。准时分析只有 Reference Schedule 建立后才能开启。

### 档案

基础主播资料与用户自己的关系数据分开：

- 全局资料：昵称、头像、简介、平台身份、主页/直播间。
- 用户私有：备注、自定义称呼、分组、关注时间、Reference Schedule。

热梗、名场面、社区内容属于后续能力，不阻塞首版。

## 4. 状态全集

UI 只消费五个用户态：

| UI 状态 | 文案 | 色彩 |
| --- | --- | --- |
| LIVE | 正在直播 | 红 |
| OFFLINE | 未开播 | 中性灰 |
| CHECKING | 正在确认 | 蓝灰 |
| UNKNOWN | 状态待确认 | 橙 |
| ERROR | 暂时无法获取 | 橙/警示 |

还必须设计以下页面状态：

- loading / skeleton
- no subscription
- no live history
- no activity
- notification denied
- notification grant unavailable
- platform degraded
- streamer unavailable
- network error / retry

`UNKNOWN != OFFLINE` 是全站硬约束。

## 5. 数据来源标签

每个新 UI 字段必须在设计包里标记：

- `NOW`
- `DERIVED`
- `OPTIONAL`
- `FUTURE`

规则：

- `DERIVED` 优先从 StageLetter 自己的 LiveSession / LiveEvent 历史计算。
- `OPTIONAL` 数据源不存在或质量不足时直接隐藏，不用“暂无”填满页面。
- `FUTURE` 不允许在代码中写假数据。
- `started_at_source=probe` 不可用于精确开播时间、准时/迟到和时间分布分析。

详细字段契约见 `features/F-UI-V2-01-streamer-detail-contract.md`。

## 6. 公共品牌头与公告条

所有顶层页复用统一品牌组件。

### 品牌头

- 唯一品牌图标资产：`miniapp/assets/brand/stage-letter-mark.png`。
- 图标、`开场信`、`StageLetter` 组成固定品牌组。
- 禁止在不同页面自行重画品牌图标。

### 公告条

- 结构：图标 → `公告` 标签 → 单条正文 → 右侧细箭头。
- 浅蓝底、品牌蓝文字。
- 可关闭/弱化的公告不应长期挤占首屏核心信息。

## 7. Figma 与仓库文档关系

- Figma Master 是视觉参考源。
- `docs/UI-DESIGN.md` 与 `docs/features/` 是实现契约源。
- 如果 Figma 与仓库冻结契约冲突，先更新设计与契约，禁止 Codex 自行猜测。
- AI 生成效果图只用于方向探索；未写入 Figma/契约前不视为正式设计基线。

## 8. 资产

- `miniapp/assets/brand/stage-letter-mark.png`
- `miniapp/assets/empty/no-live-letter.png`
- `miniapp/assets/empty/no-subscriptions-parcel.png`
- `miniapp/assets/profile/`
- `miniapp/assets/tabbar/`

后续新增图标保持同一线性/简洁风格，不使用 Emoji 替代正式交互图标。
