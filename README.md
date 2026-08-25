# 开场信 / StageLetter

开场信是一个面向微信小程序的跨平台主播开播通知系统。用户关注主播后，后端持续检测抖音、哔哩哔哩、虎牙和斗鱼的直播状态，并通过微信订阅消息或应用内通知提供可恢复、可追踪的开播提醒。

> 当前仍处于工程验证阶段，尚未获得生产发布批准，也不承诺平台调用、消息发送或用户阅读的 exactly-once 语义。

## 当前进度

```text
Gate 0  平台真实性证据         ⚠️ DEGRADED（历史证据保留）
Gate 1  领域与通知基础设施     ✅ PASS / CLOSED
Gate 2  检测引擎               ✅ PASS / CLOSED
Gate 3  Notification Engine  ✅ PASS / CLOSED
Gate 4  微信小程序             ✅ PASS / CLOSED
Gate 5  Admin / Observability  ✅ PASS / CLOSED
```

当前冻结基线：

- 自动化回归：`622 passed, 173 subtests passed`
- Alembic migration head：`f52a9d1c4e81`
- Gate 3.5 PostgreSQL 端到端验收：PASS，受控数据已恢复
- Gate 4.5：开发者工具联调、真机收到受控通知、点击进入主播详情 `PASS`
- Gate 5.1：受保护的 Admin 健康页 `PASS`；运行中准确暴露 worker 心跳异常
- Gate 5.2：受保护的 B站 `HEALTHY → DISABLED → DEGRADED` 与审计记录 `PASS`
- Gate 5.3：受保护、分页且脱敏的用户、订阅与通知投递查询 `PASS`
- Gate 5.4：受保护的固定维度指标与错误聚合 `PASS`
- Gate 5.5：独立数据库引擎重启后的只读 Admin 投影验收 `PASS`
- 2026-08-25 直播状态与首页定向回归：`29 passed`（refresh 契约、状态机、Gate 1/2 关键路径）
- 下一阶段：V1 Alpha 内测准备（仍未获得生产发布批准）

Gate 0A 的平台生命周期证据仍标记为 `DEGRADED`。后续 Gate 的通过不覆盖或伪造这项历史限制。

## 已实现能力

### 直播检测

- 抖音、哔哩哔哩、虎牙、斗鱼四个平台适配器
- `LIVE / OFFLINE / CHECKING / UNKNOWN / DEGRADED` 状态模型：确认中与暂时无法确认均为显式状态，平台失败不会被误判为下播
- HOT / WARM / COLD 检测节奏与 PostgreSQL due selection
- PostgreSQL lease、多 worker 竞争、过期接管和按平台容量隔离
- 重试、限流、熔断、观测记录及可回放状态转换
- 首页刷新接口只返回任务是否受理与建议回读窗口；客户端不会将“已受理”伪装为“已确认”

### 通知引擎

- `LIVE_STARTED` 事件到关注者 fan-out 的持久化投递链路
- 微信订阅消息 grant 账本、原子消费、摄取与对账
- 微信模板注册表、`40037` 模板禁用和管理恢复
- 微信不可用或 grant 不足时的 durable `IN_APP` fallback
- 重启恢复、`AMBIGUOUS` 结果、单数据库 claim owner 和重复发送边界
- 通知历史、已读状态与主播详情页跳转目标

### 微信小程序

- 原生 WXML / WXSS / JavaScript 工程
- 登录、首页、主播搜索、订阅管理与主播详情链路
- 首页按真实数据呈现直播横滑卡、状态确认卡或空直播卡；订阅行提供明确的详情入口与提醒管理
- 抖音昵称搜索支持可选 TikHub 传输；未配置时会明确提示，避免伪造“未找到”结果
- 通知授权、通知历史、个人页和自定义底部导航
- UI 原型与功能设计先于后续社区/主播乐园功能实现，详见 `docs/features/`

## 核心架构

```text
平台适配器
  -> 检测运行时 / due selection / lease
  -> LiveObservation（事实观测）
  -> 状态转换与 replay
  -> LiveSession / LiveEvent
  -> follower fan-out
  -> WECHAT_SUBSCRIBE 或 IN_APP
  -> 通知历史 / 主播详情
```

