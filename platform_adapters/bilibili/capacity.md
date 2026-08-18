# Bilibili Adapter Capacity — Gate 0B / 0C 阶段

> **本文件分阶段填写**:
> - §1 单请求性能 — Gate 0B 阶段必填
> - §2 批量 QPS / §3 反爬 / §4 容量推算 — Gate 0C 阶段填
>
> **状态总览**(Gate 0B 阶段,2026-08-02 更新):
> - Transport: ✅ API 调通,errcode 处理正常
> - Correctness: ⚠️ IN PROGRESS — **已验证 ONLINE + OFFLINE 双路径**(3 个 live room 连续 11.4h ONLINE,2 个 space uid 连续 OFFLINE),**缺 ≥1 真实状态转换**
> - Placeholder 返回: 全部 NOT_FOUND(已正确短路,不再视为 OFFLINE)
>
> ⚠️ StageLetter 不拉流、不录制、不播放,**没有 stream URL 任务**(原 §3 误列,已删)。

## §1 单请求性能

### 测试方法

- Adapter:`platform_adapters/bilibili/adapter.py`
- 端点:`https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld?mid=`(uid 路径,5 个测试主播全用此)
- 备选:`https://api.live.bilibili.com/room/v1/Room/room_init?id=`(room_id 路径,含短号)
- 网络:本机(无代理)
- 测试日期:2026-08-02
- 操作人:WorkBuddy 代跑(冒烟 1 轮,5 主播 × 5 轮 = 25 次)

### 单次调用结果(Gate 0B 冒烟阶段,5 主播 × 1 次)

| URL 形式 | room_id | uid | state | live_status | 7 态 | 备注 |
|----------|---------|-----|-------------|-----|------|------|
| live.bilibili.com/1796297556 | 1796297556 | - | ONLINE | 1 | ONLINE | 点唱/轮播厅,24h 在播 |
| live.bilibili.com/31751478 | 31751478 | - | ONLINE | 1 | ONLINE | 点唱/轮播厅,24h 在播 |
| live.bilibili.com/1993299468 | 1993299468 | - | ONLINE | 1 | ONLINE | 点唱/轮播厅,24h 在播 |
| space.bilibili.com/528738158 | 8758725 | 528738158 | OFFLINE | 0 | OFFLINE | 罗翔说刑法,未在播 |
| space.bilibili.com/57863910 | (未拿) | 57863910 | OFFLINE | 0 | OFFLINE | 影视飓风,未在播 |

> **观察**:
> - **ONLINE + OFFLINE 双路径已实测**(11.4h 浸泡,280 样本:ONLINE 139 / OFFLINE 91 / PARSE_ERROR 50)
> - **缺真实状态转换**:3 个 ONLINE 房间是 24h 点唱/轮播厅,2 个 OFFLINE 是视频 UP。样本两极,需补"会开播也会下播"的常规主播

**延迟分布**(11.4h 浸泡):
- 正常时段:115ms ~ 数秒(中位 ~150s 受限流时段拉高)
- **限流时段(21:00-23:17):latency 全部 ~150s(连接超时)**
- **观察到匿名请求约 2.5s 延迟,原因未知**。B 站是否有意限速,Gate 0C 再做因果实验(对比登录态 vs 匿名态、IP 池 vs 单 IP)

**单次调用资源占用**:
- 请求体:约 0.1 KB
- 响应体:约 0.4 KB(JSON)
- 内存峰值:< 1 MB
- CPU:无明显占用

### 7 态映射

| 平台 raw live_status | 7 态 |
|----------------------|------|
| 0 / "false" | OFFLINE |
| 1 / "true" | ONLINE |
| 2(轮播) | ONLINE |
| 异常 errcode | NOT_FOUND / PARSE_ERROR(由 common.classify_error 决定) |

### 解析能力

