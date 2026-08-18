# Douyin Adapter Capacity — Gate 0B / 0C 阶段

> **状态总览**(Gate 0B 阶段):
> - Transport: ✅ ttwid 拿到,web/enter API 调通,errcode 处理正常
> - Correctness: ⚠️ **NOT TESTED** — 5 个 placeholder 全部 NOT_FOUND,无 ONLINE / OFFLINE ground truth
> - 必须补 5 个真实公开主播后重新开始 correctness soak
>
> **⚠️ web_rid 自主获取不可行(2026-08-06 调研确认)**:live.douyin.com SSR 的 19 位数字是加密/无关 ID(17 个候选全 NOT_FOUND);搜索页 19 位为加密格式;专题 web_rid 是 12 位短 ID。**必须用户提供**(抖音 App 分享短链 `v.douyin.com/xxx` 或浏览器地址栏 19 位 web_rid)。详见 reports/douyin.md §1.1。
>
> ⚠️ StageLetter 不拉流、不录制、不播放,**没有 stream URL 任务**(原 §3 误列,已删)。

## §1 单请求性能

### 测试方法

- Adapter:`platform_adapters/douyin/adapter.py`
- 端点:`https://live.douyin.com/webcast/room/web/enter/?web_rid=`
- 网络:本机(无代理)
- 测试日期:2026-08-02
- 操作人:WorkBuddy 代跑(transport 冒烟)

### 单次调用结果(transport 冒烟阶段,5 placeholder × 3 轮 = 15 次)

| URL 形式 | room_id | state | 7 态 | 备注 |
|----------|---------|-------|------|------|
| 7234567890123456789 | (未拿) | errcode=4001038 | NOT_FOUND | 抖音返回"该内容暂时无法无法查看" |
| 7234567890123456790 | (未拿) | errcode=4001038 | NOT_FOUND | 同上 |
| 7234567890123456791 | (未拿) | errcode=4001038 | NOT_FOUND | 同上 |
| 7234567890123456792 | (未拿) | errcode=4001038 | NOT_FOUND | 同上 |
| 7234567890123456793 | (未拿) | errcode=4001038 | NOT_FOUND | 同上 |

> **观察**:5 个 placeholder 全部 4001038 → 7 态 `NOT_FOUND`,验证错误路径正确。
> **缺**:未做 ONLINE / OFFLINE 真实 ground truth 对照(无真实主播数据)

**延迟分布**(15 次,跨 3 轮):
- 中位数:5003 ms
- p95:5075 ms
- 最小 / 最大:105 / 5075 ms
- 节流 3s 是主要耗时

**ttwid 初始化延迟**(首次访问 live.douyin.com):
- ~100ms(cookie 写入)

**单次调用资源占用**:
- 请求体:约 0.2 KB
- 响应体:约 2-5 KB
- 内存峰值:< 2 MB

### 7 态映射

| 平台 raw status | 含义 | 7 态 |
|-----------------|------|------|
| 0 | 未开播 | OFFLINE |
| 2 | 直播中 | ONLINE |
| 4 | 已结束 | OFFLINE |
| 异常 status_code | 平台异常 | NOT_FOUND / PARSE_ERROR |

> ⚠️ **新版响应结构(2026-08-06 实测)**:房间详情在 `data.data[0]`(旧版 `data.room` 已移除),字段 `status`(2=直播中)/`status_str`/`title`/`owner.nickname`。`data.room_status`(0=可进入)与 `data.enter_room_id`(19 位内部 ID)是新增字段,非权威直播状态。

### 解析能力

- [x] `https://v.douyin.com/{short}` 触发 302 跳转,提取 room_id
- [x] `https://www.douyin.com/live/{room_id}` 提取 room_id
- [x] `https://live.douyin.com/{room_id}` 提取 room_id
- [x] **纯 10-25 位数字按 web_rid 解析**(8/6 修正:web_rid 是 10-13 位,原只接受 15-25 位)
- [x] `PLACEHOLDER_*` 短路返回 NOT_FOUND
- [ ] 旧格式 `https://douyin.com/xxx`(Gate 0C 再补)
- [ ] `https://www.iesdouyin.com/`(国际版,Gate 0C 再补)

### ⚠️ web_rid vs room_id 澄清(2026-08-06 重大发现)

- **web_rid**:直播间 URL 的短数字(10-13 位,如 `496999661018`),`enter API` 的 `web_rid` 参数用它
- **room_id / id_str**:19 位内部 ID(如 `7670915678941285156`),`data.enter_room_id` 返回它
- **两者不同**!之前 19 位数字全部 NOT_FOUND 是因为拿的是 room_id 不是 web_rid
- 获取 web_rid 的可靠途径:`webcast/feed` 推荐流 API 响应的 item **顶层 `web_rid` 字段**(需浏览器自动化捕获网络请求;SSR/DOM 里只有混淆 ID)

### 错误码 → 7 态

| 场景 | errcode | 7 态 | 行为 |
|------|---------|------|------|
| 房间不存在 | 4001038 | NOT_FOUND | "该内容暂时无法无法查看" |
| token 失效 | 40001 / 42001 | BLOCKED | 需 ttwid 续期 |
| 网络超时 | -1 | PARSE_ERROR | ok=False,fallback |
| 返回非 JSON | -2 | PARSE_ERROR | ok=False |
| URL 无法解析 | -4 | NOT_FOUND | ok=False |
| 短链展开失败 | -5 | NOT_FOUND | ok=False |
| 展开后无 room_id | -6 | NOT_FOUND | ok=False |
| HTML 无状态字段 | -7 | PARSE_ERROR | ok=False(本平台不常见) |
| Placeholder 短路 | -100 | NOT_FOUND | 不调 API |

## §2 批量 QPS / 容量(待 Gate 0C 填)

> **✅ C3 批量调研结论(2026-08-12):抖音无有效批量端点**
> - `webcast/feed`:httpx + ttwid 可直接调用,**但单响应固定 6 房间**(count=10/30/50/100 均无效)
> - `offset/cursor/scroll_to` 分页参数无效(每次随机推荐,累计去重仅 8 房间)
> - **结论:feed 是"随机推荐流"而非可翻页列表,不能用于批量状态检测**
> - 抖音容量模型 = sustained_qps × 轮询间隔(单房间探测,无 batch 增益),与 B站同
>
> **注意**:C6 因果实验(douyin)已启动(2026-08-12 23:48),测 ttwid 单 IP 限流阈值,结果会填这里。

## §3 反爬 / 风控(待 Gate 0C 填)

> 占位。Gate 0C 会观察:ttwid 失效频率、IP 频率阈值、UA 检测。

## §4 容量推算(待 Gate 0C 填)

> 占位。结合 §2 + §1 + PRD V1 主播上限,推算抖音 worker 池承载量。
