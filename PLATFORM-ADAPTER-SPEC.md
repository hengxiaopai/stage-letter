# PLATFORM-ADAPTER-SPEC.md — 平台适配器规范

> **v0.2 变更**: §7 DEGRADED 新行为 / §8.1 QPS 标 provisional / §8.3 40037 处理修正 / 新增 §13 capacity.md 模板。详见 [CHANGELOG.md](./CHANGELOGOG.md)。

## 1. 两类适配器

### A 类:官方事件/API (事件驱动)

平台主动推送状态变化。

代表:**Twitch EventSub**
- `stream.online`:主播上线
- `stream.offline`:主播下线
- 这两个事件**不要求主播授权**(只要求订阅者有 EventSub 权限)

> 详见 [Twitch EventSub 文档](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/)

可能未来加入 A 类的:
- B 站 WebSocket 部分事件
- YouTube PubSubHubbub
- 抖音官方 webcast(仅在白名单内可用)

**特点**:
- 实时(秒级)
- 稳定
- 不需要轮询
- 不需要反爬

### B 类:轮询 / 社区适配器

通过 HTTP 拉取主播状态。

代表:
- 抖音(公开网页 + 社区接口)
- B 站(API)
- 虎牙(API)
- 斗鱼(API)
- 快手(公开网页)
- 小红书(公开网页)

**特点**:
- 准实时(分钟级)
- 可能被风控
- 需要重试、限流、降级

## 2. 为什么必须分两类

因为它们的成本、稳定性、运维方式完全不同:

| 维度 | A 类 | B 类 |
|------|------|------|
| 实现成本 | 低(订阅 webhook) | 高(解析接口) |
| 维护成本 | 低 | 高(接口经常变)|
| 检测频率 | 事件驱动 | 30s ~ 30min(分级)|
| 风控风险 | 几乎无 | 高 |
| 失败模式 | webhook 断开 | 接口限流 / 反爬 |

**架构上必须把这两类用不同 worker、不同队列处理**。

## 3. 统一接口

```python
# platform_adapters/base.py

from typing import Protocol
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class LiveSnapshot:
    """统一直播快照。"""
    platform: str
    platform_account_id: int
    is_live: bool
    title: str | None = None
    cover: str | None = None
    viewer_count: int | None = None
    started_at: datetime | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class ParseResult:
    """从 URL 解析出的主播信息。"""
    platform: str
    platform_user_id: str
    room_id: str | None
    canonical_url: str
    display_name: str | None = None
    avatar: str | None = None
    is_existing: bool = False


class PlatformAdapter(Protocol):
    """所有适配器必须实现这个接口。"""

    platform: str  # 'douyin' / 'bilibili' / ...
    version: str   # adapter 自身版本,如 '1.2.3'

    async def get_live_snapshot(
        self,
        platform_account: "PlatformAccount",
    ) -> LiveSnapshot:
        """获取某主播当前直播快照。失败抛 AdapterError。"""
        ...

    async def parse_url(self, url: str) -> ParseResult:
        """从 URL 解析 platform_user_id / room_id。"""
        ...

    async def health_check(self) -> bool:
        """适配器自身健康检查(不依赖具体主播)。"""
        ...


# 错误分类
class AdapterError(Exception):
    """基类。"""
    pass

class RetryableError(AdapterError):
    """可重试:网络超时、5xx、限流。"""
    pass

class FatalError(AdapterError):
    """不可重试:主播不存在(404)、账号被封。"""
    pass

class RateLimitError(AdapterError):
    """触发限流,需要更长退避。"""
    pass
```

## 4. 适配器实现目录

```
platform_adapters/
├── __init__.py
├── base.py
├── registry.py          # platform -> adapter 映射
├── douyin/
│   ├── __init__.py
│   ├── adapter.py
│   ├── parser.py
│   ├── sign.py
│   └── tests/
├── bilibili/
├── huya/
├── douyu/
└── twitch/              # A 类:基于 EventSub
    ├── adapter.py
    ├── eventsub.py
    └── tests/
```

