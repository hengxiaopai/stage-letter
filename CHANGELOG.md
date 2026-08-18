# CHANGELOG

## v0.4.0 (2026-08-14 09:00, P0-S1 抖音登录态搜索 — P0 Correctness Gate 收尾)

### 扫码登录 CLI(tools/douyin_login_cli.py + api/services/douyin_session.py)
- 专用持久化 profile(.workbuddy/douyin_profile, 独立于主账号), 管理员扫码一次登录复用
- 命令: login / status / probe / logout / clean
- 登录检测: 持久化 cookie 请求 search API → status_code==0 有效 / 2483 失效
- 失效标记: mark_invalid → 搜索返回 AUTH_REQUIRED → 引导重新扫码

### 登录态搜索(search_douyin_logged_in)
- **关键突破**: 抖音 PC 搜索 DOM 不渲染(自动化检测) + search API 需 X-Bogus 签名
  → 页面上下文内 byted_acrawler.frontierSign() 生成签名
  → fetch /aweme/v1/web/general/search/single/ → type=4 user_list 提取用户
- 实测: 搜"大斌子" → 「大斌子（传媒副总版）」465.8万粉(与用户截图一致)
- 触发风控 → 诚实 RATE_LIMITED/BLOCKED, 不自动绕

### Search Core V3 收尾
- search.py: 抖音分支 → search_douyin_logged_in(登录态), 不再强制 BLOCKED
- deduplicate: 同分保留粉丝更高的(平台实时 > local 占位)
- platform=all 聚合: 抖音 SUCCESS + 粉丝数完整

## v0.3.13 (2026-08-13 23:40, 搜索相关性 + 状态刷新修复 — 用户 4 项反馈)

### 问题 2: 虎牙/斗鱼搜索返回无关推荐(赛事/斯诺克)
- 根因: ?sk= 直达打开的是「直播」tab(房间标题匹配)→ 返回热门推荐而非昵称匹配
- 修复: 虎牙恢复「主播」tab 交互式流程(点tab+输入+回车) + **相关性过滤**(display_name 与 keyword 互相包含才保留)
- 斗鱼: 同样加相关性过滤(无登录时斗鱼返回热门推荐, 过滤后诚实 EMPTY)
- 效果: 搜"大斌子"虎牙只返回「798大斌子」; 斗鱼 EMPTY(确实无此主播); 搜"姿态"返回 Zz1tai姿态

### 问题 3/4: 首页直播状态冻结(下播仍显示直播中 / 已开播仍显示等待开播)
- 根因: **probe worker(轮询直播状态进程)未运行**(08:45 起 15h 无探测)→ last_status/live_sessions 冻结
- 修复: nohup 恢复 `python -m workers.probe.worker --loop --interval 30` 常驻
- 验证: 姿态 pa=86 移动版 eLiveStatus=2 + 桌面版 body.liveStatus-on 双确认在播; 状态每轮刷新

### 问题 1: 抖音粘贴链接 UX(用户以为要电脑端)
- 澄清: 手机抖音 App → 主播主页 → 分享 → 复制链接(v.douyin.com 短链)即可, 无需电脑
- 前端文案改为引导式提示; 后端 BLOCKED hint 同步更新

### v0.3.13 补充(23:50 第二轮修复)
- **虎牙解析重写**: 主播 tab 卡片 href 是 video/u/{uid}, 房间号在 title 属性 "房间号：数字"; 旧 a[href] 提取全漏 → "阿哲"等搜不到
- **斗鱼搜索重写**: 卡片是 CSS Modules 混淆类名 anchorInfo, 无 data-rid, 链接非数字 → 旧 a[href] 全漏; 改为卡片文本提取 "房间号数字" + 主播名 + 关注数(骚白→911房/1781万粉 ✅)
- **相关性过滤**: display_name 与 keyword 互相包含才保留(虎牙/斗鱼都加)
- **poll_deadline 修复**: 虎牙轮询截止 = min(deadline, now+5s), goto 耗时不再导致超 10s
- **probe worker 常驻**: 首页状态冻结根因是 worker 进程未运行(08:45 起 15h); nohup 常驻 `--loop --interval 30`; 姿态当前确在播(eLiveStatus=2 + body.liveStatus-on 双确认)
- **API 重启陷阱**: 无 --reload 后改代码必须重启 uvicorn(虎牙 EMPTY 假象即旧代码)

## v0.3.12 (2026-08-13 22:50, 搜索可靠性重构 — P0-09 Douyin Search False Negative)

### 根因(Network 层取证结论)

- 抖音**未登录态彻底关闭"按昵称搜主播"**: `/aweme/v1/web/search/item/` 返回 `status_code:2483 "请先登录"`;`/aweme/v1/web/search/user/` 已废弃(404 Unsupported path)
- H5 搜索 HTML 仅含 `aweme_info.author`(视频作者), 无完整用户列表, 无 `follower_count`;PC Web 是 RSC 流式 SSR, HTML 无任何 user 字段
- 因此旧策略"拦截 loadmore API + DOM 兜底"在抖音永远 False Negative(28s 白等)

### 后端改造(api/services/search_browser.py + search.py + routers/anchors.py)

