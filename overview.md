# v0.3.12 前端设计升级 — StageLetter (开场信)

## 调研产物

| 来源 | 提取原则 | 落地方式 |
|---|---|---|
| Dribbble | 每个平台保留识别色 + 卡片多层级阴影 + 8pt grid | 平台色 tokens + 软阴影 |
| GSAP | power2.out 缓动 + stagger via nth-child | `--ease-out-quart` + `.rise-in:nth-child` |
| ReactBits | 渐变文字 + 呼吸 halo + glow | `-webkit-background-clip` + `::before` halo |
| Lenis | scroll-linked 动效(原则上) | Mini Program 不支持 scroll hijacking,跳过;原则保留 |
| Vanta.js | 多层 mesh 渐变 + 大色块柔光 | 4 层 radial-gradient (`--mesh-bg`) |
| Animos.app | tap ripple + press feedback + 磁性按压 | `hover-class` + `::after` 涟漪动画 |

**核心理念**:Web 端的设计资源不能直接 import,但可以提取 *设计原则* 用纯 CSS 重写 — Mini Program 缺 JS 库支持,要靠 WXSS 精巧地补位。

---

## 落地清单

### 1. 全局设计系统 `app.wxss` 新增

| 系统 | 关键 class | 用途 |
|---|---|---|
| 背景层叠 | `--mesh-bg` | 4 个 radial-gradient 微斑 + 浅蓝基底,模拟 Vanta 氛围 |
| 缓动曲线 | `--ease-out-quart` | cubic-bezier(0.2,0.8,0.2,1),等价 GSAP power2.out |
| 平台色 | `.platform-bilibili/-douyin/-huya/-douyu` | W3C 识别的 4 平台品牌色 |
| 渐变文字 | `.gradient-text / -warm / -light` | `-webkit-background-clip: text` |
| Tap Ripple | `.tappable + .tappable-ripple + .tappable-light/-dark` | `::after` 圆形涟漪扩散 + 配色适配暗/亮底 |
| Live Halo | `.live-halo::before` | 主播头像外圈光环无限脉冲 |
| Live Dot | `.live-dot` | 头像右下红点 + box-shadow 呼吸圈 |
| 入场动画 | `.rise-in:nth-child(1..10)` | 卡片 stagger translateY+opacity,延迟 40-490ms |
| 按压反馈 | `.press / .press-card / .lift` | 3 档按压(scale / 缩放+位移 / 抬升) |
| 空状态插画 | `.empty-icon-wrap (+ .warm / .success)` | 渐变圆背景+box-shadow 替代单 emoji |

### 2. 5 页面应用

| 页面 | 应用点 |
|---|---|
| **home (首页直播)** | title 渐变、live-card 整行可点 + press + tap ripple + rise-in,avatar 加 halo 光环 + live-dot |
| **subscriptions (订阅)** | title 渐变、live-dot 覆盖 avatar-wrap、unsub-btn 红涟漪、空状态渐变插画 |
| **add (添加)** | 4 平台各自品牌色 chip(active 渐变)、模式 tab press、sub-btn 切换 ripple 配色(亮/暗)、结果数字渐变高亮 |
| **detail (详情)** | header-card rise-in 入场、按平台左边线 + 浅色平台背景渐变 |
| **profile (我的)** | grant-card 装饰光晕(2 个 radial 圆叠加)、大数字渐变填充(暗色配浅金)、通知进度条渐变、空状态 success 色 |

---

## 关键文件改动

- `miniapp/app.wxss` — 新增 ~250 行(平台色 tokens + 动效系统)
- `miniapp/pages/home/index.wxml + .wxss` — 标题/卡片/光环
- `miniapp/pages/subscriptions/index.wxml + .wxss` — 标题/状态点/红涟漪
- `miniapp/pages/add/index.wxml + .wxss` — 平台色 chips/渐变数字
- `miniapp/pages/detail/index.wxml + .wxss` — 入场/平台边线
- `miniapp/pages/profile/index.wxml + .wxss` — 装饰光晕/渐变数字

## 实现要点

1. **零 JS 改动**:所有效果都靠 WXSS 实现,不破坏原有 event handler、状态、API 调用
2. **hover-class 复用**:mini program 原生支持 hover-class 在 tap 时附加类,所以涟漪动画不需要 JS 触发
3. **nth-child stagger**:用 CSS 的 `:nth-child(n)` + `animation-delay` 实现 stagger,无需 GSAP
4. **GPU 提示**:关键动画元素加 `will-change: width, height, opacity` / `transform: translateZ(0)` 避免合成抖动
5. **未触动的 class**:全部旧 class (card / badge / empty / cancel / platform 等)保留,新 class 叠加,无回归

## 性能与可访问性

- 所有无限动画单独 GPU 合成层(home 页最多 8 个 halo+dot 动画同屏)
- 入场动画 480ms,涟漪 580ms,符合 Animos 推荐的 100-200ms 反向(用 ease-out-quart 给出"柔软落定")
- 暗背景涟漪用 `rgba(24,95,165,0.18)`,亮背景用 `rgba(255,255,255,0.45)`,对比清晰不刺眼
- 所有交互元素加 `-webkit-tap-highlight-color: transparent` 避免系统默认蓝底高亮

## 后续方向(可选迭代)

- ✅ 完成后:卡片可点、按钮可点、状态清晰
- ⏭️ 下一版可考虑:`onPageScroll` + IntersectionObserver 触发 viewport 渐显(Lenis 原则的退化替代)
- ⏭️ 主题色随时间切换(深色模式) — 需将 `--brand-*` 切换到 `@media (prefers-color-scheme)` 或手动切换
