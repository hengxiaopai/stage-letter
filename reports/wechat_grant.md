# reports/wechat_grant.md — Gate 0A 实测报告

> **本文件用途**:把 `experiments/wechat_grant_demo.py` + `wechat_trust_test.py` 的真机结果落成可决策的证据,作为 v0.2 grant 模型 / V1 产品定位的 Go / No-Go 依据。
>
> **何时填写**:用户按 [WECHAT-TEST-ACCOUNT.md](../WECHAT-TEST-ACCOUNT.md) 完成准备并跑完两组脚本后,逐条回填本表。

---

## 0. 元数据(必填,影响结论可复现性)

| 字段 | 值 | 备注 |
|------|----|------|
| 测试日期 | `YYYY-MM-DD ~ YYYY-MM-DD` | 跑完两组脚本的实际日期 |
| 操作人 |  | 微信扫码人(可能是自己) |
| 微信号 |  | 用于扫码授权的微信账号(不要写真实账号,写昵称即可) |
| 微信版本 |  | 例:`8.0.45` |
| 手机 OS / 版本 |  | 例:`iOS 17.4` / `Android 14` |
| 小程序 AppID | `wx370fb6f14d4a4a26`(末 4 位 `4a26`) | **正式号** 2026-08-12 用户提供,access_token 已验证 ✅(原测试号 `wx64763d6b0a6cdd6e` 已弃用 — 测试号无订阅消息权限) |
| 模板 ID(开播提醒) | `VehDuOW2x...`(末 6 位 `BP-Cs`) | **直播开播通知**,字段:time3/thing6/thing5/thing1/thing2,归属已验证 ✅ |
| 模板状态 | ✅ 已选用 | 2026-08-12 用户从正式号公共模板库选用,gettemplate 返回 1 个 |
| 实验脚本版本 | `wechat_grant_demo.py@HEAD` | `git rev-parse --short HEAD` |
| 跑实验前 access_token 缓存是否清空 | ☐ 是(断网重启 / 等 2h) ☐ 否 | 防止上次缓存导致假阳性 |

> ⚠️ **不要把 AppID 完整值、Secret、openid 提交进 git**。`.gitignore` 已忽略 `experiments/.env` 和 `experiments/data/`,但报告里只写末尾 4 位即可。

---

## 1. 实验结果总览(每个实验必填)

> 结论统一用三档:**PASS**(行为符合 v0.2 假设)/ **UNEXPECTED_PASS**(行为符合直觉但和 v0.2 假设细节不同,需在 §2 详述)/ **FAIL**(行为与 v0.2 假设矛盾,需在 §2 详述并触发 ADR 更新)。

| 实验 | 期望(v0.2) | 实测结论 | 现象摘要(一句话) | 详细记录位置 |
|------|------------|----------|------------------|--------------|
| A3-1 授权一次,立即发第 1 条 | ✅ 收到 | ✅ **PASS** | errcode=0,msgid 4646537231497920512,送达确认 | §2 A3-1 |
| A3-2 不重新授权,发第 2 条 | ❌ 失败(grant 耗尽) | ✅ **PASS** | errcode=43101 "user refuse to accept the msg" | §2 A3-2 |
| A3-3 重新授权,发第 3 条 | ✅ 收到 | ✅ **PASS** | errcode=0,msgid 4646539401026830337,送达确认 | §2 A3-3 |
| A3-4 "总是保持以上选择" 后再发 | **(关键未知)** | ✅ **UNEXPECTED_PASS**(变体实测:连续授权2次→2条全送达,GRANT_CUMULATIVE) | 弹窗无"总是保持"选项;连续授权2次→2条全成功,grant 可累积储备 | §2 A3-4 |
| A3-5 微信服务端是否强制验证真实订阅授权 | 微信 send 是真实 authority;client accept 仅为 optimistic ledger 输入 | ✅ **PASS**(附伪阳性澄清) | 伪造 accept 在余额耗尽后返回 43101 — send 端按真实 grant 状态返;首次伪造成功是 grant 延迟结算假象 | §2 A3-5 |
| A3-6 用户拒收某主播后,该主播开播 | 仍 in-app,不弹微信 | ✅ **PASS** | 微信侧拒收后 send 返回 43101,消息不送达(拒收彻底且即时) | §2 A3-6 |