## 5. A 类适配器特殊点 (Twitch)

```python
class TwitchAdapter:
    platform = "twitch"
    version = "1.0.0"

    async def setup_webhook(self, platform_account):
        """向 Twitch 注册 EventSub subscription。"""
        ...

    async def handle_event(self, event_type: str, payload: dict):
        """webhook 收到事件时调用。"""
        # 写 LiveEvent(直接 CONFIRMED_ONLINE,置信度高)
        ...
```

**Twitch 不用轮询**,所以:
- `get_live_snapshot` 只在首次订阅时调用一次
- 后续完全靠 webhook
- webhook 接收 URL 暴露为独立 endpoint(`/api/v1/internal/twitch/webhook`)

## 6. B 类适配器流程

```
worker-{platform} 启动
   ↓
从 Redis queue 拿任务 { platform_account_id, polling_tier }
   ↓
调用 adapter.get_live_snapshot(pa)
   ↓
成功 → 返回 LiveSnapshot
失败 (RetryableError) → 重试 3 次
失败 (FatalError) → 标记该 platform_account 为 need_manual_check
失败 (RateLimitError) → 长退避
   ↓
返回结果给状态机
```

## 7. 适配器健康度 (v0.2 修改 DEGRADED 行为)

每个平台在 `platform_health` 表维护:

| 字段 | 含义 | 更新时机 |
|------|------|----------|
| `state` | HEALTHY / DEGRADED / DISABLED | 每次探测后 |
| `success_rate_24h` | 24h 成功率 | 滚动窗口 |
| `avg_latency_ms_24h` | 24h 平均延迟 | 滚动窗口 |
| `consecutive_failures` | 连续失败次数 | 每次失败 +1,成功归零 |
| `sustained_qps` | 实测持续 QPS(Gate 0C 填入) | 容量测量后 |
| `max_anchors` | 该平台可承载主播数(Gate 0C 填入) | 容量测量后 |

**降级规则** (V1 简化):

```python
def update_health(platform: str, success: bool, latency_ms: int):
    h = platform_health[platform]
    if success:
        h.consecutive_failures = 0
        h.success_count_24h += 1
        h.last_success_at = now()
    else:
        h.consecutive_failures += 1
        h.error_count_24h += 1
        h.last_failure_at = now()

    h.success_rate_24h = h.success_count_24h / (h.success_count_24h + h.error_count_24h)

    if h.consecutive_failures >= 5 or h.success_rate_24h < 0.7:
        h.state = 'DEGRADED'
    elif h.state == 'DEGRADED' and h.consecutive_failures == 0 and h.success_rate_24h > 0.9:
        h.state = 'HEALTHY'  # 自动恢复
```

### 7.1 DEGRADED 行为 (v0.2 修正)

**v0.1 错误**:DEGRADED 后一刀切静默,不通知。  
**v0.2 修正**:DEGRADED 后**仍通知**,但:

| 行为 | v0.1 | v0.2 |
|------|------|------|
| 检测频率 | 5min → 15min | 5min → 15min(不变) |
| 二次确认 | 30s 一次 | **60s 一次,共 3 次**(更严格) |
| LiveEvent.confidence | normal | **low** |
| 通知 | 一刀切不通知 | **仍通知,但标记低 confidence**(用户看到后知道可信度低) |
| Admin 告警 | 无 | **进入 DEGRADED 时报警** |

> 仍通知的原因:DEGRADED 是临时状态,如果主播正在直播,用户错过通知更糟糕。  
> 标记低 confidence:用户可以自行判断("平台不稳定,这次可能误报")。

### 7.2 DISABLED 行为

- 完全不调度
- Admin 手动恢复

## 8. 限流与重试

### 8.1 单平台限流 (v0.2 标 provisional)

