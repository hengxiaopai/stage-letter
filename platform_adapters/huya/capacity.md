# Huya Adapter Capacity — Gate 0B / 0C 阶段

> **状态总览**(Gate 0B 阶段,2026-08-02 更新):
> - Transport: ✅ HTML 抓取正常,eLiveStatus 解析命中
> - Correctness: ⚠️ **PARTIAL** — 5 个真实房间全部 ONLINE(11.4h 浸泡 116 次 ONLINE),**缺 OFFLINE 真实 ground truth + 真实转换**
> - Placeholder 返回: 全部 NOT_FOUND(已正确短路)
>
> ⚠️ StageLetter 不拉流、不录制、不播放,**没有 stream URL 签名任务**(原 §3 误列,已删)。

## §1 单请求性能

### 测试方法

- Adapter:`platform_adapters/huya/adapter.py`
- 端点:`https://m.huya.com/{room_id}`(移动端 HTML)
- 网络:本机(无代理)
- 测试日期:2026-08-02
- 操作人:WorkBuddy 代跑

### 单次调用结果(Gate 0B 冒烟 + 11.4h 浸泡)

| URL 形式 | room_id | state | 7 态 | parse_method | 备注 |
|----------|---------|-------|------|--------------|------|
| 660000 | 660000 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 虎牙 LOL 赛事,24h 在播 |
| 998 | 998 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 狂鸟丶楚河,11.4h 在播 |
| 1995 | 1995 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 小小小酷哥,11.4h 在播 |
| 441195 | 441195 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 胖炸,11.4h 在播 |
| 825290 | 825290 | eLiveStatus=2 | **ONLINE** | eLiveStatus_grep | 弃徒x,11.4h 在播 |

> **关键发现 1**:虎牙字段名是 **`eLiveStatus`**,值为整数(1/2/3 = 在播,0 = 未播)。HTML 静态注入。
> **关键发现 2**:`cache.php?m=LiveList` API 返回的 `channel` 字段 ≠ mobile URL room_id;**`profileRoom` 才是**。
> **缺**:OFFLINE 真实 ground truth(5 房间全在播,均为头部热门,几乎不停播)

**延迟分布**(11.4h 浸泡,141 样本):
- 正常时段:133ms ~ 数秒(中位 ~300s 受限流时段拉高)
- **限流时段(21:00-23:17):latency 全部 ~300s(连接超时)**

**单次调用资源占用**:
- 请求体:约 0.1 KB
- 响应体:约 50-60 KB(HTML,比 B 站/抖音大很多)
- 内存峰值:< 1 MB

### 7 态映射

| 平台 raw eLiveStatus | 7 态 |
|----------------------|------|
| 0 | OFFLINE |
| 1 / 2 / 3 | ONLINE |
| 其他 / null | UNKNOWN |

### 解析能力

- [x] `https://www.huya.com/{room_id}` 提取 room_id
- [x] `https://m.huya.com/{room_id}` 提取 room_id
- [x] 纯 1-15 位数字按 room_id 解析
- [x] `PLACEHOLDER_*` 短路返回 NOT_FOUND
- [ ] 短链(虎牙似乎没短链)

### 解析策略(优先级)

1. `window.HNF_GLOBAL_INIT / __INIT_STATE__ / __NUXT__` JSON 递归找 `eLiveStatus / liveStatus / isOnLive / isLive`
2. 全文 grep `"eLiveStatus"\s*:\s*(\d+)`(虎牙实际字段名)
3. 全文 grep `"liveStatus"\s*:\s*(true|false|1|0|"true"|"false")`
4. 全文 grep `"isOnLive"|"isLive"|"live_state"|"isOn"\s*:\s*(true|false|1|0)`
5. 全失败 → state=PARSE_ERROR(原返回 errcode=-7)

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

> **⚠️ 实测发现(2026-08-02 21:00)**:虎牙匿名持续轮询 ~8.3h 后出现**连接级限流**(`HTTPSConnectionPool` 超时,非 429),持续 ~2h17m 后恢复。**与 B 站模式一致**。Gate 0C 需决策是否将连接超时升级为 RATE_LIMITED。

## §2 批量 QPS / 容量(待 Gate 0C 填)

> **✅ C3 批量端点验证(2026-08-12):虎牙有"在播列表"批量 API!**
> - 端点:`https://www.huya.com/cache.php?m=LiveList&do=getLiveListByPage&gameId=0&tagAll=0&page=1&pageSize=120`
> - **单请求返回 120 个在播房间**(pageSize 上限 120,请求 1000 也截断为 120)
> - 关键字段:`profileRoom`(= room_id,如 998 / 60066 / 10188)、`nick`(昵称)、`roomName`、`introduction`
> - 语义:**出现在该列表 = 正在直播**(这是"在播推荐列表",无显式 live 状态字段)
> - 列表有 82 页 × 120 = ~9840 个在播房间(覆盖整个虎牙在播集)
>
> **容量模型影响(巨大)**:
> - 方案 A(单房间探测):1 请求/房间 → 1000 房间需要 1000 请求
> - **方案 B(列表探测)**:1 请求/120 房间 → 1000 房间只需 ~9 请求;若一次性拉全部页,9840 房间仅 82 请求
> - **但注意**:列表只含"在播"房间。某订阅主播若不在列表 = 大概率 OFFLINE(但需确认:是否所有在播房间都会出现在列表,还是仅推荐位)
> - **结论方向**:虎牙建议"列表快照 + 订阅房间差异检测"混合策略,V1 容量模型完全重写
>
> **待 Gate 0C 确认**:
> 1. ~~列表是否包含**全部**在播房间~~ — **❌ 实测否定(2026-08-12):列表有漏检!**
>    - 全扫 82 页 × 120 房间(≈9840 房间),3 个已知在播房间只命中 2 个
>    - JackeyLove(30764310)@page2、狼人杀轮播(14342778)@page19、**杰瑞CF(20814787)❌ 未出现(但单独探测 ONLINE)**
>    - **结论:列表 = "推荐/热门"排序,不覆盖全部在播**(活动/赛事房间可能不在通用列表)
>    - **风险:列表快照会把漏检房间误判为 OFFLINE** → 列表策略**不能单独使用**
> 2. 混合策略修正:列表快照(覆盖热门)+ **单房间探测补漏**(只查订阅列表里没在快照中出现的房间)
>    - 对单个用户而言,订阅的多是热门主播 → 列表命中率高;冷门主播需单查
>    - 具体漏检率需更大样本(比如 50 个在播房间)统计
> 3. 列表 82 页全拉是否触发风控(82 请求连发,本次实测无异常)

## §3 反爬 / 风控(待 Gate 0C 填)

> **前置数据(2026-08-02)**:虎牙限流是连接超时而非 429/403,~2h 后自动恢复。HTML 抓取体量大(50-60KB),风控可能盯请求频率而非内容。

## §4 容量推算(待 Gate 0C 填)

> 占位。虎牙 HTML 抓取资源占用大,容量可能受限于 HTML 解析 CPU。