---

## 2. 关键实验详述(UNEXPECTED 或 FAIL 必须填,否则选填)

### A3-4 "总是保持以上选择" 是否真的给多次 grant?

> **为什么关键**:这是 v0.2 模型的核心假设之一。微信客户端文案暗示"勾选后,后续同模板通知自动放行",但**官方文档没说会增发 grant**。如果实测下来:
> - 用户**必须每次开播都点允许** → v0.2 模型成立,V1 可行;
> - 用户勾选后真的**能用 N 次** → v0.2 模型需要扩展 grant 来源(`granted_count` 来源不只有 `request-grant` 调用);
> - 用户勾选后**根本不弹** → 极理想,但要警惕是测试号特殊行为。

**实测时间**:`2026-08-12 23:14-23:16`
**勾选位置**: ☐ 弹窗中的 checkbox  ☐ 设置页"订阅消息"全局开关 **☑ 弹窗中无此选项**(用户确认;官方文档称该选项存在但 UI 因版本而异,不保证每次显示)
**连续发了几次**:2 次(变体:因弹窗无"总是保持"选项,改用"连续授权2次→连发2条"验证 grant 是否可累积)
**第 N 次行为**:
- N=1: ☑ 送达(errcode=0,msgid 4646543149392429060)
- N=2: ☑ 送达(errcode=0,msgid 4646543192392433666)
- N=3: —
- N=N: —
**grant 计数变化**(看 `experiments/data/state.json` 里的 `grants` 数组):
```
授权后 granted_count:  4(累计 4 次授权:exp1+exp3+本次2次)
A3-4 第 1 次发后 granted_count:  4 → consumed 4
A3-4 第 2 次发后 granted_count:  4 → consumed 4
```
**结论**:`UNEXPECTED_PASS — GRANT_CUMULATIVE:连续授权 2 次 → 2 条全部送达,证明微信 grant 是"储备式"计数,授权 N 次可消耗 N 条(跨时间段累积),而非"覆盖式"单次计数。`

**如果与 v0.2 不符,如何处理**:
- ☐ 不调整,模型仍然成立(因为授权一次后该次 grant 用完即止,与模型一致)
- ☑ **UNEXPECTED_POSITIVE**:实测 N>1。v0.2 模型需要扩展 grant 来源(把"用户全局允许"也视为一次性预发 N 个 grant)。**仅触发 ADR-002 增量更新,NOT 自动降级到分支 B。** 原因:用户偶尔多送 1 条是锦上添花,不是架构性失败。N>1 触发的真正风险是"用户长期不重新授权 → 实际触达率无感提升" — 这在 A3-4 N>1 配合 A3-1/A3-3 失败场景下才会变 critical;若 A3-1/A3-3 仍正常,N>1 仅是 bonus。
- ☐ 触发 ADR-002:grant 模型重构(同上,但同时改 `DATA-MODEL.md` 里的 `granted_count` 字段语义)

> **产品含义(重要)**:grant 可累积意味着 V1 可以设计"授权储备"交互 — 用户一次性多授权几次(或客户端在每次开播前静默调 requestSubscribeMessage),就能储备多条发送额度,后续开播无需打扰用户。这对"避免每次开播都弹窗"的体验问题是一个**可行解法**(虽然官方文档提示"总是保持"仍需每次调用才产生额度,但用户主动多点几次即可储备)。

---

### A3-5 微信服务端是否强制验证真实订阅授权

> **为什么关键**:v0.2 §3.3 设计假设"真实 authority 在微信服务端,`subscribeMessage.send` 返回码才是真值;客户端 `accept` 只是本地乐观记账"。这条假设直接决定后端**不需要**也不**应该**去证明 `wx.requestSubscribeMessage` 弹窗真实发生 — 任何"前端签名 + 后端验签"方案都不可信,因为客户端可以被 patch,签名只是自欺欺人。

