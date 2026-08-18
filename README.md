# 开场信 / StageLetter

> 跨平台主播订阅通知服务 — 微信小程序 + 7×24 服务端监控

## 这是什么

一个面向多用户的 SaaS 服务：

- 在微信小程序里订阅抖音、B 站、虎牙、斗鱼、Twitch 等平台的主播
- 服务端 7×24 监控这些主播的开播状态
- 主播开播时通过微信服务消息触达用户

不是直播录制器，不是直播聚合器，不是直播播放器 —— 是一台「订阅通知服务器」。

## 项目状态

**当前阶段:Gate 0(验证)与 Gate 1-3(实现)并行推进**

```
Gate 0A 微信 grant 实测   ✅ PASS(6 实验全绿,2026-08-12)
Gate 0B 4 平台适配器      ⏳ B站/抖音 PASS;虎牙缺 OFFLINE ground truth + 转换,斗鱼缺转换(8/13 13:21 4h soak 收)
Gate 0C 压测              🟢 C6 B站/抖音 14 条零限流已分析(规则 v0.1);虎牙/斗鱼 C6 待跑
Gate 1 Domain Core        ✅ 全验收(alembic + 状态机 + 1000 事件去重)
Gate 2 Detection Engine   🟢 Probe worker 运行中(4 平台真实探测,自动确认开播)
Gate 3 Notification       ✅ 核心完成(grant 决策树,14 组测试全绿)
Gate 4 小程序              📝 待启动
```

> **2026-08-13 里程碑**:项目更名 StageLetter(开场信)+ Gate 1-3 核心代码完成。Probe worker 已自动检测到 3 个真实直播间开播(bilibili/douyu/huya),创建 OPEN session + CONFIRMED_ONLINE 事件。

### Gate 0A(等用户实测)
- 脚手架完成,等用户完成模板审核后跑 `wechat_grant_demo.py`(预计 1-3 工作日)
- 实测结论填到 [reports/wechat_grant.md](./reports/wechat_grant.md)
- **v0.2 修正**:A3-5 已改名为"微信服务端是否强制验证真实订阅授权",**不再**声称后端可证明 `wx.requestSubscribeMessage` 弹窗真实发生;**真实 authority = `subscribeMessage.send` 返回码**,客户端 accept 仅作 optimistic ledger 输入;**已删**"前端签名 + 后端验签"方案
- **v0.2 修正**:A3-4 N>1 标 `UNEXPECTED_POSITIVE`,触发 ADR-002 增量更新,**不**自动降级到多通道;仅"无法可靠后台触达 / 用户必须不可接受地频繁操作"才触发通知架构降级

### Gate 0B — IN PROGRESS(7-state 框架已落地,多轮短浸泡 + 快照抽查)

**已完成**:
- ✅ 4 平台 adapter 升级到 7-state 返回:`ONLINE / OFFLINE / NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR / UNKNOWN`
- ✅ 跨平台共用分类器 `platform_adapters/common.py` + placeholder 短路(`is_placeholder()` 检测 uppercase 字符串,直接返 `NOT_FOUND` 不调 API)
- ✅ 24h 浸泡脚本支持 `--soak-type {correctness, transport, error-path}`,7 状态分布 + 状态转换 + live 转换分离统计
- ✅ 4 平台 transport 冒烟通过(`--soak-type transport --smoke` 60s 各跑一次,见 `experiments/data/*-24h-*.log`)
- ✅ **B 站真实状态转换已捕获**(1796297556 与 1993299468 均 ONLINE→OFFLINE,8/4→8/6 快照确认)— B 站 Correctness 接近 PASS

