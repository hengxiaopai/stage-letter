# -*- coding: utf-8 -*-
"""生成 StageLetter UI-1 组件体系(第一批: 标题/状态/行组件)"""
import os
import json

ROOT = os.path.dirname(os.path.abspath(__file__))
COMP = os.path.join(ROOT, "..", "miniapp", "components")


def write_comp(name, wxml, wxss, js, using=None):
    d = os.path.join(COMP, name)
    os.makedirs(d, exist_ok=True)
    cfg = {"component": True, "styleIsolation": "apply-shared"}
    if using:
        cfg["usingComponents"] = using
    with open(os.path.join(d, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with open(os.path.join(d, name + ".js"), "w", encoding="utf-8") as f:
        f.write(js)
    with open(os.path.join(d, name + ".wxml"), "w", encoding="utf-8") as f:
        f.write(wxml)
    with open(os.path.join(d, name + ".wxss"), "w", encoding="utf-8") as f:
        f.write(wxss)
    print("OK", name)


# 1. page-title
write_comp(
    "page-title",
    """<view class="pt-wrap">
  <view class="{{size === 'display' ? 't-display' : 't-title'}}">{{title}}</view>
  <view class="pt-meta" wx:if="{{meta}}">{{meta}}</view>
</view>
""",
    """.pt-wrap { display: flex; flex-direction: column; gap: 6px; padding: 24px 0 8px; }
.pt-meta { font-size: 13px; color: var(--text-secondary); }
""",
    """Component({
  properties: {
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
    size: { type: String, value: 'title' },
  },
})
""",
)

# 2. section-header
write_comp(
    "section-header",
    """<view class="sh-wrap">
  <view class="t-section">{{title}}</view>
  <view class="sh-more" wx:if="{{more}}" bindtap="onMore">{{more}}</view>
</view>
""",
    """.sh-wrap { display: flex; justify-content: space-between; align-items: baseline; padding: 20px 0 12px; }
.sh-more { font-size: 13px; color: var(--text-secondary); }
""",
    """Component({
  properties: {
    title: { type: String, value: '' },
    more: { type: String, value: '' },
  },
  methods: {
    onMore() { this.triggerEvent('more') },
  },
})
""",
)

# 3. anchor-avatar
write_comp(
    "anchor-avatar",
    """<view class="av-wrap" style="width:{{px}};height:{{px}};">
  <image wx:if="{{src}}" class="av-img" src="{{src}}" mode="aspectFill"/>
  <view wx:else class="av-ph">{{initial}}</view>
</view>
""",
    """.av-wrap { border-radius: 50%; background: var(--brand-soft); overflow: hidden; flex-shrink: 0; }
.av-img { width: 100%; height: 100%; }
.av-ph { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: var(--brand); font-weight: 600; }
""",
    """Component({
  properties: {
    src: { type: String, value: '' },
    name: { type: String, value: '' },
    size: { type: String, value: 'md' },
  },
  data: { initial: '?', px: '44px' },
  observers: {
    name(n) { if (n) this.setData({ initial: n[0] }) },
    size(s) {
      const map = { sm: '36px', md: '44px', lg: '56px' }
      this.setData({ px: map[s] || '44px' })
    },
  },
})
""",
)

# 4. live-badge
write_comp(
    "live-badge",
    """<view class="lb lb-live" wx:if="{{live}}"><view class="lb-dot"></view>LIVE</view>
<view class="lb lb-live" wx:elif="{{state === 'live'}}"><view class="lb-dot"></view>直播中</view>
<view class="lb lb-off" wx:elif="{{state === 'off'}}"><view class="lb-dot"></view>未开播</view>
<view class="lb lb-done" wx:elif="{{state === 'done'}}"><view class="lb-dot"></view>已结束</view>
""",
    """.lb { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; border-radius: 999px; padding: 3px 10px; }
.lb-dot { width: 6px; height: 6px; border-radius: 50%; }
.lb-live { background: var(--live); color: #fff; }
.lb-live .lb-dot { background: #fff; animation: lb-blink 1.4s ease-in-out infinite; }
.lb-off { background: var(--surface-2); color: var(--offline); }
.lb-off .lb-dot { background: var(--offline); }
.lb-done { background: var(--surface-2); color: var(--text-tertiary); }
.lb-done .lb-dot { background: var(--text-tertiary); }
@keyframes lb-blink { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
""",
    """Component({
  properties: {
    live: { type: Boolean, value: false },
    state: { type: String, value: '' },
  },
})
""",
)

# 5. platform-badge
write_comp(
    "platform-badge",
    """<view class="pb {{'pb-' + platform}}">{{label}}</view>
""",
    """.pb { display: inline-flex; align-items: center; font-size: 12px; padding: 2px 8px; border-radius: 6px; background: var(--surface-2); color: var(--text-secondary); }
.pb-bilibili { background: #F0F9FE; color: #00AEEC; }
.pb-douyin { background: #F5F5F5; color: #3A3A3A; }
.pb-huya { background: #FEF5EC; color: #E07A1F; }
.pb-douyu { background: #F2F8EC; color: #5E9E2F; }
""",
    """Component({
  properties: {
    platform: { type: String, value: '' },
    label: { type: String, value: '' },
  },
})
""",
)

# 6. anchor-status
write_comp(
    "anchor-status",
    """<text class="st {{cls}}">{{text}}</text>
""",
    """.st { font-size: 13px; font-weight: 500; }
.st-live { color: var(--live); }
.st-online { color: var(--online); }
.st-off { color: var(--offline); }
.st-warn { color: var(--warning); }
""",
    """Component({
  properties: {
    state: { type: String, value: 'off' },
    text: { type: String, value: '' },
  },
  data: { cls: 'st-off' },
  observers: {
    state(s) { this.setData({ cls: 'st-' + s }) },
  },
})
""",
)

# 7. anchor-row
write_comp(
    "anchor-row",
    """<view class="ar" hover-class="press-hover" hover-stay-time="60" bindtap="onTap">
  <anchor-avatar src="{{avatar}}" name="{{name}}" size="{{size}}"/>
  <view class="ar-body">
    <view class="ar-top">
      <text class="ar-name t-anchor">{{name}}</text>
      <platform-badge wx:if="{{platform}}" platform="{{platform}}" label="{{platformLabel}}"/>
    </view>
    <view class="ar-meta t-meta">{{meta}}</view>
  </view>
  <view class="ar-right" wx:if="{{showArrow}}"><text class="ar-arrow">&rsaquo;</text></view>
  <slot name="action"/>
</view>
""",
    """.ar { display: flex; align-items: center; gap: 12px; padding: 12px 0; min-height: 68px; }
.ar-body { flex: 1; min-width: 0; }
.ar-top { display: flex; align-items: center; gap: 8px; }
.ar-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ar-meta { margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ar-right { flex-shrink: 0; margin-left: 8px; }
.ar-arrow { color: var(--text-tertiary); font-size: 20px; line-height: 1; }
""",
    """Component({
  properties: {
    avatar: { type: String, value: '' },
    name: { type: String, value: '' },
    platform: { type: String, value: '' },
    platformLabel: { type: String, value: '' },
    meta: { type: String, value: '' },
    size: { type: String, value: 'md' },
    showArrow: { type: Boolean, value: true },
  },
  methods: {
    onTap() { this.triggerEvent('tap') },
  },
  options: { multipleSlots: true },
})
""",
    using={
        "anchor-avatar": "/components/anchor-avatar/index",
        "platform-badge": "/components/platform-badge/index",
    },
)

print("DONE 第一批")