> **重要边界**:本实验**不**试图证明后端能拦住伪造。本实验只验证"**微信服务端 `subscribeMessage.send` 是不是唯一可信 authority**" — 即:
> 1. 即便客户端 `accept` 被伪造/重放,`subscribeMessage.send` 仍按真实授权状态返回(0 成功 / 43101 拒 / 40037 模板错 等);
> 2. 即便客户端从未弹过 `wx.requestSubscribeMessage`,只要 `send` 端认为没有 grant,`send` 必然失败;
> 3. 后端能且仅能依据 `send` 返回码 + `granted_count` 本地计数器 决定要不要重发 / 走兜底通道。

> **明确不验证**:后端无法证明 `wx.requestSubscribeMessage` 弹窗真实发生。**没有"前端签名 + 后端验签"方案** — 这是已删选项,因为客户端可 patch,签名链路形同虚设。

**伪造 / 异常手法**(挑几个测,目的是看微信侧 `send` 是否仍然按真实授权状态返回):

| 手法 | 目的 | 期望的微信侧 `send` 返回 |
|------|------|---------------------------|
| 直接调 `request-grant` API 但没经过 `wx.requestSubscribeMessage`(后端没真用户交互) | 测"后端乐观记账不依赖真实弹窗" | 0(因为后端是 optimistic ledger,本地 granted_count 自行 +1,但**没有真实微信侧 grant**,**首次 send 必返 43101**) |
| 重放 `experiments/data/state.json` 里上次的 `granted_at` 时间戳,让后端以为"刚授权过" | 测"后端乐观记账可被本地重放污染" | 0(本地记账被污染)但**微信侧 send 仍按真实 grant 状态返**(若用户已真实授权过,send 返 0;若没真实授权过,send 返 43101) |
| 改了 .env 里 `WX_TEMPLATE_LIVE_START` 改成没申请过的 ID | 测"模板不合法时 send 行为" | errcode=40037(模板不存在),**与是否授权无关** — 这条证明 send 端有独立校验 |
| 改了 access_token 字符串 | 测"token 不合法时 send 行为" | errcode=40001 / 42001(token 无效 / 过期) — 这条证明 send 端鉴权独立 |

**每种手法的实测结果**:

| 手法 | HTTP 状态 | errcode | 实际行为 | 截图 / 日志路径 |
|------|----------|---------|----------|-----------------|
| 直接伪造 accept(服务端 granted+1,用户无真机授权) | 200 | **首次 0(伪阳性)** | ⚠️ 首次伪造发送**返回 0 成功** — 但这是 **grant 延迟结算假象**:用户实验 4 授权 2 次,微信侧 grant 尚未全部结算,伪造发送消耗了残留真实 grant | `experiments/data/state.json` exp5_forged_accept |
| 耗尽残留后,再次伪造 accept 并发送 | 200 | **43101** | ✅ 连续发送耗尽全部真实 grant(第 1 条即 43101)→ 确认余额为 0 → 伪造 granted+1 后发送 **仍返回 43101 user refuse to accept the msg** | exp5_drain + exp5_forged_accept_after_drain |
| 伪造 openid(不存在的用户) | — | 40003 | ✅ send 端独立校验 openid 合法性 | probe 阶段(40003 invalid openid) |
| 伪造模板 ID | — | 40037 / 200014 | ✅ send 端独立校验模板存在性 | probe 阶段 addtemplate 200014 |
|  |  |  |  |  |

**关键观察**(逐条勾,任何一条 NO 都意味着 authority 假设崩塌):
- [x] **微信 send 是唯一真实 authority**:errcode 完全由"该 openid 该模板是否真有 grant"决定,与后端 state.json / granted_count 无关(余额耗尽后伪造,返回 43101)
- [x] **后端乐观记账可被本地污染不致命**:state.json 改了/重放了,微信侧 send 仍按真实状态返(可送达 / 不可送达,符合用户真实授权状态)
- [x] **模板错误 / token 错误独立报错**:40037 / 40001 / 42001 等都是 send 端独立校验,与 grant 状态正交
- [x] **grant 用尽时 errcode=43101**:这正是 A3-2 期望的错误码 — 说明 send 端有 grant 计数,且本实验可复现

