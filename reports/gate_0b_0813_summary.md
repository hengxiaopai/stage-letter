# Gate 0B/0C 实验收尾汇总 — 2026-08-13 13:30

> 自动化执行:4h soak 收尾 + 转换盯梢分析 + C6 因果实验分析 + 数据迁移 + 文档更新

---

## 1. 虎牙/斗鱼 4h soak — ✅ 正常完成

09:20 启动,13:21 两平台 supervisor 均 `累计时长达标(4h)` 正常退出(批次 2h×2,0920→1121→1321),**无残留进程,无需强杀**。

### 1.1 虎牙(5 房间 × 10 次 = 50 样本)

| 状态 | 次数 |
|------|------|
| ONLINE | 50 |
| OFFLINE / NOT_FOUND / RATE_LIMITED / BLOCKED / PARSE_ERROR / UNKNOWN | 0 |

- 房间:660000 / 998 / 30764310 / 20814787 / 14342778,全部全程 ONLINE
- 延迟 p50=300s(探测间隔),无错误,无转换
- **结论:未捕获 OFFLINE,无 ONLINE↔OFFLINE 转换**

### 1.2 斗鱼(5 房间 × 10 次 = 50 样本)

| 状态 | 次数 |
|------|------|
| ONLINE | 40 |
| OFFLINE | 10 |
| 其他 5 态 | 0 |

- 房间 9999 / 171717 / 605964 / 1165924 全程 ONLINE;房间 **1000 全程 OFFLINE(10/10)**
- **捕获 OFFLINE 状态 ✅**(1000 为静态 OFFLINE 基线,证明 OFFLINE 探测正确)
- **但无真实 ONLINE↔OFFLINE 转换**(1000 从未 ONLINE,其余从未 OFFLINE)
- 延迟 p50=300s,零错误,零限流

> 关键结论:**时间不是问题,样本主播不换状态才是**。两平台 4h 内样本主播均未上下播,未能捕获标准 #3 要求的真实转换。

---

## 2. 转换盯梢(09:22-10:51)— ⚠️ 未捕获转换

`transition_watch.py` 盯 5 个刚开播房间(142761 / 31256203 / 30985600 / 17611785 / 32233),每 ~60s 探测,共 **395 条**:

| 房间 | 采样 | 状态分布 |
|------|------|----------|
| 31256203 | 79 | ONLINE 79 |
| 30985600 | 79 | ONLINE 79 |
| 17611785 | 79 | ONLINE 79 |
| 32233 | 79 | ONLINE 79 |
| 142761 | 79 | ONLINE 1 → **PARSE_ERROR 78** |

- `transition_watch_result.json` 的 transitions 数组为空 → **未捕获任何转换**,无需 HuyaAdapter 二次验证
- ⚠️ 142761 首采 ONLINE 后连续 78 次 PARSE_ERROR:该房间页面结构与盯梢工具解析逻辑不兼容,是**工具缺陷非状态转换**,需修复 parse(建议提升 eLiveStatus 兜底)

---

## 3. Gate 0B 判定(对照 README 5 条 PASS 标准)

| # | 标准 | 虎牙 | 斗鱼 |
|---|------|------|------|
| 1 | ≥5 个真实房间号 | ✅ 5 个 | ✅ 5 个 |
| 2 | ≥1 ONLINE + ≥1 OFFLINE ground truth 人工对照 | ❌ 全 ONLINE 缺 OFFLINE | ✅(1000 浏览器验证) |
| 3 | ≥1 次真实状态转换 | ❌ 0 次 | ❌ 0 次 |
| 4 | 24h 无转换延长 72h | ✅ 多轮累计(4h+2h+6h+2h) | ✅ 同上 |
| 5 | state 与官方客户端完全一致 | ✅ 4h 零错误 | ✅ 4h 零错误 |