- **结构化返回 V2**: `SearchResult{status, items, ms_used, hint, source}`;status ∈ SUCCESS/EMPTY/DEGRADED/TIMEOUT/BLOCKED/PARSE_ERROR
- **抖音**: `search_douyin` 直接返回 `BLOCKED`(0-4ms)+ hint "抖音搜索需登录,请粘贴主播链接" — 不再 28s 白等
- **新增 `parse_douyin_user_page(url)`**: 粘贴抖音 user 链接 → 打开主页(无登录)→ 从 SSR `<title>` 提取昵称(title 格式 "XXX的抖音 - 抖音";注意 live document.title 会被 RSC 清空,必须从 page.content() 拿)+ avatar
- **Layer 0 本地索引**: anchors.display_name ILIKE 精确命中 → 0 延迟返回(高置信度), 低置信度 merge 进 Layer 1 结果尾部
- **8s 硬超时**: 全部 browser 搜索走 `_clock()=time.perf_counter()` 统一单调时钟(修复 time.time/perf_counter 混用导致 ms_used 天文数字 bug)
- **虎牙优化**: `?sk=` 直达导航替代"点tab+输入+回车"(7s vs 8.6s),直达空结果才走交互式兜底
- **斗鱼优化**: 房间名 title 并行 fetch(Promise.all), 替代串行逐个请求(每个 ~1s)
- **B站 412 风控修复**: 补全 Accept/Accept-Language/Origin 浏览器头(缺这些直接 412);-412 时 800ms 间隔重试 1 次
- **`/anchors/_search` 升级为 SearchResponseV2**(status/items/ms_used/source/hint/platform/keyword)
- **`/anchors/parse` 抖音主页分支**: 接 parse_douyin_user_page, 粘贴链接返回真实主播名(如"似梦")而非"未知主播"

### 前端改造(miniapp/services/subscriptions.js + pages/add)

- `searchAnchors` 返回结构化 `{status, items, hint, ...}`(兼容旧数组响应)
- 搜索页 `applySearchResult`: BLOCKED → 警告条 + "粘贴链接更可靠" CTA;EMPTY/TIMEOUT → "粘贴链接试试";抖音平台固定提示条"抖音搜索需登录,推荐粘贴链接"
- 新增 `onPasteLinkCta()`: 一键切到链接模式
- 移除误导性文案"没有找到相关主播，换个名字试试"(仅真正 EMPTY 时显示)

### 回归测试(tools/regression_search.py)

- 6 关键词 × 4 平台矩阵: 抖音 BLOCKED 0-4ms; B站 204-1146ms SUCCESS/EMPTY; 虎牙 7.0-7.9s; 斗鱼 5.9-7.8s — 全部 8s 内, 全过
- 用法: `.venv/Scripts/python.exe tools/regression_search.py [--repeat N] [--kw 关键词]`

## v0.3.11 (2026-08-13 13:00,前端视觉与交互全面升级 — 前端工程师专家)

### 全局设计系统

- **app.wxss**: 设计 token(品牌色/字号阶梯/圆角/阴影)+ 通用组件(卡片/按钮/徽章/空状态/骨架屏/状态点)+ 安全区适配(safe-area-inset-bottom)+ 页面 max-width 居中(大屏友好)
- app.json: 全局背景色统一 #F4F6F8

### wxs 工具模块(utils/format.wxs)

- `relTime`: 相对时间(刚刚/x分钟前/x小时前/昨天/MM-DD HH:mm)
- `duration`: 开播时长(已播 2小时15分)
- `platformName/platformClass`: 平台显示名映射
- `fans`: 粉丝数缩写(755.5万)

### 页面升级

- **首页**: 骨架屏加载 → 错误重试 → 空状态引导添加;直播卡片平台徽章 + 绿色开播时长 + 呼吸红点 + hover 缩放反馈 + 在线主播数
- **订阅页**: 头像 + 平台徽章 + 直播中/未开播状态点(新增后端 is_live 字段)+ 骨架屏 + 空状态 + 下拉刷新
- **添加页**: 双 tab 图标化;搜索框清空按钮(✕);平台胶囊选择器;结果卡片整行可点 + hover;结果计数/排序提示;提示条(错误/信息)区分
- **详情页**: 骨架屏;主播头部卡片(大头像+平台标签);平台状态卡(呼吸红点直播中/灰未开播);最近记录带"已结束/直播中"状态徽章
- **我的页**: grant 余额渐变卡(品牌蓝渐变+消耗进度条+授权/使用/剩余三格看板)+ 通知记录状态中文("已发送/未送达")

### 交互细节

- 所有可点卡片 hover-class 缩放/背景反馈
- 首页/订阅/我的 下拉刷新(仅首页原有,订阅/我的新增)
- 加载中按钮 disabled + loading
- 空状态统一 emoji 图标 + 标题 + 副文案 + CTA 按钮

---

## v0.3.10 (2026-08-13 12:10,7 个 UX 问题修复 + 三平台浏览器搜索点亮)

### 用户反馈的 7 个问题全部修复

1. **搜索偶发"没找到"**: B站搜索接口偶发风控(返回非 JSON)→ 内存缓存(5min)+ 前端重试 2 次 + 区分"真没结果"/"服务不可用"
2. **列表数量 + 滚动**: limit 10→15,结果列表 scroll-view 可滚动
3. **排序**: 按粉丝数降序(大主播在前)
4. **搜索"直播中"误导**: B站 `is_upuser` 不是直播状态 → 改为 False 不再显示(实时状态以 probe 为准)
5. **详情页无头像/简介**: 订阅时传 avatar 存入 anchor;搜索/解析带头像 → 订阅列表和详情页显示头像
6. **搜索列表订阅/取消交互**: 未订阅显示「订阅」、已订阅显示「取消订阅」(红色),点击切换;后端 search 返回 subscription_id
7. **取消订阅后仍展示**: 前端取消成功后本地立即移除 + 后台刷新(修复竞态)

### 三平台浏览器搜索点亮(playwright)

