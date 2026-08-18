# WECHAT-NOTIFICATION-SPEC.md — 微信通知机制

> **v0.2 重大重构**: 不再使用"通知额度 (Notification Credits)"模型。  
> 详见 [CHANGELOG.md §v0.2](./CHANGELOG.md) 与 ADR-001(本文 §10)。

## 1. 微信订阅消息的真实机制

### 1.1 一次性订阅消息 (one-time subscription)

调用 `wx.requestSubscribeMessage({ tmplIds: [...] })`:
- 用户在弹窗中**主动**点击接受(可全选 / 部分选 / 拒绝)
- 用户**每次主动授权** → 对应 template_id 获得**一次**发送机会
- **✅ Gate 0A 实测修正(2026-08-12):grant 可累积储备(GRANT_CUMULATIVE)** — 连续授权 N 次 = 储备 N 条额度,可跨时间段消耗。每次 accept 都是"向余额 +1",不是"覆盖上一次"。
- **⚠️ v0.2 旧描述"这次机会独立计次,与之前/之后的授权无关"已修正** — 实测证明授权会**累积**(连续授权 2 次 → 2 条消息全部送达,见 [reports/wechat_grant.md §2 A3-4](../reports/wechat_grant.md))。修正依据 ADR-002。

> 详见 [小程序订阅消息文档](https://wdk-docs.github.io/wxadev-docs/framework/open-ability/message/subscribe-message.html)

### 1.2 长期订阅消息 (long-term subscription)

仅对政务、医疗、交通、金融、教育等**线下公共服务**开放。  
**我们不在该类目,不能依赖长期订阅。**

### 1.3 调用返回

`wx.requestSubscribeMessage` 返回:

```json
{
  "TEMPLATE_ID_1": "accept",
  "TEMPLATE_ID_2": "reject",
  "TEMPLATE_ID_3": "ban"
}
```

### 1.4 三个关键事实(写给未来的自己)

1. **没有"一次性 ticket"交给服务端**。微信只回调给客户端。
2. **服务端无法独立查询用户的订阅余额**。没有"查询授权状态"的 API。
3. **没有"季初重置""系统发放"的概念**。所有 grant 必须由用户主动触发。

> **✅ Gate 0A 实测补充事实(2026-08-12,正式号)**:
> 4. **grant 可累积储备**:连续授权 N 次 = 储备 N 条额度,跨时间段消耗(实验 A3-4 变体:授权 2 次 → 2 条全送达)。
> 5. **微信弹窗"总是保持以上选择"UI 因版本而异**:iPhone 实测弹窗无此选项;且用户多次授权后微信记住选择,**真机不再弹窗**(免打扰,利好体验)。
> 6. **send 端是唯一真实 authority**:伪造 accept(客户端跳过程序直接声称授权)在 grant 余额为 0 时**必返 43101**;后端乐观记账被污染不致命。

### 1.5 我们**不能**做的(但 v0.1 写过)

| v0.1 假设 | 真实情况 |
|-----------|----------|
| 初始 8 次 | 没有"系统发放"机制,只能由用户主动触发 |
| 季度重置 8 次 | 同上,微信侧无此能力 |
| refresh +8 | 每次 accept 只 +1,且仅当用户真的点了 accept |
| 服务端校验 ticket | 没有 ticket,微信只回调给客户端 |
| 付费买 8 次微信提醒 | 卖的是 DB 数字,不增加真实下发权限 |

## 2. 新模型: WeChat Subscription Grants

### 2.1 核心思路

```
用户进入主播详情页 / 列表页
   ↓
点击"开启开播提醒"按钮
   ↓
小程序调 wx.requestSubscribeMessage({ tmplIds: ['LIVE_START_TPL'] })
   ↓
弹出授权弹窗
   ↓
用户点 accept
   ↓
客户端收到 accept → 调 POST /api/v1/notifications/request-grant
   ↓
服务端: granted_count += 1
   ↓
(可选)用户再次点"开启提醒" → 再次授权 → granted_count += 1
   ↓  ← ✅ Gate 0A 实测:授权可累积储备(GRANT_CUMULATIVE)
后续主播开播
   ↓
available = granted - consumed > 0?
   ↙             ↘
 YES             NO
  ↓               ↓
尝试 wechat  send  站内消息
   ↓
成功 → consumed +1
4xx → consumed +1(grant 失效)
5xx / 网络 → 重试,grant 保留
```

> **✅ Gate 0A 实测新增设计建议(v0.2.2)**:因为 grant 可累积,**V1 应设计"授权储备"交互**:
> - 用户关注主播时,引导一次授权 **3-5 次**(如弹窗文案"授权后可推送 5 条开播提醒")
> - 之后 3-5 次开播免打扰推送,额度用尽前再次引导授权
> - 这比"每次开播都弹窗"体验好得多,也规避了"总是保持"选项不可用的问题
> - 注意:授权储备受微信频控影响(短时间多次调用可能被压制),单次引导 3-5 次为安全上限

### 2.2 数据落地

详见 [DATA-MODEL.md §7](./DATA-MODEL.md):

```sql
CREATE TABLE wechat_subscription_grants (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    template_id     VARCHAR(64) NOT NULL,
    granted_count   INTEGER NOT NULL DEFAULT 0,
    consumed_count  INTEGER NOT NULL DEFAULT 0,
    last_granted_at TIMESTAMPTZ,
    last_send_at    TIMESTAMPTZ,
    last_send_error VARCHAR(255),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id, template_id)
);
```

**`available = granted - consumed`**(应用层计算,不存)。

### 2.3 业务规则(逐条对照)

| 触发 | granted | consumed | 说明 |
|------|---------|----------|------|
| 用户首次订阅 | 0 | 0 | 初始值,**不是 8** |
| 用户点 accept(客户端回调) | +1 | - | 乐观记账;**✅ 实测可累积储备(GRANT_CUMULATIVE),连续 accept 连续 +1** |
| wechat send 返回 0(成功) | - | +1 | grant 真实生效 |
| wechat send 返回 43101(用户拒收) | - | +1 | grant 失效 |
| wechat send 返回 40037(模板错误) | - | - | **报警 + disable 模板 ID**,grant 保留(下次修好还能用) |
| wechat send 返回 45009(限流) | - | - | 退避重试,grant 保留 |
| wechat send 返回 5xx | - | - | 退避重试,grant 保留 |
| wechat send 网络异常 | - | - | 退避重试,grant 保留 |

### 2.4 乐观账本与 Reconciliation

**乐观记账的风险**:
- 用户点 accept 但客户端网络断了,服务端没收到 → 我们漏记
- 客户端伪造 accept → 我们多记
- 用户点了 accept 但被微信侧 ban → grant 实际失效

**Reconciliation 策略**:
- 每次 send 后用微信实际返回状态更新 consumed
- 微信 API 没有"查询用户授权状态"接口,**长期必须接受少量不一致**
- **V1 接受 ±10% 不一致**,不主动 reconciliation
- V2+:用 WebHook / 主动探测(订阅过期检测)

### 2.5 v0.1 vs v0.2 模型对比

```
v0.1: 通知额度(虚构)
  初始 8 / 季度重置 / refresh +8 / 季度不可兑现

v0.2: 真实 Grants(乐观记账)
  初始 0 / 用户主动触发 / 每次 accept +1 / 真实 send 才消耗
```

## 3. 触达策略

```python
async def deliver(user_id: int, anchor_id: int, live_session_id: int):
    sub = await get_subscription(user_id, anchor_id)
    if sub is None or not sub.notify_enabled:
        return  # 用户关闭通知或取消订阅

    template_id = settings.WX_TEMPLATE_LIVE_START
    grants = await get_grants(user_id, template_id)
    available = grants.granted_count - grants.consumed_count

    if available > 0:
        try:
            await send_wechat_subscribe(user_id, template_id, live_session_id)
            await grants.update(
                consumed_count=grants.consumed_count + 1,
                last_send_at=now()
            )
        except WeChatUserOptedOutError:
            # 微信侧用户已停用,grant 失效
            await grants.update(
                consumed_count=grants.consumed_count + 1,
                last_send_error='USER_OPTED_OUT'
            )
        except WeChatRateLimitError:
            await schedule_retry()  # grant 保留
        except WeChatServerError:
            await schedule_retry()  # grant 保留
        except WeChatTemplateDisabledError:
            await disable_template(template_id)  # 不影响平台 adapter
            await schedule_retry_or_fallback()
    else:
        # 无 grant → 站内消息兜底
        await send_in_app(user_id, live_session_id, reason='no_grant')
```

## 4. UX 影响

### 4.1 不能假设"用户永远会授权"

- 用户每次想继续收通知,都得主动触发 `wx.requestSubscribeMessage`
- 微信弹窗体验不能太频繁(同 user 5min 内最多 1 次)
- 弹窗文案要明确"你将收到 X 主播的开播提醒"

### 4.2 必须明示 grant 状态

小程序显示:

```
你的开播提醒授权: 5 次(已开启)
[开启更多提醒]   ← 触发 wx.requestSubscribeMessage
```

不要写"剩余 X 次",因为 grant 是**用户行为产物**,不是配额。

### 4.3 没有 grant 时

主播开播 → 自动转站内消息。  
UI 提示:"X 主播开播了(微信提醒已用完,已转为站内消息)"。

### 4.4 与订阅绑定的 UX

把 grant 请求与订阅创建合并:

```
用户添加订阅 → 弹窗"是否同时开启开播提醒?"
   ↓
用户同意 → 同时记录 subscription + grant
   ↓
完成
```

减少用户操作步骤。

## 5. 产品定位影响(由 Gate 0A 实测决定)

> ✅ **Gate 0A 实测通过(2026-08-12)** — 结论见 §5.3

### 5.1 如果 Gate 0A 验证:"用户授权一次能用很久"

→ V1 维持"微信开播提醒器"定位不变。

### 5.2 如果 Gate 0A 验证:"用户必须频繁重新授权才收得到通知"

→ 产品定位调整为:

> **微信小程序负责订阅管理 + 微信通知是有限渠道 + 增加可持续 Push 渠道(Bark / Telegram / Webhook)**

架构上已经支持(`NotificationChannel` 接口统一),只是调整 channel 优先级。

**这个决定不在 v0.2 写死,等 Gate 0A 实测。**

### 5.3 ✅ Gate 0A 实测结论(2026-08-12,正式号 wx370fb6f14d4a4a26)

**V1 维持"微信开播提醒器"定位,进入 Gate 0B。**

实测要点:
1. **grant 核心模型成立**:一次授权 = 一条消息,耗尽后 send 返回 43101;重新授权后可再发(A3-1/2/3 全 PASS)
2. **GRANT_CUMULATIVE(新发现,UNEXPECTED_POSITIVE)**:连续授权 N 次 = 储备 N 条额度,可跨时间段消耗。V1 可设计"授权储备"交互(用户关注主播时一次授权多条,后续开播免打扰发送)
3. **send 端是唯一真实 authority**:伪造 accept(无真机授权)在余额为 0 时必返 43101;后端乐观记账被污染不致命(A3-5 PASS)
4. **拒收彻底且即时**:微信「服务通知」拒收后,send 立即返回 43101(A3-6 PASS)
5. 微信弹窗"总是保持以上选择"选项 UI 因版本而异(用户 iPhone 未显示);真机多次授权后微信会记住选择不再弹窗(免打扰,利好体验)

> 完整记录:[reports/wechat_grant.md](../reports/wechat_grant.md)

## 6. 模板与频率

### 6.1 模板申请

至少 1 个模板(开播提醒):

```
thing1.DATA    主播名(20 字内)
thing2.DATA    平台(20 字内)
time3.DATA     开播时间(yyyy-MM-dd HH:mm)
```

### 6.2 跳转

```json
{
  "page": "pages/anchor/detail?id={anchor_id}&session_id={session_id}",
  "miniprogram_state": "formal"
}
```

### 6.3 频率限制

| 维度 | 限制 |
|------|------|
| 单 LiveSession | 每 user 最多 1 条(由 DB UNIQUE 兜底) |
| 单 user 1h | 最多 5 条 |
| 单 user 1d | 最多 20 条 |
| grant refresh 同 user | 5min 内最多 1 次 |

## 7. 失败处理

| 微信错误 | 含义 | grant 处理 | 后续动作 |
|---------|------|-----------|---------|
| `0` | 成功 | consumed +1 | - |
| `40037` | 模板 ID 错误 | 不变 | **报警 + disable 该 template_id**(不是平台 adapter!) |
| `43101` | 用户拒收 | consumed +1(grant 失效) | 用户再次 accept 才能继续 |
| `43102` | 用户未订阅该消息 | consumed +1(grant 失效) | 同上 |
| `45009` | 调用太频繁 | grant 保留 | 退避重试 |
| `47003` | 参数错误 | 不变 | 报警,检查代码 |
| `5xx` | 服务端错误 | grant 保留 | 退避重试 3 次 |
| 网络异常 | - | grant 保留 | 退避重试 3 次 |

**关键修正(v0.2)**: v0.1 把 40037 当作"disable 平台",这是错的。  
**平台 adapter 与微信模板完全独立,不应该联动**。

## 8. 备选渠道 (V2+)

| Channel | 优先级 | 说明 |
|---------|--------|------|
| WeChat 一次性订阅 | 1 | 用户主动授权,有就用 |
| In-App 站内消息 | 2 | 兜底,永远可用 |
| Bark | 3 | iOS 用户自部署推送 |
| Webhook | 4 | 第三方集成 |
| Email | 5 | 海外用户 |
| Telegram | 6 | 海外 |

**架构预留**: `NotificationChannel` 接口统一,V2 扩展即可。

## 9. 监控指标

| 指标 | 含义 |
|------|------|
| `wx_grant_request_total` | grant 请求数(按 accept / reject 分) |
| `wx_send_total` | 实际发送数(按成功 / 失败 / 4xx / 5xx 分) |
| `wx_send_latency` | 微信 API 延迟 |
| `available_grant_distribution` | 用户可用 grant 分布 |
| `fallback_to_inapp_rate` | fallback 到站内比例 |
| `grant_waste_rate` | grant 被 4xx 浪费的比例 |
| `user_grant_refresh_rate` | 用户主动 refresh grant 的频率 |

## 10. ADR-001: 微信订阅模型决策

### 状态

Accepted (2026-08-01)

### 背景

v0.1 文档假设微信提供"通知额度"能力,可由服务端初始化、季度重置、refresh +8。  
实际微信仅提供"一次性订阅消息":每次用户主动授权获得一次发送机会。

### 决策

采用"乐观 grant 账本"模型:

- `wechat_subscription_grants` 表真实记录用户行为产生的 grant
- 应用层计算 `available = granted - consumed`
- 信任乐观账本 + 微信 send 返回状态做 reconciliation
- 接受 ±10% 不一致

### 后果

- 必须明示用户 grant 状态(不是"剩余配额")
- 不能承诺"无限 Push"
- Gate 0A 必须真机验证 grant 持久性,可能改变产品定位
- V1 主播上限需 Gate 0C 实测后确定

### 替代方案(已否决)

| 方案 | 否决原因 |
|------|---------|
| 伪造额度(v0.1) | 不诚实,用户期望与现实不符 |
| 强制用户每次都授权 | 体验极差,放弃 |
| 完全放弃微信通知,只用 Bark/Telegram | 流失小程序用户,产品定位偏离 |

---

## 11. ADR-002: Grant 累积储备 + 授权储备交互

### 状态

Accepted (2026-08-12,由 Gate 0A 实测触发增量更新)

### 背景

Gate 0A 实验 A3-4 变体实测(正式号 `wx370fb6f14d4a4a26`,2026-08-12 23:16):
- 用户**连续授权 2 次**后,服务端**连发 2 条订阅消息全部送达**(errcode=0)
- 说明微信 grant 是**储备式计数**:授权 N 次 = 储备 N 条额度,可跨时间段消耗
- v0.2 原假设"每次授权独立计次、与前后无关"**部分错误** → 增量修正

### 决策

1. **granted_count 语义修正**:每次用户 accept 都是向余额 +1,**可累积**(不覆盖)
2. **V1 新增"授权储备"交互**:用户关注主播时,引导一次授权 3-5 次(`wx.requestSubscribeMessage` 可一次传多个 tmplIds,或重复调用),储备多条额度,后续开播免打扰推送
3. **频控注意**:微信对 `wx.requestSubscribeMessage` 有频控,单次引导 3-5 次为安全上限;真机多次授权后微信可能记住选择不再弹窗(静默 accept),此时引导应显示"已生效"而非重复弹窗
4. **authority 不变**:send 端仍是唯一真实 authority(实验 A3-5);授权储备只影响本地 granted_count 记账,不影响微信侧校验

### 后果

- `available = granted - consumed` 公式**不变**,但 granted 现在可 >1 且跨时间累积
- 触达策略 `deliver()` 无需改动(available>0 即尝试 send)
- UX 文案从"开启提醒"可演进为"开启提醒(可推送 N 条)"
- 授权储备存在少量"微信侧 grant 与本地记账不一致"风险(用户真实授权可能因频控/过滤少于本地记账),由现有 reconciliation(每次 send 后按返回码更新 consumed)自动收敛

### 与 ADR-001 的关系

ADR-001 确立"乐观 grant 账本"框架(不变);ADR-002 是框架内的一次字段语义修正 + 产品交互增强,**不改变 V1 定位**(不降级多通道)。