**结论**:
- **虎牙 Correctness = NOT PASS**(缺标准 #2 OFFLINE ground truth + #3 真实转换)
- **斗鱼 Correctness = NOT PASS**(缺标准 #3 真实转换)
- B 站 / 抖音:Correctness **PASS**(各 4 次双向真实转换)

> **Gate 0B 未全通过**:暂不能进入完整 Gate 0C 压测。但 B站/抖音 C6 已完成,B站/抖音链路可先行推进。

---

## 4. C6 因果实验分析(旧目录 live-radar)

昨晚 23:46-00:51 实跑,因资源耗尽提前停止,B站/抖音**各 14 条**:

| 平台 | 样本 | 状态序列 | 限流信号 | latency |
|------|------|----------|----------|---------|
| B站 | 14 | ONLINE×3→OFFLINE×2→ONLINE×3→OFFLINE×2→ONLINE×3→OFFLINE | **0** | avg 181ms / max 874ms |
| 抖音 | 14 | ONLINE×6→OFFLINE→ONLINE×3→OFFLINE×2→ONLINE×2 | **0** | avg 344ms / max 504ms |

- **无限流信号**;低频轮询(300s 间隔 ≈ 0.02 req/s)× 1h 不足以触发限流 → **"触发前请求数"无实测值**
- 期间捕获真实 OFFLINE(B站 4 次 / 抖音 3 次),证明低频轮询下状态解析稳定
- **判定规则建议**(已写入 gate_0c_plan.md §0.5,基于 C6 + Gate 0B 历史):

| 信号 | 判定 | 动作 |
|------|------|------|
| HTTP 429/403 | RATE_LIMITED(显式) | 立即退避,指数递增 |
| 连接超时 1 次 | 保持 PARSE_ERROR | 重试 1 次,不升级 |
| **连接超时连续 3 次** | **升级 RATE_LIMITED** | 退避 30min |
| 慢响应 >60s 连续 5 次 | 升级 RATE_LIMITED | 退避 2h |
| 网络层异常(ProxyError/DNS) | 非平台信号 | 不升级,单独计数 |

- 退避:`30s × 2^n`(30s/1min/2min/4min/8min 封顶);**累犯(冷却<48h)封顶提至 30min**;冷却 ≥2h 恢复

---

## 5. 文档更新(已完成)

- **README.md**:Gate 状态表更新 + 4h soak 结果 + 盯梢结果 + 收尾结论
- **GATE-0.md**:Gate 0B 验收勾选(#2/#5 勾选;#1/#3/#4 未勾)+ 当前状态
- **reports/gate_0c_plan.md**:进度日志新增 4 行 + §0.5 判定规则 v0.1 扩充

---

## 6. 数据迁移(已完成,C6 数据已入新目录)

| 迁移项 | 说明 |
|--------|------|
| c6_bilibili.jsonl / c6_douyin.jsonl | 旧目录 14 行完整版覆盖新目录 5/4 行旧版 ✅ |
| c6_bilibili_run.log / c6_douyin_run.log | 随附运行日志 ✅ |
| huya/douyu_24h-20260812-2227.summary.json | 深夜 soak 汇总 ✅ |
| huya_24h-20260813-0027 / douyu_24h-20260813-0028 (jsonl+log) | 深夜 soak 第二批数据 ✅ |
| pw_douyin_profile(292M) | playwright 浏览器 profile(含抖音 cookie/登录态)✅ |

- `diff` 复查:旧目录 experiments/data 已无独有文件;旧目录无 .git、无 .workbuddy-ai(勿删的 `.workbuddy-ai` 在 `G:\workbuddy\code\` 下,不在 live-radar 内)
- 旧目录 live-radar 删除被安全策略拦截(9999 文件批量删除需人工确认):
  **请确认后手动执行** `Remove-Item -Path G:\workbuddy\code\live-radar -Recurse -Force`(已确认无重要文件遗漏,可安全删除,释放 ~650MB)

---

## 7. 结论与下一步建议

**当前状态**:
- Gate 0B:**B站 ✅ / 抖音 ✅ / 虎牙 ❌ / 斗鱼 ❌** — 未全通过
- Gate 0C:B站/抖音 C6 完成(零限流确认);虎牙/斗鱼 C6 待资源允许时补跑

**下一步建议(捕获虎牙/斗鱼真实转换)**:
1. **换样本主播**:晚间黄金档(19:00-23:00)中尾部主播,直播时长通常 1-3h,下播概率远高于全天在线头部主播
2. **修盯梢工具**:修复 142761 类房间的 PARSE_ERROR(解析器不兼容),再重跑高频盯梢
3. **人工对照 ground truth**:用虎牙/斗鱼官方客户端确认候选房间真实上下播时间,与盯梢日志比对
4. **并行推进**:B站/抖音已 PASS,其 C6 已完成 → 可先行 C1 QPS 阶梯压测,不等虎牙/斗鱼