- **虎牙** ✅: 搜索页输入关键词+回车(选可见 input),解析 .new-clickstat 卡片;实测搜"姿态"→ LPL003号选手等
- **斗鱼** ✅: 打开搜索页,从 href 提取 rid;实测搜"雨神"→ 相关主播
- **抖音** ❌ 需登录: 无登录态搜索返回空 → 明确 501"需登录,请用粘贴链接"
- chromium-1234 用国内镜像(npmmirror)下载成功
- **踩坑**: playwright 需要匹配版本 chromium(1208/1228 不够);虎牙搜索框有隐藏 input 需选可见的

### 端到端验证

虎牙搜"姿态"→ 订阅(LPL003,rid=333003)→ 详情含头像 ✅
抖音搜索 → 501 明确提示 ✅

### 能力矩阵更新

| 平台 | 名字搜索 | 主页订阅 |
|------|---------|---------|
| B站 | ✅ HTTP+cache | ✅ |
| 虎牙 | ✅ playwright | ✅ |
| 斗鱼 | ✅ playwright | ✅ |
| 抖音 | ❌ 需登录 | ⏳ sec_uid 保留 |

---

## v0.3.9 (2026-08-13 11:40,主播详情页 + 转换扫描器 + 浏览器搜索框架)

### 主播详情页(小程序)

- `pages/detail/`: 头像/简介/平台状态(直播中/未开播 + 当前 session)/最近直播记录
- 首页(正在直播)+ 订阅列表卡片 → 点击跳详情
- 端到端验证: 搜索德云色 → 订阅 → 详情(anchor_id=81)✅

### 全站转换扫描器(替代盯梢,提高 Gate 0B 转换捕获率)

