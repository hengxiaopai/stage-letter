# GATE-0.md — Gate 0 技术可行性

> **v0.2 重大重构**: 拆分为 **0A → 0B → 0C → 0D → 0E**,**0A 微信通知真实性实验排第一**。  
> 详见 [CHANGELOG.md §v0.2](./CHANGELOG.md)。

## 0. 目标

在写任何正式产品代码前,用最小代码证明:

1. **微信通知能稳定送达**(0A)
2. **单主播 Adapter 能正确检测**(0B)
3. **平台能稳定承载规模流量**(0C)
4. **整套系统 72h 稳定运行**(0D)
5. **状态机 + 端到端通知链路正确**(0E)

任意一关不通过,不进入 Gate 1。

## 1. 不做

- ❌ 不写小程序 UI
- ❌ 不写正式后端(FastAPI 项目骨架)
- ❌ 不部署上线(仅本地 + 个人测试号)
- ❌ 不做用户系统(脚本驱动)
- ❌ 不写正式数据库 schema(脚本 + 内存即可)

## 2. Gate 拆分

```
Gate 0A — 微信通知真实性实验           ←  第一关,验证 v0.2 模型假设
   ↓ pass
Gate 0B — 单主播 Adapter 正确性
   ↓ pass
Gate 0C — 平台吞吐 / 风控 / 容量      ←  关键,决定 V1 主播上限
   ↓ pass
Gate 0D — 72h 稳定性
   ↓ pass
Gate 0E — 状态机 + 端到端
   ↓ pass
GO / CONDITIONAL GO / NO-GO
```

每个 Gate 内部三个阶段:

```
冒烟 2h → 稳定性 24h → 最终 72h
```

> v0.1 写了"24h"和"72h"在不同位置,自相矛盾。v0.2 统一为:任何 Gate 先冒烟 2h,再跑 24h,再跑 72h。

---

## Gate 0A — 微信通知真实性实验

### 目标

> **真机验证 v0.2 grant 模型假设是否成立**。

### 任务

A1. **注册小程序测试号**(用户操作,WorkBuddy 提供步骤文档)
A2. **申请订阅消息模板**:`开播提醒` (thing1 / thing2 / time3)
A3. **真机验证**(用户操作,WorkBuddy 写脚本):

| 实验 | 期望 |
|------|------|
| 授权一次,立即发第 1 条 | ✅ 收到 |
| 不重新授权,发第 2 条 | ❌ 失败(grant 已耗尽) |
| 重新授权,发第 3 条 | ✅ 收到 |
| 用户点"总是保持以上选择"后再发 | 实际行为?**(关键,需要真机记录)** |
| 客户端伪造 accept(直接调 request-grant API) | 服务端 + 微信侧真实表现? |
| 用户拒收某主播通知后,该主播开播 | 仍 in-app,不弹微信 |

### 验收

- [x] 实验 A3-1 / A3-3 通过(均 errcode=0,送达确认)
- [x] 实验 A3-2 失败原因明确(grant 真的被消耗了,errcode=43101)
- [x] 实验 A3-4 / A3-5 / A3-6 行为记录完整
- [x] **得出结论**:V1 微信通知模型是否需要调整
  - **结论:GATE 0A PASS(2026-08-12)**
  - grant 模型**核心成立**:一次授权 = 一条消息,耗尽后 43101
  - **新增发现 GRANT_CUMULATIVE**:连续授权 N 次 = 储备 N 条额度(UNEXPECTED_POSITIVE → ADR-002 增量更新,V1 可设计"授权储备"交互避免反复弹窗)
  - send 端是唯一真实 authority(伪造 accept 在余额为 0 时必返 43101)
  - 拒收后微信侧即时不送达(43101)
  - → **V1 维持"微信开播提醒器"定位**,进入 Gate 0B

> 完整实测记录见 [reports/wechat_grant.md](./reports/wechat_grant.md)(2026-08-12 正式号 wx370fb6f14d4a4a26 末4位 4a26 实测)

### 输出物

- `experiments/wechat_grant_demo.py`
- `experiments/wechat_trust_test.py`(伪造测试)
- `reports/wechat_grant.md` (含 A3-4 ~ A3-6 实测记录)

---

## Gate 0B — 单主播 Adapter 正确性

### 目标

> 每个 P0 平台能在本地稳定检测 5 个主播。

### 任务

B1. **抖音 Adapter Prototype**

- [ ] 解析 `https://v.douyin.com/xxx`(短链)
- [ ] 解析 `https://www.douyin.com/user/xxx`(长链)
- [ ] 检测是否在直播
- [ ] 5 个主播 × 冒烟 2h
- [ ] 5 个主播 × 24h(稳定性)

