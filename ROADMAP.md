# ROADMAP.md — 路线图

## 总览（当前执行状态）

```
Gate 0 — Feasibility Evidence      ⚠️ DEGRADED（历史证据，不补写缺口）
──────────────────────────────────────────
Gate 1 — Domain Core              ✅ PASS / CLOSED
Gate 2 — Detection Engine         ✅ PASS / CLOSED
Gate 3 — Notification Engine      ✅ PASS / CLOSED
Gate 4 — 微信小程序                 ✅ PASS / CLOSED
Gate 5 — Admin / Observability      ✅ PASS / CLOSED
──────────────────────────────────────────
V1 Alpha 内测准备                  🚧 CURRENT
V1 公开上线                         2-4 周缓冲
──────────────────────────────────────────
V1.1: P1 平台 + V1.2 优化         4-6 周
V2:  跨平台身份合并 + 静默时间      2-3 月
V3:  创作者订阅情报中心            6+ 月
```

> Gate 0 的原始计划和实验记录继续保留用于审计，但当前开发入口是 Gate 5；
> Gate 1–3 的最终冻结证据分别以 Gate 文档和自动化验收为准。

## Gate 0 — 技术可行性 (v0.2 拆 0A-0E)

**目标**: 验证 v0.2 grant 模型 + 单主播 adapter + 平台容量 + 72h 稳定性 + 端到端通知

**任务**: 详见 [GATE-0.md](./GATE-0.md)

**整体验收**(必须全部通过):
- [ ] Gate 0A: 微信 grant 模型真机验证,产品定位确定
- [ ] Gate 0B: 4 个平台 adapter 各自 5 个主播 × 24h
- [ ] Gate 0C: 每平台 `capacity.md` 完整,V1 主播上限确定
- [ ] Gate 0D: 72h 集成稳定
- [ ] Gate 0E: 状态机 + 端到端通知

**任意一关不通过** → 不进入 Gate 1。

## Gate 1 — Domain Core

**时长**：1-2 周  
**目标**：数据模型 + 状态机 + 去重（纯后端，不依赖真实平台）

**任务**：
- PostgreSQL + SQLAlchemy 2.0
- 10 张核心表 + Alembic migration
- LiveStateEngine（状态机 + 二次确认）
- 单元测试覆盖状态机
- 单元测试覆盖去重

**输出**：
- 完整 data-model（migration 可跑）
- 状态机 100% 测试覆盖
- 单一进程内可手动制造 LiveSession
- 集成测试：注入 1000 个 LiveEvent，验证去重不重不漏

**验收**：
- [x] `alembic upgrade head` 从空库成功(2026-08-13,迁移 5354a9ed7741)
- [x] 状态机所有转换都有测试(`tests/test_live_session_engine.py` 4 组全过)
- [x] 1000 个 LiveEvent fan-out 后不重复通知(`tests/integration_1000_events.py` 全过)
- [x] 人工注入抖动(online→offline→online 5s 内)只产生一次 CONFIRMED_ONLINE(`test_jitter_handling` + 引擎测试)

## Gate 2 — Detection Engine

**时长**:2-3 周  
**目标**:完整检测层,平台隔离、可降级

**任务**:
- APScheduler + Redis queue
- 平台 worker 拆分(worker-douyin / worker-bilibili / ...)
- **v0.2 新增**: 分级轮询(hot / warm / cold)
- 适配器健康度监控
- 限流(aiolimiter)
- 重试(tenacity)
- 熔断(DEGRADED 自动降频,**仍通知,标低 confidence**)
- platform_health 自动更新
- **v0.2 调整**: `probe_runs` 轻量 probe telemetry 必须纳入 Gate 2(不再是 V1.1 可选)

**输出**:
- 按平台实测 `max_anchors` 的去重检测 demo(目标数由 Gate 0C 决定)
- 平台健康页可看
- 任一平台 disable 不影响其他
- 单平台故障可自动 DEGRADED → DISABLE
- probe_runs 表持续写入

**验收**：✅ PASS / CLOSED。最终证据见 [GATE-2.md](./GATE-2.md)。

## Gate 3 — Notification Engine

**时长**:2-3 周  
**目标**:真正能"主播开播 → 微信通知"

**任务**:
- 微信订阅消息模板申请(提前 Gate 0A 完成后立刻申请)
- **v0.2 重构**: grant 模型(wechat_subscription_grants 表,乐观记账 + reconciliation)
- Fan-out(LiveEvent → notification_jobs)
- WeChat 投递 worker(grant 决策树)
- In-App 投递 worker(兜底)
- Delivery log
- 失败重试(指数退避)
- 微信 4xx → grant 失效 / 5xx → grant 保留
- **v0.2 新增**: 微信模板独立 disable 能力

**输出**:
- 真机收到开播通知
- grant 正确消耗与记录
- request-grant 流程跑通
- 微信 43101 / 45009 / 40037 等错误正确处理