> **v0.2 重要**:以下限流数字是**默认起点**,必须由 Gate 0C 实测后调整。  
> 不允许在 Gate 0C 完成前承诺这些数字。

| 平台 | 默认 QPS | 来源 |
|------|---------|------|
| 抖音 | 1 req/s | 默认起点,Gate 0C 验证 |
| B 站 | 2 req/s | 默认起点,Gate 0C 验证 |
| 虎牙 | 2 req/s | 默认起点,Gate 0C 验证 |
| 斗鱼 | 2 req/s | 默认起点,Gate 0C 验证 |
| Twitch | 5 req/s | 默认起点(几乎不调)|

```python
from aiolimiter import AsyncLimiter

class DouyinAdapter:
    _limiter = AsyncLimiter(1, 1)  # 1 req / 1s

    async def get_live_snapshot(self, ...):
        async with self._limiter:
            ...
```

### 8.2 重试

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class DouyinAdapter:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(RetryableError),
    )
    async def get_live_snapshot(self, ...):
        ...
```

### 8.3 错误分类与处理 (v0.2 修正)

| 异常 | 含义 | 重试 | 健康度 |
|------|------|------|--------|
| `RetryableError` | 网络超时、5xx | 是 (3 次) | 累计失败 |
| `RateLimitError` | 429 | 是 (更长退避 30s+) | 累计失败 |
| `FatalError` | 404 / 账号被封 | 否 | 单次失败 |
| `WeChatTemplateDisabledError` | 微信模板错误 | **不在 adapter 重试**,直接 disable 模板 | 不影响 adapter 健康度 |

**v0.2 关键修正**:
- v0.1 把微信 40037 当作"disable 平台"——错的!
- 微信模板错误是**微信通道**的问题,与**平台 adapter** 完全独立
- 处理:`adapter.send_wechat()` 抛 `WeChatTemplateDisabledError` → **调用方** `disable_wechat_template(template_id)`,**不修改** platform_health

## 9. 检测调度 (v0.2 分级轮询)

### 9.1 分级 (Polling Tier)

| Tier | 检测频率 | 适用 |
|------|---------|------|
| **HOT** | 30s | 订阅数 > N(如 100)的主播 / 刚开播 5min 内 |
| **WARM** | 5min | 默认(订阅数 1-99) |
| **COLD** | 30min | 长期 OFFLINE(连续 7 天未开播) |

Tier 由 worker 动态调整:
- 主播开播 → 临时 HOT(开播后 1h 内)
- OFFLINE 7 天 → COLD
- 订阅数突增 → 升级 tier

### 9.2 调度算法

```sql
-- 按 tier 分桶选 due 的 platform_accounts
SELECT * FROM platform_accounts
WHERE platform = $1
  AND is_disabled = false
  AND polling_tier = $2
  AND last_checked_at < now() - interval $3