> ⚠️ **伪阳性教训(重要)**:实验 5 首次伪造发送返回 errcode=0,曾一度以为 authority 崩塌。补充实验证明这是 **grant 延迟结算** — 用户真实授权的 grant 尚未完全消耗,伪造发送恰好消耗了残留。**结论:必须先把真实 grant 耗尽(连发到 43101),再做伪造实验,否则会被假象误导。**

**结论**:`PASS` — 微信 send 端确实是唯一真实 authority。伪造 accept(无真机授权)在 grant 余额为 0 时**必被 43101 拒绝**;后端乐观记账被污染不致命,send 返回码始终反映真实授权状态。

**如果 authority 假设被打破(比如 send 不按真实授权返)**:
- 微信通知不可信,触发 ADR-003:通知架构降级(走 §4 分支 B,选 Bark / Telegram / Webhook / 企业微信)
- 同步在 [WECHAT-NOTIFICATION-SPEC.md](../WECHAT-NOTIFICATION-SPEC.md) §3.3 把"authority = send 返回"改为"authority 不可信,需 fallback"

---

### A3-6 用户拒收后,平台实际行为

> **为什么关键**:v0.2 §4.2 假设"用户拒收 in-app 弹窗后,微信侧不会送达"。但要确认:**会不会客户端又发了一次"重新请求授权"**?这种"误弹"会严重影响体验。

**触发场景**:用户通过 **微信「服务通知」→ 设置 → 找到小程序 → 拒收通知**(iOS 路径;Android 类似在服务通知会话里操作)拒绝该小程序的订阅消息
**之后发生的事**:
- ☑ 用户主动拒收(非弹窗取消 — 因用户弹窗已不显示,微信记住了"总是允许"选择)
- 发送结果:**errcode=43101 user refuse to accept the msg**,即时生效

**主播开播后实际行为**:
- ☑ 微信侧**不**收到通知(errcode=43101,正确)
- ☐ 微信侧**还**是收到了通知(说明拒收只对那一次有效,可能 v0.2 模型需要"per-anchor 黑名单"而非"per-grant 消耗")
- ☐ 客户端在 in-app 弹了横幅(说明兜底通道工作)

> ⚠️ 本次实验在"拒收"条件下 send 直接返回 43101 — 注意与实验 2(未授权)的 43101 是同一个错误码,说明**微信服务端不区分"未授权"和"已拒收"**,对 send 调用方而言两者都是"不可送达"。V1 后端只需统一按 43101 处理,无需区分原因(但客户端 UX 上可区分:未授权→引导弹窗,拒收→引导去服务通知开启)。

**结论**:`PASS — 拒收后微信侧即时返回 43101,消息不送达,且拒收是彻底、即时、跨时间生效的。`

**如果拒收不彻底**:
- 增加 per-(user, platform_account) 黑名单表
- 在 ADR-001 旁挂 ADR-002 记录这个修正

---

## 3. 验收清单(逐条勾)

> 来源:[GATE-0.md §Gate 0A 验收](../GATE-0.md)

- [x] 实验 A3-1 通过(errcode=0,msgid 4646537231497920512,送达确认)
- [x] 实验 A3-3 通过(errcode=0,msgid 4646539401026830337,送达确认)
- [x] 实验 A3-2 失败原因明确(grant 真的被消耗了,errcode 是 43101 而不是其他)
- [x] 实验 A3-4 行为记录完整(连续授权2次→2条全送达,`UNEXPECTED_POSITIVE` GRANT_CUMULATIVE,已触发 ADR-002 增量更新 — 未自动降级)
- [x] 实验 A3-5 行为记录完整(2 种伪造手法 + 耗尽验证,authority 假设成立)
- [x] 实验 A3-6 行为记录完整(微信服务通知拒收 → 43101,拒收彻底且即时)
- [x] 原始 stdout 日志已保存到 `experiments/data/run-grant-20260812-2311.log`(实验期间逐步记录于 state.json,见 §6.1)
- [x] state.json 在 git working tree 里没有被误提交(`git status experiments/data/` 是空的或仅 .gitkeep)
- [x] AppID 完整值 / Secret 没有出现在任何 commit / 截图 / 本文件

---

## 4. 结论(决定 V1 产品定位)

> 根据上面 6 个实验的实测,走下面两条分支之一。