主要边界：

- provider I/O 不放在数据库事务中。
- provider 失败不是直播事实，不能直接改变 live truth。
- `accepted`、`delivered`、`read` 是不同语义。
- worker、provider 和用户阅读均不做 exactly-once 声明。
- 历史 `workers/probe/worker.py` 仍为 `LEGACY_REFERENCE_ONLY`。

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

Git Bash 可使用：

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres redis
python -m alembic upgrade head
python -m uvicorn api.main:app --host 0.0.0.0 --port 8899 --reload
```

启动前请检查 `.env` 中的数据库、Redis 和微信配置。服务监听 `0.0.0.0:8899`，以便本机及局域网调试访问；微信开发者工具中的本机客户端地址仍使用 `http://127.0.0.1:8899/api/v1`。两者分别是**服务监听地址**与**客户端访问地址**，并不冲突。

### 可选：抖音昵称搜索

若要启用稳定的“昵称搜索 → 用户主页标识”能力，在根目录 `.env` 设置：

```dotenv
STAGE_LETTER_TIKHUB_API_KEY=你的_TikHub_Key
```

该配置是可选能力；缺少凭据时，应用会明确显示搜索暂不可用，而不会把网络/权限问题误报为没有主播。真实 Key 只能放入 `.env`，禁止提交。

### 打开微信小程序

1. 在微信开发者工具中导入 `miniapp/` 目录。
2. 确认本地 API 已启动且数据库已迁移到 head。
3. 模拟器可使用 `127.0.0.1`；真机联调需要手机可访问的 HTTPS 地址，并按微信要求配置合法域名。
4. 开发者工具的个人设置应保存在 `project.private.config.json`，不要提交到仓库。

## 验证基线

```bash
python -m pytest -q tests/gate1 tests/gate2 tests/gate3
python -m alembic current
```

当前预期：

```text
556 passed, 173 subtests passed
e34d7a2c1b50
```

涉及 lease、重启恢复、容量隔离或通知端到端语义的改动，还应运行对应 Gate 的 PostgreSQL 受控 probe。Probe 可能写入临时验收数据，必须确认输出包含清理完成和数据库恢复证据。

## 敏感配置

仓库只提供配置结构，真实凭据应留在本机或部署环境：

| 配置 | 处理方式 |
| --- | --- |
| 微信 AppSecret | 仅写入根目录 `.env` 或部署平台的 secret store，禁止提交 |
| TikHub API Key | 仅写入根目录 `.env` 或部署平台的 secret store，禁止提交 |
| 数据库密码、访问令牌、用户 openid | 视为敏感信息，禁止写入日志、文档、测试快照或 Git 历史 |
| 微信 AppID、模板 ID | 属于客户端可见标识符，不等同于 AppSecret；仍应通过现有配置入口维护，避免无必要复制 |
| 开发者工具个人配置 | 使用已忽略的 `miniapp/project.private.config.json` |

根目录 `.env` 和私有配置已被 `.gitignore` 排除。提交前仍应检查 `git diff --cached`，因为忽略规则无法撤回已经进入 Git 历史的秘密。

## 文档索引

- [产品说明](PRODUCT.md)
- [产品需求](PRD.md)
- [功能设计与交付规范](docs/FEATURE-DESIGN-DELIVERY.md)
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

README 只呈现当前可执行入口。详细冻结契约、历史 soak 记录、边界证据和验收输出保留在各 Gate 文档、`reports/` 与 `experiments/` 中。

## 当前限制

- Gate 0A 仍为 `DEGRADED`，不能据此宣称四个平台已经完成长期生产级真实性证明。
- 尚未批准生产部署；生产认证、密钥托管、域名和监控仍需独立验收。
- Gate 4 的视觉还原仍需在微信开发者工具与真机完成逐屏验收；设计稿不是自动通过的视觉验收。
- 抖音昵称搜索依赖可选的 TikHub 凭据与上游可用性；失效时必须显示明确的降级状态。
- 当前通知保证以持久化状态机、幂等边界和可恢复性为核心，不承诺端到端 exactly-once。

## License

许可证尚未确定。
