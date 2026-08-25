# 开场信 / StageLetter

开场信是一个面向微信小程序的跨平台主播开播通知系统。用户关注主播后，后端持续检测抖音、哔哩哔哩、虎牙和斗鱼的直播状态，并通过微信订阅消息或应用内通知提供可恢复、可追踪的开播提醒。

> 当前仍处于工程验证与 V1 Alpha 准备阶段，尚未获得生产发布批准，也不承诺平台调用、消息发送或用户阅读的 exactly-once 语义。

## 当前进度

```text
Gate 0  平台真实性证据           ⚠️ DEGRADED（历史证据保留）
Gate 1  领域与通知基础设施       ✅ PASS / CLOSED
Gate 2  检测引擎                 ✅ PASS / CLOSED
Gate 3  Notification Engine    ✅ PASS / CLOSED
Gate 4  微信小程序               ✅ PASS / CLOSED
Gate 5  Admin / Observability  ✅ PASS / CLOSED
──────────────────────────────────────────────
UI V2.1 主播详情契约冻结          ✅ PASS WITH OPEN DELTAS
UI V2.2 Backend/API Contract     🚧 CURRENT
V1 Alpha 内测准备                 🚧 CURRENT
```

当前冻结基线：

- 最近一次完整自动化基线：`622 passed, 173 subtests passed`
- Alembic migration head：`f52a9d1c4e81`
- 2026-08-25 直播状态与首页定向回归：`29 passed`
- Gate 4.5：开发者工具联调、真机收到受控通知、点击进入主播详情 `PASS`
- Gate 5.1–5.5：Admin 健康、平台控制、脱敏查询、错误聚合和重启读取均已验收
- UI V2.1：主播详情信息架构、状态展示语义与字段能力分级已冻结；D1–D4 后端差异待实施

Gate 0A 的平台生命周期证据仍标记为 `DEGRADED`。后续 Gate 的通过不覆盖或伪造这项历史限制。

## 当前产品方向

StageLetter 不只做“是否开播”的瞬时检测，而是逐步形成**属于用户自己的主播动态档案**。当前 UI V2 主播详情统一为四个一级入口：

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

其中：

- **概览**：当前直播状态、直播标题、可信开播时间、提醒状态、最近直播和速览统计。
- **记录**：完整直播 Session 列表与按月开播日历。
- **数据**：直播场次、总时长、平均时长、时段/星期分布等可推导统计。
- **分析**：在数据质量达标后给出常见开播时间、稳定性和相对规律；不使用探测兜底时间伪装成真实开播时间。
- **档案**：主播基础资料，以及后续的用户备注、分组、别名和个人关注记录。

月度总结属于“记录 / 日历”和“数据 / 统计”的派生结果，不再单独作为一级页面。

## 已实现能力

### 直播检测

- 抖音、哔哩哔哩、虎牙、斗鱼四个平台适配器
- 对外统一状态：`LIVE / OFFLINE / CONFIRMING / UNKNOWN / DEGRADED`
- UI 语义收敛为：`正在直播 / 未开播 / 正在确认 / 状态待确认 / 暂时无法获取`
- provider 失败、解析失败和限流不会被误判为 `OFFLINE`
- HOT / WARM / COLD 检测节奏、PostgreSQL due selection、lease 与多 worker 隔离
- 状态翻转二次确认、短时确认窗口与过期回退
- 首页刷新接口只返回 `accepted/cooldown` 与建议回读窗口，客户端不会把“已受理”伪装成“已确认”

### 通知引擎

- `LIVE_STARTED` 事件到关注者 fan-out 的持久化投递链路
- 微信订阅消息 grant 账本、原子消费、摄取与对账
- 微信模板注册表、`40037` 模板禁用和管理恢复
- 微信不可用或 grant 不足时的 durable `IN_APP` fallback
- 重启恢复、`AMBIGUOUS` 结果、单数据库 claim owner 和重复发送边界
- 通知历史、已读状态与主播详情页跳转目标

### 微信小程序

- 原生 WXML / WXSS / JavaScript 工程
- 登录、首页、发现/搜索、订阅管理、通知历史、个人页和主播详情链路
- 首页按真实数据呈现直播横滑卡、确认卡或空直播卡，并支持 `全部 / 直播中 / 未开播` 快速筛选
- 抖音昵称搜索支持可选 TikHub 传输；未配置或上游异常时明确降级，不伪造“未找到”
- 当前详情页提醒开关仍是旧版 UI 状态，尚未与 `NotificationPreference` 建立真实 GET/PATCH 契约；UI V2.2 将优先修复
- 当前底部导航仍为 `首页 / 发现 / 消息 / 我的`；UI V2 目标语义为 `首页 / 发现 / 动态 / 我的`，待信息架构同步后实施

## TikHub 与平台能力边界

TikHub 是抖音等平台数据的**供应方之一**，不是前端 UI Contract。StageLetter 必须先将 provider 响应归一化为自己的领域事实，再交给状态机和前端：

```text
TikHub / 平台响应
      ↓
Platform Adapter
      ↓
LiveSnapshot / LiveObservation
      ↓
状态机 / LiveSession / LiveEvent
      ↓
StageLetter UI Contract
```

所有 UI 字段按能力分级：

- `NOW`：当前已有稳定数据来源，可直接实现。
- `DERIVED`：由 StageLetter 自己的历史 Session/Event 计算。
- `OPTIONAL`：只有 provider/adapter 明确支持并且质量达标时才展示。
- `FUTURE`：当前不承诺，不允许为了还原设计稿写假数据。

例如直播时长、月直播天数、场次、平均时长属于 `DERIVED`；福袋、礼物榜、在线人数等高级字段必须按实际能力决定是否显示。

