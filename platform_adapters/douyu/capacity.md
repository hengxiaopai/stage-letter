# Douyu Adapter Capacity — Gate 0B / 0C 阶段

> **状态总览**(Gate 0B 阶段,2026-08-02 更新):
> - Transport: ✅ HTML 抓取正常,show_status 解析命中
> - Correctness: ⚠️ **PARTIAL** — ONLINE + OFFLINE 双 ground truth 已获(11.4h 浸泡 93 ONLINE + 23 OFFLINE),**缺 ≥1 真实状态转换**
> - Placeholder 返回: 全部 NOT_FOUND(已正确短路)
>
> ⚠️ StageLetter 不拉流、不录制、不播放,**没有 stream URL 签名任务**(原 §3 误列,已删)。

## §1 单请求性能

### 测试方法

- Adapter:`platform_adapters/douyu/adapter.py`
- 端点:`https://www.douyu.com/{room_id}`(桌面端 HTML)
- 网络:本机(无代理)
- 测试日期:2026-08-02
- 操作人:WorkBuddy 代跑

### 单次调用结果(Gate 0B 冒烟 + 11.4h 浸泡)

| URL 形式 | room_id | state | 7 态 | parse_method | 备注 |
|----------|---------|-------|------|--------------|------|
| 9999 | 9999 | show_status=1 | **ONLINE** | show_status_grep | 斗鱼 yyfyyf,24h 在播 |
| 171717 | 171717 | show_status=1 | **ONLINE** | show_status_grep | 若若跑的贼快,11.4h 在播 |
| 605964 | 605964 | show_status=1 | **ONLINE** | show_status_grep | CFPL 夏季赛,11.4h 在播 |
| 1165924 | 1165924 | show_status=1 | **ONLINE** | show_status_grep | 靓旭,11.4h 在播 |
| 1000 | 1000 | show_status=2 | **OFFLINE** | show_status_grep | 小房间号,11.4h 未播(候选基线) |

> **关键发现**:斗鱼 HTML 字段是 `\"show_status\":1`(**JSON 内嵌,转义引号**)
> 正则必须接受 `\\?"..."\\?`,否则匹配失败。
> **缺**:真实状态转换(4 ONLINE 全热门/赛事,1 OFFLINE 固定不播,两极样本)

**延迟分布**(11.4h 浸泡,141 样本):
- 正常时段:118ms ~ 数秒(中位 ~300s 受限流时段拉高)
- **限流时段(21:00-23:17):latency 全部 ~300s(连接超时)**

**单次调用资源占用**:
- 请求体:约 0.1 KB
- 响应体:约 130-150 KB(HTML,斗鱼页面较大)
- 内存峰值:< 2 MB

### 7 态映射

| 平台 raw show_status | 7 态 |
|----------------------|------|
| 1 | ONLINE |
| 2 | OFFLINE |
| 0 / 3 / 4 | UNKNOWN(配合 videoLoop 二次判断) |
| videoLoop=1 | ONLINE(轮播) |
| isLiveBroadcast=true | ONLINE |

### 解析能力

- [x] `https://www.douyu.com/{room_id}` 提取 room_id
- [x] 1-12 位纯数字按 room_id 解析
- [x] `PLACEHOLDER_*` 短路返回 NOT_FOUND
- [ ] 短链(斗鱼似乎没短链)

### 解析策略(优先级)

1. `window.__INIT_STATE__ / $ROOM / DouyuData / HNF_GLOBAL_INIT / __NUXT__` JSON 递归找 `show_status / liveStatus / isOnLive / isLive`
2. 全文 grep 转义引号 `\\?"show_status\\?"\s*:\s*(\d+)`(斗鱼实际字段)
3. 全文 grep `\\?"showStatus\\?"\s*:\s*("?)([12])\1`
4. 全文 grep `\\?"isLiveBroadcast\\?"\s*:\s*(true|false|"true"|"false")`
5. 全文 grep `\\?"videoLoop\\?"\s*:\s*1`(轮播视为在播)
6. 全失败 → state=PARSE_ERROR(原返回 errcode=-7)

### 错误码 → 7 态

| 场景 | errcode | 7 态 |
|------|---------|------|
| 网络超时(含限流) | -1 | PARSE_ERROR |
| 返回非 text | -2 | PARSE_ERROR |
| URL 无法解析 | -4 | NOT_FOUND |
| 短链展开失败 | -5 | NOT_FOUND |
| 展开后无 room_id | -6 | NOT_FOUND |
| HTML 无状态字段 | -7 | PARSE_ERROR |
| Placeholder 短路 | -100 | NOT_FOUND |

> **⚠️ 实测发现(2026-08-02 21:00)**:斗鱼匿名持续轮询 ~8.3h 后出现**连接级限流**(`HTTPSConnectionPool` 超时,非 429),持续 ~2h17m 后恢复。**与 B 站/虎牙模式一致**(三大平台同晚同时段限流,可能是通用反爬策略或网络层)。Gate 0C 需确认。

## §2 批量 QPS / 容量(待 Gate 0C 填)

> **✅ C3 批量端点验证(2026-08-12):斗鱼有"在播列表"批量数据!**
> - 端点:`https://www.douyu.com/directory/all`(HTML 页面,~267KB)
> - **单页面内嵌 40 个在播房间**(含 `rid` 房间号、`nn` 昵称、`rn` 房间名、`ol` 在线人数)
> - 旧 gapi(`/gapi/rkc/directory/0/1.json`)已失效(404),新版需从页面内嵌 JSON 解析
> - 语义:**出现在列表 = 正在直播**(ol > 0),`ol=0` 可能是已下播残留
>
> **容量模型影响**:
> - 方案 B(列表探测):1 请求/40 房间 → 1000 房间需 ~25 请求(若支持翻页则更少)
> - 需确认:directory/all 是否支持翻页参数(page=2,3...)、每页固定 40?
> - 斗鱼 HTML 体量大(130-150KB/页),列表抓取带宽成本高(40 房间/267KB ≈ 6.7KB/房间,仍优于单房间 130KB)
>
> **待 Gate 0C 确认**:
> 1. ~~directory/all 翻页参数与每页房间数上限~~ — **❌ 实测否定(2026-08-12):列表有漏检!**
>    - 首页 40 个在播房间,4 个测试在播房间只命中 1 个(9999)
>    - 171717 / 605964 / 1165924 均 ONLINE 但不在列表(可能因列表是"推荐位"而非全量)
>    - **结论:斗鱼列表 = 推荐位,不覆盖全部在播** → 列表策略**不能单独使用**
> 2. 混合策略修正:列表快照(覆盖热门)+ 单房间探测补漏(只查订阅列表里没出现的房间)
> 3. directory/all 是否支持翻页(page 参数)仍需确认 — 首页仅 40 个,全量在播远多于 40

## §3 反爬 / 风控(待 Gate 0C 填)

> **前置数据(2026-08-02)**:斗鱼限流是连接超时而非 429/403,~2h 后自动恢复。HTML 体量最大(130-150KB),需关注解析 CPU。

## §4 容量推算(待 Gate 0C 填)

> 占位。斗鱼 HTML 较大(130-150KB),容量可能受限于带宽 + 解析 CPU。