- `experiments/transition_scanner.py`: 每 20min 拉虎牙前 5 页在播列表,对比上轮:
  - 消失房间 → adapter 验证 → 真 OFFLINE = **ONLINE→OFFLINE 转换**(Gate 0B 标准 #3 要的)
  - 新增房间 → adapter 验证 → 真 ONLINE = **OFFLINE→ONLINE 转换**
  - 排序波动已被验证步骤过滤(6 个候选全 ONLINE 的教训)
- dry-run 已捕获 3 个真实开播(WY--甜贝贝 等)✅,正式扫描 20min/轮 后台跑中

### 浏览器搜索框架(抖音/虎牙/斗鱼)

- `api/services/search_browser.py`: playwright 读搜索页 DOM(绕过抖音 X-Bogus)
- `search.py` 扩展: 4 平台统一 search_anchors(bilibili HTTP + 其余浏览器)
- chromium 下载中(网络慢),装好后即测

### 核心闭环验证(重要)

**订阅未开播主播 → probe worker 自动接管**:
- 订阅德云色(B站主页,未开播)→ pa=84 创建 → probe worker 探测 → OFFLINE ✅
- 一旦开播 → CONFIRMED_ONLINE → 微信通知(完整产品价值链)

---

## v0.3.8 (2026-08-13 10:55,主播搜索 + 主页订阅 — 产品核心修正)

**回应"订阅开播通知应支持未开播主播"——双能力落地**。

### 后端

- **`GET /api/v1/anchors/_search`**: 按名字搜索主播
  - B站官方搜索接口(返回名字/头像/粉丝数/是否已订阅)— 实测搜"德云色" ✅
  - 虎牙/斗鱼/抖音: 数据 JS 异步加载 + 需 X-Bogus 签名 → 返回 501 明确错误(后续 playwright 浏览器方案)
  - 容错: B站风控时返回空列表而非 500
- **`POST /api/v1/anchors/parse` 支持主页 URL**(未开播也能订阅):
  - B站 `space.bilibili.com/{mid}`: 免签名 card 接口拿名字/头像;adapter 对主页返回 OFFLINE(未开播探测正常)
  - 抖音 `douyin.com/user/{sec_uid}`: 保留 sec_uid 为主 user_id(名字需浏览器)
  - 虎牙/斗鱼房间号即主播 ID(天然支持主页)
- 修复: 旧的抖音 URL 分支(只支持数字)与新分支重复 → 删除旧分支
- ⚠️ 踩坑: 多 uvicorn 进程并存占端口导致"改代码不生效" → 全杀重启

### 小程序添加页(双入口)

- 搜索 tab: 平台选择(B站/抖音/虎牙/斗鱼)+ 名字搜索 → 结果列表(头像/粉丝/直播中)点击订阅
- 链接 tab: 原粘贴链接流程(支持主页 URL)
- 统一订阅流程 confirmSubscribe: 先授权 → 三态互斥(订阅+提醒/仅订阅/不订阅)

### 能力矩阵(记录)

| 平台 | 名字搜索 | 主页 URL 订阅 |
|------|---------|--------------|
| B站 | ✅ 官方 API | ✅ space + card 接口 |
| 虎牙 | ⏳ 浏览器 | ✅ 房间号即 ID |
| 斗鱼 | ⏳ 浏览器 | ✅ 房间号即 ID |
| 抖音 | ⏳ 浏览器+X-Bogus | ⏳ sec_uid 保留,名字待浏览器 |

---

## v0.3.7 (2026-08-13 10:00,Gate 4 小程序原生骨架完成)

**ADR-003 落地:微信原生小程序工程(非 Taro)初始化完成**,25 个文件。

### 工程结构(miniapp/)

```
miniapp/
├── app.js / app.json(tabBar 3 tab)/ project.config.json(正式号 appid)
├── services/     — API 封装: api / auth(登录)/ lives / subscriptions / notifications
└── pages/
    ├── home/          — 首页:正在直播(lives/active)+ 下拉刷新
    ├── add/           — 添加订阅:粘 URL → parse → 确认 → requestSubscribeMessage + request-grant
    ├── subscriptions/ — 我的订阅:列表 + 取消(确认弹窗)
    └── profile/       — 我的:grant 余额 + 通知记录
```

### 关键实现

- **登录链**: onLaunch → wx.login → code2session → openid 存 globalData
- **添加链**: URL 解析 → 订阅 → 弹微信授权(requestSubscribeMessage,模板 ID 已填)→ accept 计数 → request-grant(ADR-002 累积)
- **grant 展示**: available = granted - consumed(不是配额,是用户行为余额)
- 所有 JS 通过 node --check 语法验证

### 待真机验证

- [ ] 微信开发者工具导入 miniapp/ → 真机预览
- [ ] 登录(需正式号合法域名)
- [ ] 添加订阅全链路
- [ ] 收到真实开播通知(Gate 3 收尾)

---

## v0.3.6 (2026-08-13 09:50,API 补齐 — 小程序数据源就绪)

**11 个 REST 端点全部实现 + 实测通过**(契约见 API-SPEC.md)。

### 新增路由(3 个新文件)

- `api/routers/anchors.py`: POST /anchors/parse(粘 URL 解析,4 平台)+ GET /anchors/{id}(详情含实时状态)
- `api/routers/lives.py`: GET /lives/active(我订阅的正在直播)+ GET /lives/recent(最近 24h 开播)
- `api/routers/notifications.py`: GET /notifications/grants(余额)+ POST /request-grant(授权,5min 限频 + 1h 上限)+ GET /history(通知记录,游标分页)

### 实测验证(全绿)

- **grant 闭环**: request-grant(1 次)→ granted=1 available=1 ✅;5min 内重复 → 429 ✅;累积储备 ADR-002 ✅
- **订阅闭环**: POST subscriptions → lives/active 立即返回正在直播的主播 ✅
- **URL 解析**: bilibili/douyin/huya 全部正确,非法 URL → 400 ✅
- **修复 bug**: history 查询误用 NotificationJob.platform_account_id(模型无此字段)→ 改为经 LiveSession 反查
- 注: auth/login 测试 code 预期失败(生产走真实 wx.login code2session)

### 小程序数据源就绪清单

首页(lives/active)· 添加订阅(anchors/parse)· 我的订阅(subscriptions)· 我的(grants/history)

---

## v0.3.5 (2026-08-13 09:30,Gate 0C 分析 + Gate 2 补全 + Gate 4 选型)

**在等待虎牙/斗鱼白天 soak(4h)期间并行推进的 3 块工作**。

### C6 数据分析(Gate 0C 关键产出)

- 昨晚 C6(23:46-00:51):B站/抖音各 14 探测(300s 间隔)**全部成功零限流**(B站 avg 181ms / 抖音 avg 344ms)
- **限流判定规则 v0.1** 写入 gate_0c_plan.md §0.5:
  - HTTP 429/403 → RATE_LIMITED(立即退避)
  - `HTTPSConnectionPool` 连接超时连续 3 次 → RATE_LIMITED
  - 慢响应 >5× 基线连续 5 次 → RATE_LIMITED
  - 退避 `30s × 2^n` 封顶 8min;累犯(冷却 <48h)封顶 30min;冷却 ≥2h 恢复

### Gate 2 补全(探测引擎健壮性)

- **aiolimiter** 每平台令牌桶限流(默认 1 req/s)
- **熔断降级**:连续 5 失败 → DEGRADED(探测降频 5×,事件标 low confidence);连续 20 失败 → DISABLED
- **probe_runs telemetry** 持续写入(审计):已验证 4 条完整(platform/success/state/latency)
- worker 循环异常捕获(进程不再因单次错误崩溃)

### ADR-003: 客户端选型定案(微信原生,不用 Taro)

- Taro 4 尚未发布(2026-04 仍 Taro 3 主流)
- V1 只做微信 → 原生性能优(首屏 320 vs 450ms)+ 包体积最小(不逼近 2MB)
- 未来多端再评估 Taro 4/uni-app,单页迁移成本可控

### 当前后台(09:30)

| 进程 | 状态 |
|------|------|
| 虎牙/斗鱼 4h soak | 🟢 09:20 起,13:20 收 |
| 转换盯梢(5 房间) | 🟢 60s 间隔,等下播捕获转换 |
| Probe worker v2 | 🟢 限流+熔断+telemetry |
| API + Docker | 🟢 |

---

## v0.3.4 (2026-08-13 00:40,Gate 3 Notification Engine 完成)

**开播 → 微信触达的最后一块拼图完成**(mock 验证)。

### WeChat 投递 worker(workers/notify/wechat.py)

- 消费 notification_jobs(PENDING),按 **grant 决策树**发送:
  - 有 grant → send,成功 consumed+1,delivery SENT
  - 无 grant → fallback in_app(no_grant),不调微信
  - **43101** → grant 失效(consumed+1)+ fallback in_app
  - **45009/40001/42001/5xx** → 指数退避重试(10s→300s 封顶,8 次),grant 保留
  - **40037** → 模板错误 + fallback in_app,grant 保留(platform_adapters 不受影响)
- **model 新增**: notification_jobs.attempt + next_retry_at(指数退避调度)
- 迁移 `c23b5e229894`(手动编写,链: 5354a9ed7741 → c23b5e229894)

### In-App 兜底 worker(workers/notify/in_app.py)

- 扫描 >1h 未处理的 PENDING job → 兜底 in_app delivery(幂等:已有 in_app 则跳过)

### 测试(全部 mock 微信,不真发)

- `tests/test_notify_engine.py`: 成功/无grant/43101/45009/40037 — **5 组全过**
- 4 套件合计 14 组测试全绿

### 验收对照(ROADMAP Gate 3)

- [x] grant 用完后自动转站内(无 grant → in_app fallback)
- [x] 微信 43101 → grant 失效 + fallback
- [x] 微信 40037 → disable 模板(worker 层处理,不影响 platform adapter)
- [x] 微信失败自动 fallback in_app
- [ ] 真机收到微信订阅消息(需真机 + 真实模板 ID 配置,待用户确认)
- [ ] 点通知跳 anchor 详情页(需 Gate 4 小程序)

---

## v0.3.3 (2026-08-13 00:33,Gate 2 Detection Engine 启动:Probe Worker)

**Gate 1 全部验收达成,进入 Gate 2(探测引擎)**。

### Probe Worker(workers/probe/worker.py)

- 从 platform_accounts 表按 **polling_tier 分级轮询**(hot 60s / warm 300s / cold 900s)
- 同步 adapter(requests)放 `asyncio.to_thread` 线程池,不阻塞事件循环
- 4 平台真实账号端到端跑通: huya/douyu/bilibili → ONLINE, douyin → OFFLINE
- 状态机正确演进: 首次探测 → SUSPECT_ONLINE,二次确认 → CONFIRMED_ONLINE + OPEN session
- ⚠️ 坑1: `async_sessionmaker` 默认 `expire_on_commit=True` → commit 后 pa 过期 → async lazy load 炸 MissingGreenlet → 必须 `expire_on_commit=False`
- ⚠️ 坑2: adapter 是同步代码,必须 `to_thread` 包装

### ROADMAP Gate 1 验收全达成

- [x] `alembic upgrade head` 从空库成功
- [x] 状态机所有转换都有测试(5 组全过,含新增抖动测试)
- [x] 1000 个 LiveEvent fan-out 不重复(集成测试)
- [x] 抖动 online→offline→online 只产生一次 CONFIRMED_ONLINE

### 后台运行

- Probe worker: `nohup python -m workers.probe.worker --loop --interval 30`(持续探测 4 平台)
- API: 127.0.0.1:8899
- 后台 Gate 0 实验仍在旧目录 live-radar(明早 10:27 收)

---

## v0.3.2 (2026-08-13 00:24,Gate 1 Domain Core 核心完成)

**Gate 1 三验收项全部达成**(ROADMAP: alembic 迁移可跑 + 状态机全测 + 1000 事件去重不重不漏)。

### Alembic 迁移(验收 #1 ✅)

- `alembic init migrations` + 异步 env.py(asyncpg)
- 初始迁移 `5354a9ed7741`(11 张表 + partial unique index + 全部索引)
- **`alembic upgrade head` 从空库成功**(DROP SCHEMA 后实测)
- 坑: alembic.ini 含中文注释会被 configparser cp1252 拒绝 → 注释改 ASCII

### LiveSessionEngine 开播检测引擎(核心领域服务)

- `core/live_session_engine.py`: 探测 → 状态机 → 事件/session/fan-out 全链路
- 三重去重: ① OPEN session 每 pa 仅 1 个(应用层查 + partial unique 兜底)② CONFIRMED 事件只产生一次 ③ notification_job 每 (event, user) 唯一(应用层查 + UNIQUE 兜底)
- 修复 bug: `_fanout_jobs` 误把 event_type 字符串当 live_event_id 传 → 改为 `_record_event` 返回真实 event_id
- `JSONBCompat` TypeDecorator: PG 用原生 JSONB,SQLite 单测退化为 JSON

### 测试(验收 #2/#3 ✅)

- `tests/test_live_session_engine.py`(PG): 完整循环 / OPEN session 去重 / job 去重 / 限流不转换 — **4 组全过**
- `tests/integration_1000_events.py`(PG): 10 主播 × 100 探测 = **1000 事件不重不漏**
  - LiveEvent=1000 / OPEN=0 / CLOSED=250 / Job=500 全对
  - fan-out 重放幂等(UNIQUE 兜底)
  - 事件分布 SUSPECT/CONFIRMED × ONLINE/OFFLINE 各 250 完美均衡

### 待办(下一阶段)

- Gate 2 Detection Engine: workers/probe 调度器(接 platform_adapters 真探测)
- Gate 3 Notification Engine: fan-out worker + 微信 send(复用 Gate 0A 实测逻辑)
- Alembic 迁移版本管理进 git

---

## v0.3.1 (2026-08-13 00:06,项目改名)

**项目更名**: Live Radar(主播雷达)→ **StageLetter(开场信)**;仓库 `live-radar` → `stage-letter`。

- 全量替换 34 个文件 92 处:`Live Radar`→`StageLetter`、`live-radar`→`stage-letter`、`live_radar`→`stage_letter`、`liveradar`→`stageletter`(docker/DB)、`LIVE_RADAR_`→`STAGE_LETTER_`(环境变量)、`主播雷达`→`开场信`
- Docker 容器: `liveradar-postgres/redis` → `stageletter-postgres/redis`(重建,端口 5433/6379 不变)
- PostgreSQL: 用户/库/密码 `liveradar` → `stageletter`,11 张表重建
- 已验证: FastAPI `app="StageLetter"`、订阅链路、models/状态机导入全绿
- miniapp 工程名: `grant-test` → `stageletter-grant-test`
- **后台实验(Gate 0)仍在旧目录 `live-radar` 运行(相对路径不受影响),明早汇总后迁移数据并删除旧目录**

---

## v0.3.0 (2026-08-12 晚,Gate 1 骨架启动 — 与 Gate 0 实验并行)

**决策**:Gate 0 是决策门槛(防容量/风控未验证时写死架构),但项目骨架 / DB 模型 / 基础设施**不依赖实验结论**,可以并行启动。所有模型严格按 DATA-MODEL.md 定义。

### Gate 1 骨架交付

- **目录结构**:`api/`(FastAPI)+ `core/`(config/db/models/state_machine)+ `workers/` + `tests/` + `migrations/`(空)
- **core/config.py**:环境变量配置(`STAGE_LETTER_` 前缀,支持 .env)
- **core/models.py**:11 张表 SQLAlchemy 2.x ORM(users/anchors/platform_accounts/user_subscriptions/live_sessions/live_events/wechat_subscription_grants/notification_jobs/notification_deliveries/platform_health/probe_runs),含全部不变量(partial unique index:OPEN session 每平台账号仅 1 个等)
- **core/state_machine.py**:OFFLINE → SUSPECT_ONLINE → ONLINE → SUSPECT_OFFLINE → OFFLINE 抗抖动状态机(单元测试 3 组全过)
- **api/services/wechat.py**:复用 Gate 0A 实测逻辑(access_token 缓存、code2session、5 字段模板 payload、grant 乐观记账注释)
- **api/routers/**:`auth.py`(微信登录)+ `subscriptions.py`(订阅/取消/列出,upsert 语义)
- **docker-compose.yml**:PostgreSQL 16 + Redis 7(**PG 映射 5433** — 本机已有 PG 占 5432)
- **requirements.txt** / **.env.example** / **.gitignore**(安全:Secret 不入 git)

### 实测验证(全绿)

- 11 张表在 PostgreSQL 16 创建成功
- FastAPI 4 路由注册:`/health` + auth/login + subscriptions CRUD
- 完整业务链路:订阅 B站主播 → 订阅抖音主播 → 重复订阅(upsert)→ 列出订阅 → 全部正确
- 中文 UTF-8 存储/读取正确(之前 curl 显示 ?? 是 Windows 控制台编码,非存储问题)
- 状态机 3 组测试(完整循环/抖动/非直播态不转换)全过

### 待办

- Alembic 迁移初版(v0.3.1)
- workers/probe 调度器(Gate 2)
- 微信通知 fanout(Gate 3)
- Taro 小程序(Gate 4)

---

## v0.2.2 (2026-08-12,Gate 0A PASS)

Gate 0A 微信通知真实性实验**全部通过** — 正式号 `wx370fb6f14d4a4a26`(末4位 4a26)真机实测。

### Gate 0A PASS — 6 实验全绿

- **A3-1/2/3 PASS**:授权→发1条(errcode=0,msgid 4646537231497920512);不授权→43101;重新授权→再发成功(msgid 4646539401026830337)。grant 核心模型成立
- **A3-4 UNEXPECTED_POSITIVE(GRANT_CUMULATIVE)**:连续授权2次→2条全送达。**微信 grant 是储备式计数,授权 N 次 = 储备 N 条额度,可跨时间消耗** → V1 可设计"授权储备"交互避免反复弹窗;触发 ADR-002 增量更新(不降级)
- **A3-5 PASS(含伪阳性澄清)**:伪造 accept 在余额耗尽后必返 43101。**send 端是唯一真实 authority**,后端乐观记账可被污染但不致命。教训:伪造实验前必须先耗尽真实 grant,否则残留 grant 造成"假成功"
- **A3-6 PASS**:微信「服务通知」拒收后 send 立即返回 43101,拒收彻底且即时

### 关键决策

- **V1 维持"微信开播提醒器"定位**,Gate 0A 正式 PASS,进入 Gate 0B
- 模板「直播开播通知」5 字段(thing1/thing2/time3/thing5/thing6),比 v0.2 设计多 2 个,payload 已适配
- 测试号无订阅消息权限(无服务类目)→ 正式号解决;`experiments/probe_subscribe_message.py` 留作回归测试

### ADR-002 增量更新(Grant 累积储备)

Gate 0A 实测发现授权可累积(GRANT_CUMULATIVE),已同步全部文档:

- `WECHAT-NOTIFICATION-SPEC.md`:§1.1 修正"独立计次"描述 + §1.4 补充 3 条实测事实 + §2.1 新增"授权储备"交互设计 + §2.3 业务规则标注可累积 + **§11 新增 ADR-002 全文**
- `DATA-MODEL.md`:§7 `granted_count` 语义标注"可累积储备"
- `ARCHITECTURE.md`:§11 决策表 ADR-001 → ADR-001+ADR-002;头部加 v0.2.2 变更说明
- `PRD.md`:F5.1 grant 规则标注可累积 + 新增授权储备交互说明

### 新增文件

- `experiments/miniapp-grant-test/`(最小授权测试小程序,真机弹窗用)
- `experiments/verify_template_owner.py`(模板归属验证)
- `experiments/probe_subscribe_message.py`(订阅消息能力探测)
- `experiments/data/run-grant-20260812-2311.log`(实验原始日志)

---

## v0.2.3 (2026-08-12 晚,Gate 0C 启动)

Gate 0C 压测方案启动:脚本就绪 + C3 批量端点重大发现。

### Gate 0C 计划与脚本

- `reports/gate_0c_plan.md`:完整压测方案(C1 QPS 阶梯 / C2 风控阈值 / C3 batch / C4 签名 / C5 capacity / C6 因果实验)
- `experiments/throughput_test/c6_ratelimit_causality.py`:连接超时→RATE_LIMITED 判定实验(4 平台 dry-run 通过)
- `experiments/throughput_test/c1_qps_ladder.py`:QPS 阶梯压测(0.02→5 req/s,dry-run 通过)
- `experiments/batch_probe/c3_batch_probe.py`:批量端点探测

### C3 批量端点重大发现(2026-08-12)

| 平台 | 批量端点 | 单请求房间数 | 漏检? |
|------|---------|-------------|-------|
| 虎牙 | `cache.php?m=LiveList&do=getLiveListByPage` | 120 × 82 页 | **❌ 有**(3 在播只命中 2) |
| 斗鱼 | `directory/all`(页面内嵌 JSON) | 40/页 | **❌ 有**(4 在播只命中 1) |
| B站 | `getWebAreaList` | -400 需签名 | ⏳ |
| 抖音 | `webcast/feed` | N/响应 | ⏳ |

**核心结论**:两个平台的"在播列表"都是**推荐位排序,不覆盖全部在播房间**(活动/冷门房可能缺失)。列表快照**不能单独用**,必须"列表快照(覆盖热门)+ 单房间补漏"混合。V1 容量模型需按混合策略重算。

**待办**:C6/C1 实跑需等 Gate 0B 虎牙/斗鱼 12h soak 结束(8/13 10:27),避免同 IP 叠加限流混淆归因。

---

## v0.2.1 (2026-08-02 ~ 08-06,Gate 0B 实测)

Gate 0B 实测驱动的增量修正(9 点修正指令 + 4 天浸泡实测)。

### P0 修正:Gate 0B 状态口径统一为 IN PROGRESS

- README / reports / GATE-0.md 全部把"冒烟通过/全部就绪"改为 **Gate 0B — IN PROGRESS**
- 明确 transport(✅ 已过)≠ correctness(⚠️ 未过),不得混用

### P0 修正:7 态跨平台框架落地

- 新增 `platform_adapters/common.py`:`LiveStatus` 7 态枚举 + `classify_platform_status()` + `classify_error()` + `is_placeholder()`
- 4 平台 adapter 全部升级 7 态返回 + placeholder 短路(NOT_FOUND,不调 API)
- **禁止**字段缺失/HTML 异常/placeholder 静默归为 OFFLINE(无 silent parse failure)
- 24h 浸泡脚本支持 `--soak-type {correctness,transport,error-path}` + 7 态分布/转换分离统计

### P0 修正:微信 grant 模型 authority 澄清(wechat_grant.md)

- A3-5 改名"微信服务端是否强制验证真实订阅授权"
- **真实 authority = `subscribeMessage.send` 返回码**;客户端 accept 仅作 optimistic ledger 输入
- 删除"前端签名 + 后端验签"方案(客户端可 patch,签名形同虚设)
- A3-4 N>1 → `UNEXPECTED_POSITIVE`,触发 ADR 增量更新但**不**自动降级多通道

### P1 修正:实测发现(→ Gate 0C 输入)

- **平台限流是连接超时非 429**(B站/虎牙/斗鱼):慢响应 150-300s + `HTTPSConnectionPool` 拒连
- **B 站累犯加速限流**:首犯 8.3h,冷却 2 天后 25min 即触发 → 单 IP 匿名不可持续
- 新增 GATE-0 Gate 0C C6 因果实验(连接超时→RATE_LIMITED 判定 + 退避参数)
- `-1` 归类保持 PARSE_ERROR(保守),待 C6 结论,不改语义

### 新增

- `experiments/supervise_soak.sh`:soak 监督器(2h 批次 + 自动重启,解决后台进程被杀丢数据)
- `experiments/analyze_soak.py`:跨文件 JSONL 汇总(7 态分布/转换/错误/latency)
- B 站 Correctness PASS(2 次真实 ONLINE→OFFLINE 转换,8/6 soak 二次确认)
- 虎牙样本换时段性主播(JackeyLove/活动主播/轮播厅)提高转换捕获率
- 抖音 web_rid 自主获取调研结论:web 端混淆/加密,必须用户提供

### 🎉 抖音突破(2026-08-06 晚,浏览器自动化)

- **web_rid 真相**:直播间 URL 用 10-13 位短数字(如 `496999661018`),不是 19 位;19 位 `id_str` 是内部 room_id,两者不同(之前全 NOT_FOUND 的根因)
- **提取方法**:playwright 无头 chromium 监听 `live.douyin.com/webcast/feed` 推荐流 API,提取 item 顶层 `web_rid` 字段 → 20+ 候选 → 5 个验证 ONLINE
- **enter API 改版适配**:房间详情从 `data.room` 移到 `data.data[0]`(status/status_str/title/owner),`data.room_status`/`data.enter_room_id` 为新字段;`parse_url` 接受 10-25 位数字
- **新增工具**:`experiments/extract_douyin_webrids.py`(feed 监听提取)、`experiments/sniff_douyin_api.py`(网络嗅探)、`experiments/verify_douyin.py`(web_rid 验证)
- 抖音从 NOT TESTED → 5 个真实 ONLINE 数据就绪,6h correctness soak 启动(`mjcJoQ`)
- 斗鱼房间 1000 浏览器验证:房间存在(主播 hsj1207)+ video 空占位 = 权威 OFFLINE 基线 ✅

## v0.2 (2026-08-01 晚)

基于对 v0.1 的深度审计(用户原文逐条复核),修正 P0 / P1 问题。

### P0 修正

#### 1. 微信订阅消息模型完全重构

**v0.1 错误假设**:
- 初始 8 次 / 季度重置 8 次 / refresh +8
- 服务端可校验"一次性 ticket"
- 付费买 8 次微信提醒

**微信真实机制**:
- 一次性订阅消息:用户每次**主动授权** → 对应 template_id 获得**一次**发送机会
- 没有"余额"概念,没有"季初重置"概念
- `wx.requestSubscribeMessage` 只回调给客户端,服务端拿不到 ticket
- 没有"查询用户授权状态"的 API

**v0.2 新模型**: `wechat_subscription_grants` (乐观记账 + reconciliation)
- `granted_count`: 客户端回调 accept 后 +1
- `consumed_count`: 实际 send 成功后 +1(4xx 用户拒收也 +1,grant 失效)
- `available = granted - consumed`(应用层计算)
- 初始值 = 0
- 无季度重置

**影响文件**:
- WECHAT-NOTIFICATION-SPEC.md(整篇重写,含 ADR-001)
- DATA-MODEL.md (§4 改 UNIQUE / §7 换表 / §11 probe_runs 挪 Gate 2 / §12 不变量 / §13 查询)
- PRD.md (§F5 重写 / §N1 SLA 重写 / 验收标准)
- ARCHITECTURE.md (§5 通知流更新 / §6 SLA 分级 / 新增 §5.4 分级轮询)
- API-SPEC.md (§6 refresh 改名 request-grant)
- PRODUCT.md (§核心场景 2、3 / §产品原则)

#### 2. 平台容量 vs Adapter 限流矛盾

**v0.1 矛盾**: PRD 假定 18,000 主播 / 5min = 60 req/s,Adapter Spec 限流 1-2 req/s。两者无法共存。

**v0.2 修正**:
- 引入**分级轮询**: hot 30s / warm 5min / cold 30min
- V1 总主播数 = 各平台 max 之和(由 Gate 0C 实测倒推)
- Gate 0C 必须测量每平台持续 QPS、403/429 阈值、batch endpoint 可用性
- 在 Gate 0C 完成前,**V1 主播数上限是 unknown**

**影响文件**:
- ARCHITECTURE.md (新增 §5.4 分级轮询 + §6 容量计算)
- PLATFORM-ADAPTER-SPEC.md (§8.1 限流标"待 Gate 0C 测量" / 新增 §13 capacity.md 模板 / §7 DEGRADED 新行为)
- GATE-0.md (新增 Gate 0C)

#### 3. SLA vs 检测频率矛盾

**v0.1 矛盾**: PRD 定 <3min p95,但 5min 轮询 + 30s 二次确认 = 5.5min+。数学上不可能。

**v0.2 修正**: 按平台分级 SLA(SLA 是 provisional,Gate 0C/D 后定稿)

| 平台 | 检测方式 | SLA p95 | 备注 |
|------|---------|---------|------|
| Twitch | EventSub webhook | < 30s | 官方事件,可信 |
| B 站 | API 轮询 | < 5min | 待 Gate 0C 验证 |
| 虎牙 | API 轮询 | < 5min | 待 Gate 0C 验证 |
| 斗鱼 | API 轮询 | < 5min | 待 Gate 0C 验证 |
| 抖音 | 网页/接口 | < 8min | 受限最多,可能要降主播数 |

**影响文件**:
- PRD.md (§N1 SLA)
- ARCHITECTURE.md (§6 SLA 分级)

### P1 修正

| # | v0.1 问题 | v0.2 修正 |
|---|----------|----------|
| 1 | Gate 0 24h / 72h 冲突 | 统一为"冒烟 2h → 稳定性 24h → 最终 72h" |
| 2 | `probe_runs` 在 DATA-MODEL 标 V1.1 但 ROADMAP Gate 2 要 | 移入 Gate 2(轻量 probe telemetry) |
| 3 | openid 加密同时写"V1 AES+KMS"和"V1 明文" | 定 **V1 明文 + V2 KMS**,不再自相矛盾 |
| 4 | Subscription 同时存 anchor_id + platform_account_id,UNIQUE 不明确 | 改 UNIQUE `(user_id, platform_account_id)`,更直接 |
| 5 | DEGRADED 平台一刀切静默 | 仍通知,但**提高确认次数 + 标记低 confidence** |
| 6 | 微信 40037 disable 直播平台 | 改为 disable 微信模板 ID,不影响平台 adapter |
| 7 | Taro 3 / Taro 4 自相矛盾 | **Gate 4 再定** |
| 8 | Admin 搜 openid 直接显示 | 默认 mask,如 `o***********abc` |

### 新增

- `CHANGELOG.md`(本文件)
- `ADR-001: 微信订阅 grant 模型`(嵌入 WECHAT-NOTIFICATION-SPEC §10)
- Gate 0 拆分为 **0A → 0B → 0C → 0D → 0E**,**0A 微信通知真实性实验排第一**
- 每平台 `capacity.md` 测量模板(GATE-0 §3.5)

### 保留(确认无误)

- Dramatiq(暂不换 Celery)
- Twitch EventSub 独立 worker,不参与轮询
- Admin V1 轻权限(IP 白名单 + admin token)
- NON-GOALS 清单
- 产品一句话:"我关注的人开播了,第一时间告诉我。"
- `live_sessions` partial UNIQUE
- 多租户去重检测模型
- 平台 adapter A/B 类分类

### v0.2 后仍未决定

- 产品名(暂定"开场信 / StageLetter")
- License(暂定"待定")
- V1 主播总规模上限(等 Gate 0C)
- 抖音适配器是否进 V1(等 Gate 0C,若 QPS 太低可能降级)

## v0.1 (2026-08-01 早)

初始立项包,12 个文档。已废弃。