**验收**：✅ PASS / CLOSED。真实 provider `errcode=0` 与手机收件证据复用
Gate 1.6；grant、40037、fallback、restart、多 worker、history 和详情路径契约
均已验收，见 [GATE-3.md](./GATE-3.md)。真实点击/页面交互属于 Gate 4，
不得用静态路径测试冒充。

## Gate 4 — 微信小程序

**时长**:2-3 周  
**目标**:用户能完整使用 4 个核心页面

**任务**:
- 复用当前原生微信小程序（WXML / WXSS / JavaScript），不重新迁移到 Taro
- 微信登录集成
- 4 个核心页面:
  - 首页(正在直播 / 最近开播)
  - 添加订阅
  - 我的订阅
  - 我的(grant 余额 / 通知记录 / 「开启更多提醒」按钮)
- 「开启更多提醒」UI:触发 wx.requestSubscribeMessage
- 与后端 API 联调

**输出**:
- 4 个页面 demo
- 完整用户路径:登录 → 添加 → 开播收到通知 → 查看详情
- 真机预览

**验收**:
- [ ] 微信登录可用
- [ ] 粘贴抖音链接 → 添加成功(同时弹 grant 授权)
- [ ] 主播开播 → 真机收到微信通知
- [ ] 点通知 → 跳详情页
- [ ] 我的页面显示 grant 余额(不是"剩余配额")

## Gate 5 — Admin / Observability

**时长**：1-2 周  
**目标**：运营可观测、可干预

**任务**：
- Admin Web（FastAPI + Jinja2 或独立 React）
- 平台健康 dashboard
- 适配器 disable/enable
- 用户列表
- 通知记录查询
- 错误日志聚合
- Prometheus metrics 暴露
- Grafana dashboard（V1.1）

**输出**：
- Admin 完整可用
- 至少 4 个核心页面

**验收**：✅ PASS / CLOSED。受保护的健康页、审计化的平台 disable/restore、
有界用户/订阅/投递查询、固定维度错误聚合和独立引擎重启读取已验收；最终
证据见 [GATE-5.md](./GATE-5.md)。Prometheus/Grafana 保持为 V1.1 的独立工作，
不得将其缺席伪装为已完成。

## V1 Alpha 内测

**时长**：2 周  
**目标**：100 用户真实使用 1 周

**任务**：
- 招募 100 内测用户
- 监控关键指标
- 收集反馈
- 修复 P0 bug

**验收**：
- [ ] 100 用户全部成功完成"添加订阅 → 收到通知"
- [ ] 没有 P0 故障（数据丢失、通知漏发等）
- [ ] 关键指标达标（性能、错误率）

## V1 公开上线

**时长**：2-4 周缓冲

**任务**：
- 微信小程序提交审核
- 灰度放量（10% → 50% → 100%）
- 监控告警就位
- 客服话术准备

**验收**：
- [ ] 微信审核通过
- [ ] 灰度放量无重大事故
- [ ] 告警链路打通

---

## V1.1 / V1.2（V1 之后 1-2 月）

- 快手 / Twitch P1 平台接入
- 性能优化（缓存、批量探测）
- 通知记录导出
- 通知点击转化率分析
- 微信模板 A/B 测试

## V2（V1 之后 2-3 月）

- 跨平台身份合并（同一主播抖音+B 站合并到一条 anchor）
- 静默时间段
- 通知额度购买（`period='manual'` 启用）
- H5 端
- 主播动态（新视频、专栏）

## V3+（V1 之后 6+ 月）

- 创作者订阅情报中心
- 直播预约
- 主播情报雷达（跨平台热度、节奏）
- 海外平台
- 付费会员 / 高级功能
- 移动端原生 App

---

## 进度追踪

每个 Gate 完成时：
1. 在 GitHub 提 release
2. 更新 ROADMAP.md
3. 在 SOUL.md / 项目 MEMORY 留 working note
4. 启动下一个 Gate

## 风险与备案

| 风险 | 触发条件 | 备案 |
|------|---------|------|
| 抖音接口持续升级 | Adapter 错误率 > 30% 持续 7 天 | 减小抖音优先级，优先 P1 平台 |
| 微信模板审核不过 | Gate 3 阻塞 | 用站内消息作为主渠道，微信做备选 |
| 1 万用户容量不足 | 上线 1 月内 DAU > 5000 | 提前优化检测层；引入 worker 横向扩容 |
| 平台法律风险 | 收到平台投诉 | 仅做"订阅通知"，不存内容；联系法务 |
| 团队人手不足 | 任一 Gate 延期 > 2 周 | 砍 P1 平台、砍 Admin、聚焦核心通知链路 |

## 决策记录

每个 Gate 结束时记录：
- 实际耗时 vs 计划
- 重大决策与原因
- 发现的坑
- 下个 Gate 调整

格式参考 ADR（Architecture Decision Record）。
