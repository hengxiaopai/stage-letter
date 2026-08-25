# reports/douyu.md — Gate 0B 斗鱼实测报告

> **Gate 0B 状态:IN PROGRESS**
> - Transport: ✅ PASS(HTML 抓取 + show_status 解析)
> - Correctness: ⚠️ **PARTIAL** — ONLINE + OFFLINE 双 ground truth 已获,但 **0 次真实状态转换**(11.4h + 8/6 快照)
> - Placeholder: 0/5(全部已替换为真实房间)
> - 真实状态 transition: 0 次(所有转换均为限流引发的 PARSE_ERROR 抖动)

---

## 0. 元数据

| 字段 | 值 |
|------|----|
| 跑实验日期 | 2026-08-02 ~ 2026-08-06(11.4h 浸泡 + 8/6 快照 + 6h soak 进行中) |
| 测试主播数 | 5(9999 + 171717 + 605964 + 1165924 + 1000) |
| 轮询间隔 | 600s(10min) |
| Adapter | `platform_adapters/douyu/adapter.py` |
| 端点 | `https://www.douyu.com/{room_id}`(桌面端 HTML) |
| Correctness task | `ZhwM37`(8/2 24h 启,中断)+ `kdgzBq`(8/6 6h 进行中) |
| 样本文件 | experiments/data/douyu_24h-20260802-1244.jsonl(141 行)+ douyu_24h-20260806-0835.jsonl(进行中) |
| Summary 文件 | ⚠️ 进程被杀未写出;数据在 jsonl 里 |

## 1. Transport + ONLINE/OFFLINE 冒烟(已通过)

| URL 形式 | room_id | state | 7 态 | parse_method | 延迟 (ms) |
|----------|---------|-------|------|--------------|-----------|
| 9999 | 9999 | show_status=1 | **ONLINE** | show_status_grep | 34-5092 |
| 171717 | 171717 | show_status=1 | **ONLINE** | show_status_grep | - |
| 605964 | 605964 | show_status=1 | **ONLINE** | show_status_grep | - |
| 1165924 | 1165924 | show_status=1 | **ONLINE** | show_status_grep | - |
| 1000 | 1000 | show_status=2 | **OFFLINE** | show_status_grep | - |

> 关键:斗鱼 HTML 字段是 `\"show_status\":1`(**JSON 内嵌,转义引号**)
> 1000 是人工探测的小房间号,当前未播,作 OFFLINE ground truth 候选(非权威长期不播,见 §6)

## 2. 7 态分布(11.4h 实测)

| 状态 | 次数 | 说明 |
|------|------|------|
| ONLINE | 93 | 9999/171717/605964/1165924 连续 11.4h 在播 |
| OFFLINE | 23 | 1000 连续 11.4h 未播 ✅ |
| NOT_FOUND | 0 | - |
| RATE_LIMITED | 0 | 注意:限流表现为连接超时(-1),不是 HTTP 429 |
| BLOCKED | 0 | - |
| PARSE_ERROR | 25 | 21:00-23:17 限流窗口内 5 房间 × 5 次连接失败 |
| UNKNOWN | 0 | - |

## 3. Ground Truth 对照表

| 时间 | 抽样房间 | 平台侧 state | 人工/客户端真实 | 一致? |
|------|----------|-------------|----------------|-------|
| 12:44 | 9999 | ONLINE | 斗鱼 yyfyyf 直播中 | ✅ |
| 12:44 | 171717 | ONLINE | 若若跑的贼快 直播中 | ✅ |
| 12:44 | 605964 | ONLINE | CFPL 夏季赛总决赛 直播中 | ✅ |
| 12:44 | 1165924 | ONLINE | 靓旭 直播中 | ✅ |
| 12:44 | 1000 | OFFLINE | 房间未播 | ✅ |
| 21:00-23:17 | 全部 | PARSE_ERROR | 客户端仍正常(平台限流) | ✅(平台侧) |
| 8/6 08:35 | 9999/171717/605964/1165924 | ONLINE | 客户端确认全部仍在播 | ✅ |
| 8/6 08:35 | 1000 | OFFLINE | 客户端确认仍未播 | ✅ |

> **无 silent parse failure**:25 次限流失败全部正确标记为 `PARSE_ERROR` ✅

## 4. 真实状态 transition

| 时间 | 房间 | from_state | to_state | 平台侧真实 | 一致? |
|------|------|------------|----------|-----------|-------|
| (无) | - | - | - | - | - |

> ⚠️ **0 次真实 ONLINE↔OFFLINE 转换**(10 次变化均为限流抖动)。
> **样本选择偏差**:4 个 ONLINE 房间全是热门/赛事(几乎不停播),1 个 OFFLINE 房间 1000 一直不播。8/6 快照确认状态未变。**两极样本,缺少"会开播也会下播"的常规主播**。

## 5. PASS 新标准检查

- [x] 5 个真实主播 ✅
- [x] ONLINE 真实 ground truth ≥ 1 次 ✅(4 房间连续 11.4h + 8/6 快照 ONLINE)
- [x] OFFLINE 真实 ground truth ≥ 1 次 ✅(1000 连续 OFFLINE,但需用户确认为权威基线)
- [ ] 真实状态 transition ≥ 1 次 ❌(**缺,样本两极**)
- [x] 无 silent parse failure ✅(25 次限流正确标记 PARSE_ERROR)
- [ ] 每次抽样与 Ground Truth 对照 ⚠️(已对照 8 时间点)

## 6. 待补行动

1. **补 1-2 个"会开播也会下播"的常规主播**(非赛事厅/非 24h 点唱厅,如晚间固定开播的游戏主播),以获得真实转换
2. 1000 房间:请用户确认是否是"长期不播"的权威 OFFLINE 基线(否则替换为已知不播的主播)
3. 替换 `experiments/test_anchors/douyu.txt` 中 1-2 个热门厅
4. **72h 连续浸泡不可行**(进程 ~3-12h 即被杀):改为多轮 6h 短浸泡 + 快照抽查;8/6 soak 进行中
5. 每 1-2h 抽样一次,人工对比斗鱼客户端,填 §3 表

## 7. 结论

- [ ] Gate 0B 斗鱼:Transport PASS / Correctness NOT PASS(缺真实转换)
- [ ] 关键阻塞:样本两极(4 热门 + 1 固定不播),需常规主播 + 观察