B2. **B 站 Adapter Prototype**

- [ ] 解析 `https://space.bilibili.com/{uid}`
- [ ] 解析 `https://live.bilibili.com/{room}`
- [ ] 检测直播
- [ ] 5 × 2h, 5 × 24h

B3. **虎牙 Adapter Prototype**

- [ ] 解析 `https://www.huya.com/{room}`
- [ ] 检测直播
- [ ] 5 × 2h, 5 × 24h

B4. **斗鱼 Adapter Prototype**

- [ ] 解析 `https://www.douyu.com/{room}`
- [ ] 检测直播
- [ ] 5 × 2h, 5 × 24h

### 验收

> **v0.2 修正(2026-08-02)**:7-state 框架已落地,所有 adapter 必须返回 7 状态之一。**placeholder / 字段缺失 / HTML 异常不得自动视为 OFFLINE**。具体 PASS 标准见下,任一不满足即 NOT PASS。

**7-state 返回值**:`ONLINE / OFFLINE / NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR / UNKNOWN`,实现见 `platform_adapters/common.py` 的 `LiveStatus` 枚举 + `classify_platform_status()` / `classify_error()` / `is_placeholder()`。

**硬性 PASS 标准**(所有项必须满足):
- [ ] 4 个平台各自 **≥ 5 个真实房间号**(placeholder 不计入 PASS,会被 `is_placeholder()` 短路返 `NOT_FOUND` 不调 API)
- [x] 每平台 **≥ 1 个真实 ONLINE 主播** + **≥ 1 个真实 OFFLINE 主播** ground truth 已被人工对照平台官方客户端验证(B站/抖音/斗鱼✅;虎牙缺 OFFLINE)
- [ ] **≥ 1 次真实状态转换**(ONLINE↔OFFLINE 跨样本真实发生)。**24h 浸泡无转换则延长到 72h**(B站 4 次 / 抖音 4 次;虎牙/斗鱼 0)
- [x] 每个样本的 `state` 字段和平台官方客户端 ground truth **完全一致**(4h soak 零错误,斗鱼 1000 静态 OFFLINE 验证通过)
- [x] **不允许**字段缺失 / HTML 异常 / placeholder / 网络抖动静默归类为 OFFLINE — 这些场景必须独立返 `NOT_FOUND` / `PARSE_ERROR` / `UNKNOWN`
- [ ] 4 个平台 24h 持续运行无崩溃(目前最长为分段累计,未连续 24h)
- [ ] parse_url 覆盖文档列出的所有 URL 形式
- [x] 每个 adapter 有 `capacity.md`(0B 阶段可只填 1 + 7 + 8 节,完整填在 Gate 0C)

**当前状态**:**IN PROGRESS**(截至 2026-08-13 13:30,白天 4h soak + 盯梢收尾)
- B 站:Transport ✅ / Correctness ✅ PASS
- 抖音:Transport ✅ / Correctness ✅ PASS
- 虎牙:Transport ✅ / Correctness ⚠️ **NOT PASS**(缺 ≥1 OFFLINE ground truth;0 转换)
- 斗鱼:Transport ✅ / Correctness ⚠️ **NOT PASS**(0 转换;OFLLINE 基线 1000 已验证)

> **2026-08-13 收尾结论**:白天 4h soak(09:20-13:21)虎牙/斗鱼各 50 样本零错误零限流,但样本主播全程不换状态,**仍未捕获真实转换**;盯梢(395 条)4 房间全程 ONLINE,142761 连续 PARSE_ERROR(解析器不兼容,需修)。**Gate 0B 阻塞项 = 标准 #3(真实转换)**;虎牙另有标准 #2(OFFLINE 样本)未满足。B站/抖音已 PASS,可先行进入 Gate 0C B站/抖音部分。

### 输出物

- `platform_adapters/{douyin,bilibili,huya,douyu}/adapter.py`
- `experiments/{platform}_24h.py`
- `reports/{platform}.md`(0B 部分)
- `platform_adapters/{platform}/capacity.md`(0B 阶段,只填 1)

---

## Gate 0C — 平台吞吐 / 风控 / 容量 (v0.2 关键)

### 目标

> **实测每个平台的持续 QPS、风控阈值、batch 能力**。  
> 这是 V1 主播上限的真实依据。

### 任务

C1. **持续 QPS 压测**

| 平台 | 测什么 |
|------|--------|
| 抖音 | 单 IP 1 req/s × 10min 是否 429?2 req/s?5 req/s? |
| B 站 | 单 IP / 单 token 持续 5 req/s / 10 req/s / 20 req/s |
| 虎牙 | 同上 |
| 斗鱼 | 同上 |

