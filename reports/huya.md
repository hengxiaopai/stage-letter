# reports/huya.md — Gate 0B 虎牙实测报告

> **Gate 0B 状态:IN PROGRESS**
> - Transport: ✅ PASS(HTML 抓取 + eLiveStatus 解析)
> - Correctness: ⚠️ **PARTIAL** — 5 个真实房间(1 基线 + 4 新)ONLINE 已验证,但 **0 次真实转换 + 缺 OFFLINE ground truth**
> - Placeholder: 0/5(全部已替换为真实房间)
> - 真实状态 transition: 0 次(11.4h 浸泡 + 8/6 快照,5 房间持续 ONLINE)

---

## 0. 元数据

| 字段 | 值 |
|------|----|
| 跑实验日期 | 2026-08-02 ~ 2026-08-06(11.4h 浸泡 + 8/6 快照抽查 + 6h soak 进行中) |
| 测试主播数 | 5(660000 + 998 + 1995 + 441195 + 825290) |
| 轮询间隔 | 600s(10min) |
| Adapter | `platform_adapters/huya/adapter.py` |
| 端点 | `https://m.huya.com/{room_id}`(移动端 HTML) |
| Correctness task | `LTcpGb`(8/2 24h 启,中断)+ `OhCAhz`(8/6 6h 进行中) |
| 样本文件 | experiments/data/huya_24h-20260802-1244.jsonl(141 行)+ huya_24h-20260806-0835.jsonl(进行中) |
| Summary 文件 | ⚠️ 进程被杀未写出;数据在 jsonl 里 |

## 1. Transport + ONLINE 冒烟(已通过)

| URL 形式 | room_id | state | 7 态 | parse_method | 延迟 (ms) |
|----------|---------|-------|------|--------------|-----------|
| 660000 | 660000 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 10-5001 |
| 998 | 998 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | - |
| 1995 | 1995 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | - |
| 441195 | 441195 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | - |
| 825290 | 825290 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | - |

> **room_id 关键发现**:虎牙 `cache.php?m=LiveList` API 返回的 `channel` 字段 ≠ mobile room ID。`profileRoom` 才是 URL 用的真实 ID(如 虎牙英雄联盟赛事 channel=1346609715 但 URL 用 660000)。已在 test_anchors/huya.txt 注释。

## 2. 7 态分布(11.4h 实测)

| 状态 | 次数 | 说明 |
|------|------|------|
| ONLINE | 116 | 5 房间连续 11.4h 在播(全部头部/热门,几乎不停播) |
| OFFLINE | 0 | **缺 OFFLINE 真实样本** ❌ |
| NOT_FOUND | 0 | - |
| RATE_LIMITED | 0 | 注意:限流表现为连接超时(-1),不是 HTTP 429 |
| BLOCKED | 0 | - |
| PARSE_ERROR | 25 | 21:00-23:17 限流窗口内 5 房间 × 5 次连接失败 |
| UNKNOWN | 0 | - |

> **限流分类问题**:与 B 站相同,虎牙限流是 TCP 连接超时,非 429。已列入 ADR 候选(见 capacity.md §7)。

## 3. Ground Truth 对照表

| 时间 | 抽样房间 | 平台侧 state | 人工/客户端真实 | 一致? |
|------|----------|-------------|----------------|-------|
| 12:44 | 660000 | ONLINE | 虎牙 LOL 赛事直播中 | ✅ |
| 12:44 | 998 | ONLINE | 狂鸟丶楚河 直播中 | ✅ |
| 12:44 | 1995 | ONLINE | 小小小酷哥 直播中 | ✅ |
| 12:44 | 441195 | ONLINE | 胖炸 直播中 | ✅ |
| 12:44 | 825290 | ONLINE | 弃徒x 直播中 | ✅ |
| 21:00-23:17 | 全部 | PARSE_ERROR | 客户端仍正常(平台限流) | ✅(平台侧) |
| 8/6 08:35 | 全部 | ONLINE | 客户端确认全部仍在播 | ✅ |

> **无 silent parse failure**:25 次限流失败全部正确标记为 `PARSE_ERROR` ✅

## 4. 真实状态 transition

| 时间 | 房间 | from_state | to_state | 平台侧真实 | 一致? |
|------|------|------------|----------|-----------|-------|
| (无) | - | - | - | - | - |

> ⚠️ **0 次真实 ONLINE↔OFFLINE 转换**(10 次变化均为限流抖动)。
> **样本选择偏差**:5 个房间全是头部热门(热度前 10),几乎 24h 在播。8/6 快照确认仍全 ONLINE。**缺一个"会下播"的常规主播**。

## 5. PASS 新标准检查

- [x] 5 个真实主播 ✅
- [x] ONLINE 真实 ground truth ≥ 1 次 ✅(5 房间连续 11.4h + 8/6 快照 ONLINE)
- [ ] OFFLINE 真实 ground truth ≥ 1 次 ❌(**缺 — 5 房间全在播**)
- [ ] 真实状态 transition ≥ 1 次 ❌(**缺,样本全热门**)
- [x] 无 silent parse failure ✅(25 次限流正确标记 PARSE_ERROR)
- [ ] 每次抽样与 Ground Truth 对照 ⚠️(已对照 7 时间点)

## 6. 待补行动

1. **补 1-2 个非热门房间**(中尾部主播,会开播也会下播)以获得 OFFLINE ground truth + 真实转换
2. 可参考:虎牙分区页找热度 1-10 万的中部主播(非超级明星),或用户自己关注的
3. 替换 `experiments/test_anchors/huya.txt` 中 1-2 个头部
4. **72h 连续浸泡不可行**(进程 ~3-12h 即被杀):改为多轮 6h 短浸泡 + 快照抽查;8/6 soak 进行中,若 6h 仍 0 转换则必须换样本
5. 每 1-2h 抽样一次,人工对比虎牙客户端,填 §3 表

## 7. 结论

- [ ] Gate 0B 虎牙:Transport PASS / Correctness NOT PASS(缺 OFFLINE + 真实转换)
- [ ] 关键阻塞:样本全头部热门,需补中部主播(会下播的)