**浸泡轮次历史**(进程多次被杀,改为多轮短浸泡 + 快照抽查累积数据):
- 2026-08-02 12:44 启 4 平台 24h soak(`9l0S2l`/`LTcpGb`/`ZhwM37`/`tV38J1`)— 8/3 00:09-00:19 全被杀(11.4h 数据)
- 2026-08-04 13:54 启 B 站 72h soak(`bvPAE2`)— 16:44 被杀(3h 数据,且 B 站二次限流 25 分钟即触发)
- 2026-08-06 08:35 启 3 平台 6h soak(`KlT9wr` B站 / `OhCAhz` 虎牙 / `kdgzBq` 斗鱼)— 进行中
- 2026-08-12 22:27 启深夜 12h soak(虎牙/斗鱼,`supervise_soak.sh`)— 资源耗尽只跑 2h(00:27 收):虎牙 5 房间全 ONLINE 无转换,斗鱼 4 ONLINE + 1 OFFLINE(1000)无转换
- **2026-08-13 09:20 白天 4h soak(虎牙/斗鱼,`supervise_soak.sh huya/douyu 4 600`)— 13:21 正常收**(批次 2h×2):
  - 虎牙 50 样本全部 ONLINE(5 房间 × 10 次),**无 OFFLINE / 无转换 / 零错误**
  - 斗鱼 50 样本:40 ONLINE + 10 OFFLINE(房间 1000 全程 OFFLINE,证明 OFFLINE 探测正确),**无 ONLINE↔OFFLINE 转换**
  - 结论:**时间不是问题,样本主播不换状态才是**;两平台均仍缺标准 #3(真实转换)
- **2026-08-13 09:22-10:51 主动盯梢(`transition_watch.py` 盯 5 个刚开播房间 142761/31256203/30985600/17611785/32233,每 ~60s 探测,395 条)**:
  - 4 房间全程 ONLINE(79 次/房间);房间 142761 首采 ONLINE 后连续 78 次 PARSE_ERROR(页面结构与该房间不兼容,非状态转换)
  - **未捕获任何转换**;盯梢工具对个别房间 HTML 变体解析失败,需修 parse(候选:提升 eLiveStatus 兜底)

**等用户输入**:
- ⏳ 抖音 5 个真实 web_rid(`experiments/test_anchors/douyin.txt` 当前 5 个 PLACEHOLDER_DOUYIN_*)
  - 取得途径:抖音 App 分享短链 / 浏览器打开 `live.douyin.com/{web_rid}` 复制 19 位数字
- ⏳ 虎牙 OFFLINE ground truth(当前 5 个全 ONLINE,需至少 1 个已知不播房间 / 中尾部主播)
- ⏳ 斗鱼 1000 房间是否为权威 OFFLINE 基线(用户确认)

**Gate 0B 新 PASS 标准**(任何一条不满足就 NOT PASS):
1. 每平台 ≥ 5 个真实房间号(placeholder 不计)
2. 每平台 ≥ 1 个真实 ONLINE 主播 + ≥ 1 个真实 OFFLINE 主播 ground truth 已被人工对照平台官方客户端验证
3. ≥ 1 次真实状态转换(ONLINE↔OFFLINE 跨样本真实发生)
4. 24h 浸泡无转换则延长到 72h
5. 每个样本的 `state` 字段和平台官方客户端 ground truth 完全一致,**不允许** `state=OFFLINE` 的字段缺失/HTML 异常/placeholder 静默

**当前结果**(截至 2026-08-13 13:30,4h soak + 盯梢收尾):

| 平台 | 样本累计 | 7-state 分布 | Ground Truth | 真实转换 | PASS 状态 |
|------|---------|-------------|--------------|----------|-----------|
| B 站 | 316+ | ONLINE 155 / OFFLINE 100 / PARSE_ERROR 61 | ≥1 ONLINE + ≥1 OFFLINE ✅ | **4 次 ✅ 双向**(2 下播 + 2 开播,时间戳精确) | **Transport ✅ / Correctness ✅ PASS** |
| 抖音 | 90 | ONLINE 34 / OFFLINE 56 | ≥1 ONLINE + ≥1 OFFLINE ✅ | **4 次 ✅**(00:48/01:48/02:23/03:33 下播) | **Transport ✅ / Correctness ✅ PASS** |
| 虎牙 | 191+ | ONLINE 166 / PARSE_ERROR 25(旧样本) | ≥1 ONLINE ✅ / OFFLINE ❌ | 0 | Transport ✅ / Correctness ⚠️ NOT PASS(缺 OFFLINE ground truth + 转换) |
| 斗鱼 | 191+ | ONLINE 133 / OFFLINE 33 / PARSE_ERROR 25 | ≥1 ONLINE + ≥1 OFFLINE ✅(1000 浏览器验证) | 0 | Transport ✅ / Correctness ⚠️ NOT PASS(缺真实转换) |