C2. **风控阈值**

- 403 阈值(单 IP 连续多少请求后被封)
- 429 阈值(单 IP QPS 上限)
- 封禁恢复时间(停多久能恢复)
- 代理 IP 后的恢复效果

C3. **Batch Endpoint 调研 (关键)**

| 平台 | 有无 batch endpoint | 单请求可查多少主播 |
|------|---------------------|-------------------|
| 抖音 | ? | ? |
| B 站 | ?(可能 `/xlive/web-room/v1/index/getRoomPlayInfo` 批量?) | ? |
| 虎牙 | ? | ? |
| 斗鱼 | ? | ? |

> **若 B 站 / 虎牙 / 斗鱼有 batch endpoint,容量模型完全不同,V1 18,000 主播才有可能**。

C4. **cookie / 签名 / UA / 风控账号依赖**

每平台必须明确:
- 是否需要 cookie?
- 是否需要 sign / x-s / a-bogus 等签名?
- 是否需要真实 UA?
- 是否需要特定 IP 段?

C5. **填写完整 `capacity.md`**

每平台输出完整 8 节 capacity 报告(详见 [PLATFORM-ADAPTER-SPEC §13](./PLATFORM-ADAPTER-SPEC.md))。

C6. **连接超时 vs RATE_LIMITED 因果实验(2026-08-06 新增,来自 Gate 0B 实测)**

> **背景**:Gate 0B 实测发现 B 站/虎牙/斗鱼对匿名持续轮询的限流**不是 HTTP 429**,而是:
> - **慢响应限流**:虎牙 8/2 13:29 起每请求 300s 才返回(数据正确但延迟拉满)
> - **连接级拒连**:8/2 21:00 起 `HTTPSConnectionPool` 连接超时(-1),~2h 后恢复
> - **累犯加速**:B 站首犯 8.3h 触发;冷却 2 天后累犯 25 分钟即触发(8/4 实测)
>
> 当前 `classify_error` 把 -1 → PARSE_ERROR(保守)。**本实验要回答**:
> 1. 连接超时连续 N 次(如 3 次)后,是否应升级为 `RATE_LIMITED`?
> 2. 慢响应(延迟 > 60s)是否也算限流信号?
> 3. 各平台恢复时间是否随累犯延长?自动退避参数(停 2h / 4h / 24h)怎么定?
>
> 实验方法:单 IP 匿名,固定频率轮询,记录"首犯时间 / 累犯时间 / 恢复时间"曲线。

### 验收

- [ ] 每个平台 `capacity.md` 完整填写
- [ ] 每个平台测得 `sustained_qps`
- [ ] C6 实验完成:给出"连接超时→RATE_LIMITED"判定规则 + 退避参数
- [ ] **V1 主播上限计算结果**:
  - max_anchors_per_platform = sustained_qps × polling_interval
  - total_max_anchors = Σ 各平台
  - 是否满足 V1 目标(如 18,000)?

### 输出物

- `experiments/throughput_test/{platform}.py`
- `experiments/batch_probe/{platform}.py`
- `reports/capacity_summary.md`(综合 4 个平台的 capacity)
- `platform_adapters/{platform}/capacity.md`(完整)

### 决策点

Gate 0C 完成后必须做一次决策:

- **GO**: V1 主播上限满足产品目标,继续 Gate 0D
- **CONDITIONAL GO**: 总上限不够,降低 V1 目标(比如 5,000 而非 18,000)继续
- **NO-GO**: 容量模型根本无法支撑产品(比如抖音完全无法 1 req/s 持续),重新评估产品形态

---

## Gate 0D — 72h 稳定性

### 目标

> 完整适配器 + 调度器 + Redis queue 跑 72h 无重大故障。

### 任务

- [ ] 集成 4 个 P0 平台 adapter
- [ ] APScheduler 调度(简化版)
- [ ] Redis queue + Dramatiq
- [ ] 20 个主播(每平台 5 个)
- [ ] 72h 持续运行
- [ ] 监控成功率 / 延迟 / 错误类型
- [ ] 故障注入测试:
  - 模拟平台 5xx → adapter 重试 + 退避
  - 模拟 Redis 短暂不可用 → 不丢失任务
  - 模拟 worker 崩溃 → 任务可被其他 worker 接管

### 验收

- [ ] 72h 持续无崩溃
- [ ] 错误率 < 5%
- [ ] 检测延迟:开播 < 平台 SLA p95(详见 [PRD §N1](./PRD.md))
- [ ] 故障注入测试全部通过

### 输出物

- `experiments/integration_72h.py`
- `reports/stability_72h.md`