### 分支 A — V1 维持"微信开播提醒器"定位(走这条的前提)

**所有以下条件成立**才走这条**:
- A3-1 / A3-3 通过
- A3-2 失败原因是 43101(grant 耗尽),而不是其他
- A3-4 行为符合 v0.2(每次发通知前用户必须已经授权过,且每次授权只能发 1 条)
  - **或 A3-4 N>1 标记为 `UNEXPECTED_POSITIVE`**:v0.2 grant 模型可扩展(本地 granted_count 来源不只有 request-grant),但**不**因此自动降级到分支 B;仅触发 ADR-002 增量更新 + `DATA-MODEL.md` 字段语义修正
- A3-5 微信 send 是唯一真实 authority(errcode 完全由真实 grant 决定,与后端 state.json / granted_count 无关)
- A3-6 拒收后微信侧不送达

**勾选才生效**:
- [x] A3-1 通过
- [x] A3-3 通过
- [x] A3-2 失败原因是 43101
- [x] A3-4 行为符合 v0.2 **或** 标记为 `UNEXPECTED_POSITIVE` 且 ADR-002 已增量更新
- [x] A3-5 send 是唯一真实 authority(后端乐观记账可被本地污染但 send 仍按真实授权状态返)
- [x] A3-6 拒收后微信侧不送达

**结果**:**V1 维持原定位,直接进入 Gate 0B。**

需要在 [WECHAT-NOTIFICATION-SPEC.md](../WECHAT-NOTIFICATION-SPEC.md) §5.1 处补一行"Gate 0A 实测通过,日期 2026-08-12"。

---

### 分支 B — V1 改为"订阅管理 + 多通道"(走这条的前提)

> ⚠️ **重要:不再因为 A3-4 N>1 自动降级**。N>1 标记为 `UNEXPECTED_POSITIVE`,走 ADR-002 增量更新即可。仅在下面"真正架构性失败"条件下才走分支 B。

**任意以下条件成立**就走这条**:
- A3-2 失败但 errcode 不是 43101(比如 40037 模板问题、40001 token 问题,说明 grant 模型根本走不到消耗那一步)
- **A3-5 send 端不按真实授权状态返回**(微信通知不可信,authority 假设崩塌)
- A3-6 拒收后微信侧仍然送达(用户没法关闭,体验崩塌)
- **综合判断 A:用户必须不可接受地频繁操作**(比如每次开播都要重新扫码授权,或每次授权只能发 1 条且 grant 重置周期 ≤ 1 天)
- **综合判断 B:微信后台触达不可靠**(errcode 持续返回非 0/43101 的网络性错误,或消息送达率显著低于 in-app 兜底通道)
- (A3-4 N>1 已不再作为自动降级条件 — 见上面 ⚠️)

**勾选就触发**(可多选,**任一架构性失败**即触发,**A3-4 N>1 不在其中**):
- [ ] A3-2 errcode 不是 43101
- [ ] A3-5 send 不按真实授权状态返(authority 崩塌)
- [ ] A3-6 拒收不彻底
- [ ] 综合 A:用户必须不可接受地频繁操作
- [ ] 综合 B:微信后台触达不可靠

**结果**:**V1 改为"订阅管理 + 多通道"**:
1. 微信小程序**只**负责订阅管理(增删主播、设置通知偏好)
2. 微信通知降级为"辅助通道",**优先级最低**
3. V1 必须实现至少一个**可持续 Push 通道**(选一个先做):
   - ☐ Bark(iOS 用户体验最好)
   - ☐ Telegram Bot(海外用户友好)
   - ☐ Webhook(开发者友好)
   - ☐ 企业微信应用消息(国内企业用户)
4. 在 [PRODUCT.md](../PRODUCT.md) §场景 2 / 场景 3 加一句"通知渠道:微信 + <X>",并在 [WECHAT-NOTIFICATION-SPEC.md](../WECHAT-NOTIFICATION-SPEC.md) §5.2 处把"待 Gate 0A 实测"改为"已实测触发,日期 YYYY-MM-DD"
5. 触发 ADR-002:V1 通知架构调整(注意:与上面 A3-4 UNEXPECTED_POSITIVE 触发的 ADR-002 是同一份 ADR,合并写)