> **2026-08-13 收尾结论**:白天 4h soak 两平台均正常完成(零错误、零限流),但**仍无真实状态转换**。斗鱼房间 1000 全程 OFFLINE(10/10 采样)证明 OFFLINE 探测正确,但 OFFLINE 是静态基线不是转换。**Gate 0B 唯一阻塞项 = 标准 #3(≥1 次真实转换)**:虎牙还叠加缺 OFFLINE 样本(标准 #2)。下一步建议:换晚间黄金档中尾部主播(直播时长 1-3h,下播概率高)做高频盯梢;盯梢工具修复 142761 类房间解析失败后重跑。

> **2026-08-13 策略调整(回应"为什么 12h"问题)**:Gate 0B 唯一缺的是标准 #3(≥1 次真实状态转换)。12h 是"赌运气等转换",改为**主动捕获**:
> - 夜间 12h soak(8/12 22:27 启)因系统资源耗尽只跑 2h(虎牙 5 房间全 ONLINE 无转换,斗鱼 1 OFFLINE + 4 ONLINE 无转换)——2h 数据已证明**时间短不是问题,样本主播没转换才是**
> - 白天重启 **4h soak**(8/13 09:20 启,13:21 正常收)— 虎牙/斗鱼各 50 样本,零错误,但样本主播全程不换状态,**仍无转换**
> - **主动盯梢**:用批量列表对比发现"刚开播"主播(ONLINE 候选 5 个),每 60s 高频探测(transition_watch.py,8/13 09:22-10:51 共 395 条)— 4 房间全程 ONLINE,**未捕获转换**;142761 房间连续 PARSE_ERROR(解析器不兼容该房间 HTML,需修)
> - 虎牙列表对比法本身有噪音(列表是推荐排序,房间消失 ≠ 下播,已验证 6 个候选均仍 ONLINE)— 再次确认 C3 结论:列表只能当 ONLINE 单侧证据

> 🎉 **抖音 web_rid 自主获取成功(2026-08-06 晚)**:playwright 监听 `webcast/feed` 推荐流 API,提取 item 顶层 `web_rid` 字段(10-13 位;19 位 id_str 是内部 room_id,两者不同)。5 个 web_rid 全部 ONLINE 验证(adapter + 页面 video 双重确认),6h correctness soak 已启动。**同时发现抖音 enter API 改版**(房间详情移到 `data.data[0]`),adapter 已适配。

> ⚠️ **重要实测发现(限流,直接进 Gate 0C 输入)**:B 站/虎牙/斗鱼对匿名持续轮询都有连接级限流(非 429,是 `HTTPSConnectionPool` 超时)。**B 站限流阈值与 IP 信誉负相关**:首犯 8.3h 触发,冷却 2 天后累犯 25 分钟即触发。V1 生产必须引入登录态/cookie 池/UA 池/多出口 IP + 自动退避。详见各 capacity.md §2/§3。

**4 平台 capacity.md 同步更新**:`reports/{bilibili,douyin,huya,douyu}.md` 已重写,明确标注 Transport ✅ / Correctness ⚠️ / NOT TESTED / PARTIAL,删除了"verify stream URL signature"(StageLetter 是订阅通知服务,不流不录不播)。B 站"~2.5s intentional delay"已改为"~2.5s observed,cause unknown,Gate 0C causal experiment"。

- v0.2 立项包 13 个文档已发布,3 P0 + 8 P1 问题已修正。详见 [CHANGELOG.md §v0.2](./CHANGELOG.md)。

**v0.2 重大变更**:
- 微信通知模型从"伪造额度(初始 8/季度重置/refresh+8)"改为"乐观 grant 账本"
- Gate 0 拆分为 0A → 0B → 0C → 0D → 0E,**0A 排第一**
- 引入分级轮询(hot / warm / cold)
- 按平台分级 SLA(Twitch < 30s / 其他 < 5-8min)
- V1 主播上限由 Gate 0C 实测决定(不再假定 18,000)