- [x] `https://space.bilibili.com/{uid}` 解析为 uid
- [x] `https://live.bilibili.com/{room_id}` 解析为 room_id(含短号)
- [x] `https://www.bilibili.com/{uid}` 解析为 uid
- [x] 纯数字默认按 uid 解析
- [x] `PLACEHOLDER_*` 短路返回 NOT_FOUND(state=NOT_FOUND,errcode=-100)
- [ ] 短链 `https://b23.tv/xxx`(需跳转,Gate 0C 再补)
- [ ] 旧 `https://room.bilibili.com/xxx`(Gate 0C 再补)

### 错误码 → 7 态

| 场景 | errcode | 7 态 | 行为 |
|------|---------|------|------|
| 房间不存在 | 1 | NOT_FOUND | ok=False,不抛异常 |
| 网络超时(含限流) | -1 | PARSE_ERROR(暂归,Gate 0C 验证) | ok=False,fallback |
| 返回非 JSON | -2 | PARSE_ERROR | ok=False,fallback |
| URL 无法解析 | -3 | NOT_FOUND | ok=False |
| Placeholder 短路 | -100 | NOT_FOUND | 不调 API |
| 限流(429) | (HTTP 层) | RATE_LIMITED | ok=False,需 backoff |

> **⚠️ 实测发现(2026-08-02 21:00)**:B 站匿名持续轮询 ~8.3h 后(12:44 起 5 房间 × 300s)出现**连接级限流** — 表现为 `HTTPSConnectionPool` 连接超时(非 HTTP 429),持续 ~2h17m 后(23:17)自动恢复。**此现象映射为 -1 → PARSE_ERROR 有语义偏差**:连接超时更接近 `RATE_LIMITED`。**Gate 0C 需决策**:是否把"连接超时且重试仍失败"升级为 `RATE_LIMITED`。

> **⚠️⚠️ 二次限流发现(2026-08-04)**:同 IP 冷却 2 天后重启 soak,**仅 25 分钟就再次限流**(8/2 首犯是 8.3h 后才限流)。**结论:限流阈值与 IP 信誉负相关,累犯加速触发**。对 V1 生产设计的直接含义:
> - 单 IP 匿名轮询不可持续,必须引入登录态 / cookie 池 / UA 池 / 多出口 IP
> - 限流恢复时间可能随累犯次数延长,需自动退避(触发后停 ≥4h 再试,而非 2h)
> - 此结论直接进入 Gate 0C 风控设计输入

## §2 批量 QPS / 容量(待 Gate 0C 填)

> **✅ C3 批量调研结论(2026-08-12):B站无有效批量端点**
> - `getList`(推荐页):单请求 115 房间(5 推荐 + 110 分区),但**漏检率极高** — 3 个测试在播房间 0 命中(推荐位只覆盖极少数)
> - `getRoomPlayInfo` / `getRoomInfoOld`:逗号分隔多 room_id/uid 返回 **-400,不支持批量**
> - `getWebAreaList`:返回 -400(需 wbi 签名或参数修正)
> - **结论:B站只能单房间探测**,容量模型 = sustained_qps × 轮询间隔,无 batch 增益
>
> **前置数据(2026-08-02 实测)**:单 IP 匿名,5 房间 × 300s 间隔(即持续 ~0.017 req/s/房间,总 ~0.02 req/s)连续 ~8.3h 后被连接级限流。Gate 0C 需测更高频率的阈值。
> **前置数据(2026-08-04 实测)**:累犯 IP 冷却 2 天后,~0.02 req/s 下 25 分钟即触发限流。

## §3 反爬 / 风控(待 Gate 0C 填)

> **前置数据(2026-08-02 实测)**:B 站限流是连接超时而非 429/403,且 ~2h 后自动恢复。
> **前置数据(2026-08-04 实测)**:累犯 IP 25 分钟即限流,**恢复时间待测**(可能 > 2h)。Gate 0C 需确认:恢复时间是否随累犯延长、是否 IP 级、UA 池能否规避。

## §4 容量推算(待 Gate 0C 填)

> 占位。结合 §2 的 QPS 阈值 + §1 的延迟 + PRD V1 主播上限,推算 B 站单一 worker 池能承载多少主播。