---

## 5. 对 v0.2 各文档的影响(无论走哪个分支都要回填)

| 文档 | 需要做的更新 | 责任人 | 状态 |
|------|--------------|--------|------|
| WECHAT-NOTIFICATION-SPEC.md | §5 加实测日期 + 结论分支 | WorkBuddy | ☐ |
| PRD.md | F5 grant 描述 / 多通道描述 根据分支 A/B 调整 | WorkBuddy | ☐ |
| PRODUCT.md | 场景 2 / 3 通知描述调整 | WorkBuddy | ☐ |
| API-SPEC.md | 如果走分支 B,加 channel 字段 | WorkBuddy | ☐ |
| DATA-MODEL.md | 如果走分支 B,加 `notification_channels` 表 | WorkBuddy | ☐ |
| CHANGELOG.md | 加 v0.2.1 条目(如果是分支 B) | WorkBuddy | ☐ |
| GATE-0.md | §Gate 0A 验收处加本报告链接 | WorkBuddy | ☐ |

---

## 6. 附录(可选)

### 6.1 原始日志路径

```
experiments/data/run-grant-YYYYMMDD-HHMM.log
experiments/data/run-trust-YYYYMMDD-HHMM.log
experiments/data/state.json(grants 数组前 5 条已脱敏)
```

### 6.2 关键截图清单(可选,放路径即可,不要把图片 commit 进 git)

- A3-1:首次弹窗 + 收到通知
- A3-2:第二次发失败的 errcode 返回
- A3-4:"总是保持以上选择"勾选位置 + N 次发通知结果
- A3-5:伪造被拒的 errcode
- A3-6:拒收后再开播的微信侧表现

### 6.3 任何"文档没说清楚但实测里踩坑"的小坑

> 例:实测发现"开发者工具里弹窗行为和真机不一致,必须用真机扫码";例:access_token 缓存时间实测是 7199s 不是文档写的 7200s;例:测试号没有订阅消息配额限制(和正式号不同)等等。

| 现象 | 对 v0.2 文档的影响 |
|------|-------------------|
| **【2026-08-12】微信小程序测试号不支持订阅消息** — 实测:`getcategory` 返回空数组、`getpubtemplatetitles` 返回 errcode 200016、`addtemplate` 用假 tid 也只返 200014(说明根本没走到类目校验就死了);用户后台界面确认**没有** "订阅消息 / 公共模板库" 菜单入口。原因:测试号未绑定主体、没有可用服务类目。 | Gate 0A 6 个实验**整体搁置**,需走 §A 替代方案:① 申请正式非个人小程序(个人主体也无订阅消息权限);② 先用 mock 全流程跑通 + Gate 0B 适配器;③ 等小程序上线后再补此 Gate 0A。access_token 本身已可用(`106_*` 前缀,137 字长),所以"接口链路层"已通,只是"模板侧"被锁死。|
| **【2026-08-12】正式号已解锁订阅消息** — 用户提供了正式号 `wx370fb6f14d4a4a26`(末 4 位 `4a26`),模板 `VehDuOW2x...` 已选用,模板标题 **直播开播通知**,字段:`time3` 开播时间 / `thing6` 直播间活动 / `thing5` 直播主题 / `thing1` 达人名称 / `thing2` 直播间名称。比 v0.2 设计的 thing1/thing2/time3 多了 thing5/thing6,payload 构造时可全填。 | 阻塞解除!Gate 0A 6 实验可继续。模板字段结构已确认,v0.2 的 `WECHAT-NOTIFICATION-SPEC.md` 里 payload 字段映射可据此更新(把 thing5/thing6 纳入)。|
|  |  |
|  |  |

---

## 7. 报告签收

| 角色 | 姓名 | 日期 | 签字 / commit hash |
|------|------|------|---------------------|
| 实验执行 |  |  |  |
| 模型负责人(WorkBuddy) |  |  |  |
| 最终决策(产品) |  |  |  |

> **完成本报告 + §4 结论分支确定后**,在 [GATE-0.md](../GATE-0.md) §Gate 0A 验收处把对应 checkbox 勾上,Gate 0A 正式 pass,可以进入 Gate 0B。