## UI V2.2 当前后端差异

进入主播详情 V2 实现前，当前冻结四个 Delta：

- **D1 — Viewer Context + Reminder Preference**：详情 API 返回当前用户 Follow/NotificationPreference；提醒开关从真实后端读取并支持持久化修改，删除 `remindOn: true` 假状态。
- **D2 — Session Query / Calendar / Stats**：增加分页直播记录、月历聚合、统计接口和数据质量规则。
- **D3 — Personal Streamer Profile**：后续增加用户备注、分组、自定义称呼和 Reference Schedule；不阻塞最小主播详情 V2。
- **D4 — Formal Consumer Parity**：Formal Creator/Session 路径必须与 legacy 消费路径返回等价的状态、标题、时间和元数据，逐步消除双世界语义差异。

详细契约见 `docs/features/F-UI-V2-01-streamer-detail-contract.md`。

## 核心架构

```text
平台适配器
  -> 检测运行时 / due selection / lease
  -> LiveObservation（事实观测）
  -> 状态转换与 replay
  -> LiveSession / LiveEvent
  -> follower fan-out
  -> WECHAT_SUBSCRIBE 或 IN_APP
  -> 通知历史 / 主播详情 / 统计派生
```

主要边界：

- provider I/O 不放在数据库事务中。
- provider 失败不是直播事实，不能直接改变 live truth。
- `accepted`、`delivered`、`read` 是不同语义。
- worker、provider 和用户阅读均不做 exactly-once 声明。
- legacy/compatibility 路径仍存在；任何新 UI Contract 都必须优先对齐 Formal Domain，而不是继续扩散 legacy 字段。

## 技术栈

- API：FastAPI、Pydantic
- 数据访问：SQLAlchemy 2、asyncpg、Alembic
- 数据库：PostgreSQL 16
- 缓存与运行时依赖：Redis 7、Dramatiq
- HTTP：HTTPX、Requests
- 测试：pytest、PostgreSQL 受控验收脚本
- 小程序：微信开发者工具、原生 WXML / WXSS / JavaScript
- 本地基础设施：Docker Compose

## 本地启动

建议环境：Python 3.13、Docker Desktop、微信开发者工具。

PowerShell：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d postgres redis
python -m alembic upgrade head
python -m uvicorn api.main:app --host 0.0.0.0 --port 8899 --reload
```

Git Bash：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres redis
python -m alembic upgrade head
python -m uvicorn api.main:app --host 0.0.0.0 --port 8899 --reload
```

服务监听 `0.0.0.0:8899`，微信开发者工具本机访问仍使用 `http://127.0.0.1:8899/api/v1`。真机联调需使用手机可访问的 HTTPS 地址并配置微信合法域名。

### 可选：TikHub

在根目录 `.env` 配置：

```dotenv
STAGE_LETTER_TIKHUB_API_KEY=你的_TikHub_Key
```

真实 Key 只能保存在 `.env` 或部署平台 secret store，禁止提交到 Git。

## 验证基线

完整回归和定向回归必须分开记录，避免把局部测试误写成全量基线：

```bash
python -m pytest -q
python -m alembic current
```

最近记录：

```text
full baseline: 622 passed, 173 subtests passed
migration head: f52a9d1c4e81
2026-08-25 targeted live/UI-state regression: 29 passed
```

涉及 lease、重启恢复、容量隔离、通知端到端语义或 UI V2 Contract 的改动，还应运行对应 Gate 的受控验收。真实 provider/真机动作必须单独记录，不能用 mock 或静态路径测试冒充。

## 分支与开发约定

- `main`：唯一合并基线，应保持可运行、可回退。
- `codex/gate*`：历史 Gate 或已合并功能分支，仅用于审计/追溯，不应继续承载新功能。
- UI V2 后续工作统一使用 `codex/ui-v2-*` 命名；当前下一工作分支为 `codex/ui-v2-2-backend-contract`。
- 一个分支只解决一个主目标；设计/API Contract 先冻结，再进入实现。
- 合并前更新对应 `docs/features/` 设计包、测试证据和已知限制。

## 文档索引

- [产品说明](PRODUCT.md)
- [产品需求](PRD.md)
- [功能设计与交付规范](docs/FEATURE-DESIGN-DELIVERY.md)
- [UI 实施基线](docs/UI-DESIGN.md)
- [主播详情 UI V2 Contract](docs/features/F-UI-V2-01-streamer-detail-contract.md)
- [系统架构](ARCHITECTURE.md)
- [数据模型](DATA-MODEL.md)
- [API 规范](API-SPEC.md)
- [安全说明](SECURITY.md)
- [研发路线图](ROADMAP.md)
- [Gate 0 平台证据](GATE-0.md)
- [Gate 2 检测引擎](GATE-2.md)
- [Gate 3 通知引擎](GATE-3.md)
- [Gate 4 微信小程序](GATE-4.md)
- [历史实验与验收报告](reports/)

## 当前限制

- Gate 0A 仍为 `DEGRADED`，不能宣称四个平台已完成长期生产级真实性证明。
- 尚未批准生产部署；生产认证、密钥托管、域名和监控仍需独立验收。
- UI V2 尚处于 Contract/设计冻结阶段，当前代码中的主播详情、提醒开关和底部“消息”仍是旧版实现。
- 抖音昵称搜索依赖 TikHub 凭据与上游可用性；失效时必须显示明确降级状态。
- 开播时间规律、准时/迟到分析只能使用可信的 `started_at_source=platform` 数据；`probe` 兜底时间不可参与精确行为分析。
- 当前通知保证以持久化状态机、幂等边界和可恢复性为核心，不承诺端到端 exactly-once。

## License

许可证尚未确定。