---

## Gate 0E — 状态机 + 端到端

### 目标

> 验证状态机抗抖动 + 端到端通知链路。

### 任务

E1. **状态机原型**

- [ ] 实现 `OFFLINE → SUSPECT_ONLINE → ONLINE`
- [ ] 实现 `ONLINE → SUSPECT_OFFLINE → OFFLINE`
- [ ] 100% 单元测试覆盖所有转换
- [ ] 注入抖动(online→offline→online 5s 内)只产生 1 次 CONFIRMED_ONLINE
- [ ] SUSPECT 期间不产生事件

E2. **端到端 demo**

- [ ] 把 0B / 0C / 0D 的 adapter 接入状态机
- [ ] 状态机 → LiveEvent → mock notification(不接真微信,用 log)
- [ ] 验证:1 主播开播 → 1 用户模拟收到(写 log)
- [ ] 验证:抖动不重复通知

### 验收

- [ ] 状态机测试 100% 通过
- [ ] 端到端 demo 跑通 1 个主播 1 个用户 24h
- [ ] 抖动测试不漏不重

### 输出物

- `core/state_machine.py`
- `experiments/state_machine_test.py`
- `experiments/end_to_end_demo.py`
- `reports/state_machine.md`
- `reports/end_to_end.md`

---

## 3. 整体验收

### 必须全部通过才能进入 Gate 1

- [ ] 0A 微信通知模型验证通过,产品定位确定
- [ ] 0B 4 个平台 adapter 各自 5 个主播 × 24h 通过
- [ ] 0C 每平台 `capacity.md` 完整,V1 主播上限确定
- [ ] 0D 72h 集成稳定
- [ ] 0E 状态机 + 端到端通过

### 任意一关不通过

→ 不进入 Gate 1,回到对应 Gate 修补。

## 4. 最终输出物

```
stage-letter/
├── platform_adapters/
│   ├── douyin/
│   │   ├── adapter.py
│   │   ├── parser.py
│   │   └── capacity.md        ← 0C 填完整
│   ├── bilibili/
│   ├── huya/
│   └── douyu/
├── core/
│   └── state_machine.py
├── experiments/
│   ├── wechat_grant_demo.py
│   ├── wechat_trust_test.py
│   ├── {platform}_24h.py
│   ├── throughput_test/{platform}.py
│   ├── batch_probe/{platform}.py
│   ├── integration_72h.py
│   ├── state_machine_test.py
│   └── end_to_end_demo.py
├── reports/
│   ├── wechat_grant.md
│   ├── {platform}.md
│   ├── capacity_summary.md
│   ├── stability_72h.md
│   ├── state_machine.md
│   ├── end_to_end.md
│   └── SUMMARY.md             ← 一句话"GO / CONDITIONAL GO / NO-GO"
└── GATE-0-RESULT.md           ← 总结报告
```

## 5. 估计时间

- Gate 0A:2-3 天(主要等用户真机操作)
- Gate 0B:3-4 天
- Gate 0C:3-5 天(关键,最不确定)
- Gate 0D:3-5 天(72h 跑起来 + 观察)
- Gate 0E:2-3 天

总计:**2-3 周**(取决于抖音 / 微信稳定性)。

## 6. 风险

| 风险 | 应对 |
|------|------|
| Gate 0A 显示微信不可用 | 产品定位调整(详见 [WECHAT-NOTIFICATION-SPEC §5](./WECHAT-NOTIFICATION-SPEC.md)),但架构已支持 |
| Gate 0C 容量不足 | 降 V1 目标(5,000 → 1,000 主播),优先 batch 强的平台 |
| 抖音接口反爬升级 | 准备 2-3 套方案,参考 DouyinLiveRecorder 迭代 |
| 微信模板审核失败 | 准备多套模板文案;先申请、不阻塞 |
| 个人测试号无法验证 | 至少找 1-2 个真机用户协助 |
| 72h 跑挂 | 缩短到 24h 重新跑,排障 |

## 7. 与其他文档的关系

- 状态机设计:[ARCHITECTURE.md §5.3](./ARCHITECTURE.md)
- 适配器接口:[PLATFORM-ADAPTER-SPEC.md §3](./PLATFORM-ADAPTER-SPEC.md)
- capacity.md 模板:[PLATFORM-ADAPTER-SPEC.md §13](./PLATFORM-ADAPTER-SPEC.md)
- 微信通知:[WECHAT-NOTIFICATION-SPEC.md](./WECHAT-NOTIFICATION-SPEC.md)
- 数据模型:[DATA-MODEL.md](./DATA-MODEL.md)
- SLA 分级:[PRD.md §N1](./PRD.md)