ORDER BY last_checked_at NULLS FIRST
LIMIT 100;
```

### 9.3 频率(汇总)

| 状态 | 频率 |
|------|------|
| ONLINE(临时 HOT)| 30s |
| SUSPECT_ONLINE / SUSPECT_OFFLINE | 30s(加速确认)|
| OFFLINE(订阅数 > 100)| WARM 5min |
| OFFLINE(订阅数 1-99)| WARM 5min |
| OFFLINE > 7 天 | COLD 30min |
| DEGRADED 平台 | WARM 15min |
| DISABLED 平台 | 跳过 |

### 9.4 容量计算 (v0.2 新增)

每个平台可承载主播数(估算公式):

```
max_anchors = sustained_qps × polling_interval_seconds
```

例如:
- Douyin `sustained_qps=1`,`polling_interval=300s` → **max_anchors = 300**
- B 站 `sustained_qps=10`(若有 batch),`polling_interval=300s` → **max_anchors = 3000**

**V1 总主播上限 = Σ 各平台 max_anchors**(必须 Gate 0C 实测后再确定)。  
**v0.1 的"18,000 主播 / 5min"假设在没有实测前不成立。**

## 10. 适配器版本管理

每个 adapter 有 `version` 字段。

**原因**:平台接口经常变(特别是抖音),adapter 必须能:
- 独立升级
- 灰度回滚
- 标注"我现在用哪个版本"

`platform_accounts.adapter_version` 记录每个主播当前用的版本(V1 全平台统一版本,字段先留好;V2 支持 per-anchor 版本)。

## 11. 适配器测试

每个适配器必须包含:

### 11.1 单元测试

- mock HTTP 响应
- 覆盖:成功、404、429、5xx、超时
- `parse_url` 各种 URL 形式

### 11.2 集成测试

- 真实 1-2 个主播,跑 24h
- 验证:状态变化能被正确检测

### 11.3 健康检查脚本

```bash
python -m platform_adapters.douyin.health_check
```

不依赖具体主播,仅检查:
- 平台域名可访问
- 关键 endpoint 不返回错误
- TLS 证书有效

## 12. 反爬策略(V1 简化)

- 自有 IP 池(V1 用云厂商 NAT,V2 引入代理池)
- 真实 UA / Referer
- 随机间隔(±20%)
- 失败后冷却(指数退避)
- **不存用户 Cookie**

## 13. capacity.md 模板 (v0.2 新增)

> **每个平台适配器**必须输出 `platform_adapters/{platform}/capacity.md`。  
> 模板如下,由 Gate 0C 填写。

```markdown
# {Platform} Adapter Capacity Report

**测试时间**: YYYY-MM-DD HH:MM ~ YYYY-MM-DD HH:MM
**测试版本**: adapter v{version}

## 1. 单请求性能

- 平均 latency: ___ ms
- p50 / p95 / p99 latency: ___ / ___ / ___ ms
- 失败率: ___ %

## 2. 持续吞吐

- 持续 QPS(无 429): ___
- 触发 403 的阈值: ___ QPS 或 ___ req/min
- 触发 429 的阈值: ___ QPS 或 ___ req/min
- 触发后恢复时间: ___

## 3. Batch 能力

- 有无 batch endpoint? ___
- 单请求最多查多少主播? ___
- batch 后的 per-anchor latency: ___

## 4. 风控依赖

| 项 | 是否必需 |
|----|---------|
| Cookie | 是 / 否 |
| 签名(sign / x-s / ...)| 是 / 否 |
| 固定 UA | 是 / 否 |
| 真实 Referer | 是 / 否 |
| 真实 IP 段 | 是 / 否 |
| 风控账号 | 是 / 否 |

## 5. 稳定性(72h 持续)

- 总请求数: ___
- 成功率: ___ %
- 平均 latency: ___ ms
- 错误类型分布:
  - 4xx: ___ %
  - 5xx: ___ %
  - 网络超时: ___ %
  - parse 失败: ___ %

## 6. 容量上限(估)

- sustained_qps 实测: ___
- 建议 polling interval: ___ min
- **max_anchors 估算: ___(sustained_qps × interval)**

## 7. 代理 / 多 IP 影响

- 多 IP 后成功率变化: ___
- 单 IP 被封后恢复时间: ___

## 8. 结论

- [ ] 可承载生产流量
- [ ] 需要降主播数(实际 < 期望)
- [ ] 需要 batch endpoint(否则 QPS 不够)
- [ ] 需要付费方案
- [ ] 暂不适合 V1
```

> 没有 `capacity.md` 的 adapter 不允许进入 Gate 1。

## 14. 未来扩展

- 新增平台:实现 `PlatformAdapter` 接口 + 注册到 `registry`
- 适配器独立部署:把单个 adapter 拆成独立镜像
- 适配器热更新:通过版本号灰度切换
- 代理池(V2):用 proxy pool 解决单 IP 风控