进入任何正式产品代码之前,必须先通过 Gate 0 全部 5 关验证。详见 [GATE-0.md](./GATE-0.md)。

## 文档索引

| 文档 | 作用 |
|------|------|
| [CHANGELOG.md](./CHANGELOG.md) | **v0.2 修订记录(P0/P1 修正清单)** |
| [PRODUCT.md](./PRODUCT.md) | 产品愿景、定位、反愿景 |
| [PRD.md](./PRD.md) | V1 产品需求文档 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 系统架构与技术选型 |
| [DATA-MODEL.md](./DATA-MODEL.md) | 数据库模型 |
| [PLATFORM-ADAPTER-SPEC.md](./PLATFORM-ADAPTER-SPEC.md) | 平台适配器规范 |
| [WECHAT-NOTIFICATION-SPEC.md](./WECHAT-NOTIFICATION-SPEC.md) | 微信通知机制 (v0.2 grant 模型) |
| [API-SPEC.md](./API-SPEC.md) | REST API 规范 |
| [SECURITY.md](./SECURITY.md) | 安全考虑 |
| [NON-GOALS.md](./NON-GOALS.md) | V1 明确不做 |
| [ROADMAP.md](./ROADMAP.md) | 路线图与里程碑 |
| [GATE-0.md](./GATE-0.md) | Gate 0 (0A-0E) 技术验证任务书 |

## 核心原则

1. **只做一件事**:订阅主播,开播通知。
2. **多租户模型**:1 万用户 × 10 订阅 = 18,000 个主播去重检测(实际容量由 Gate 0C 倒推)。
3. **微信通知是用户行为产物** (v0.2):不是配额,是用户每次主动 accept 产生的 grant。初始 0,无季度重置。详见 [WECHAT-NOTIFICATION-SPEC.md §2](./WECHAT-NOTIFICATION-SPEC.md)。
4. **平台适配器可降级**:任一平台故障不影响其他平台,可手动 disable。
5. **状态机避免抖动**:SUSPECT → CONFIRMED 二次确认,不会反复上下线。
6. **事件可重放**:所有 LiveEvent 落库,支持事后补偿与审计。
7. **分级轮询** (v0.2):hot / warm / cold,优化总承载量。
8. **不诚实的产品承诺**:SLA 按平台分级,不假装"< 3min 统一"。

## 技术栈

- **微信端**：Taro 3 + React + TypeScript（待 Gate 0 验证后再定）
- **服务端**：Python 3.13 + FastAPI
- **数据库**：PostgreSQL 15+
- **队列 / 缓存**：Redis + Dramatiq
- **任务调度**：APScheduler（单实例 → 分布式锁）
- **部署**：Docker Compose

详细选型见 [ARCHITECTURE.md §4](./ARCHITECTURE.md)。

## 开始 Gate 0A(当前阶段)

如果你正在准备 / 跑 Gate 0A 实验,按以下顺序:

1. [WECHAT-TEST-ACCOUNT.md](./WECHAT-TEST-ACCOUNT.md) — 注册测试号 + 申请订阅模板 + 配置 .env
2. [experiments/README.md](./experiments/README.md) — 实验脚本使用说明
3. 跑完后回填 [reports/wechat_grant.md](./reports/wechat_grant.md)

实验通过后,在 [GATE-0.md](./GATE-0.md) §Gate 0A 验收处勾选,即可进入 Gate 0B(单平台 adapter prototype,不依赖微信,可以并行启动)。

## 快速开始

> 当前阶段没有可运行的产品代码。  
> 先读 [GATE-0.md](./GATE-0.md),按任务清单做完技术验证再进入正式开发。

## 参考项目

下列项目仅作架构与实现参考，**禁止直接复制代码**到本项目（部分项目 License 限制或声明禁止商用）：

- [DouyinLiveRecorder](https://github.com/ihmily/DouyinLiveRecorder) — 多平台适配器最成熟
- [aio-dynamic-push](https://github.com/nfe-w/aio-dynamic-push) — 检测/推送模块分离设计（禁止商用）
- [WebMoniter](https://github.com/666fy666/WebMoniter) — 后端工程组织参考

## 许可

待定。
