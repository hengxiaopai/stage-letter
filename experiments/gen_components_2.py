# -*- coding: utf-8 -*-
"""生成 StageLetter UI-1 组件体系(第二批: 功能卡/提醒/记录/表单/按钮/空状态/弹层)"""
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


# 8. live-anchor-feature — 首页重点 Live 卡(唯一允许 elevation 的 Live Card)
write_comp(
    "live-anchor-feature",
    """<view class="laf" hover-class="press-hover" hover-stay-time="80" bindtap="onTap">
  <view class="laf-head">
    <anchor-avatar src="{{avatar}}" name="{{name}}" size="lg"/>
    <view class="laf-info">
      <view class="laf-top">
        <text class="laf-name t-anchor">{{name}}</text>
        <platform-badge wx:if="{{platform}}" platform="{{platform}}" label="{{platformLabel}}"/>
      </view>
      <view class="laf-live"><view class="laf-dot"></view>正在直播</view>
    </view>
    <view class="laf-badge">LIVE</view>
  </view>
  <view class="laf-title">{{title}}</view>
  <view class="laf-meta t-meta">{{meta}}</view>
</view>
""",
    """.laf { border: 1px solid var(--border); border-left: 3px solid var(--live); border-radius: var(--r-md); padding: 14px 16px; background: var(--surface); box-shadow: 0 2px 8px rgba(23,26,25,0.05); }
.laf-head { display: flex; align-items: center; gap: 12px; }
.laf-info { flex: 1; min-width: 0; }
.laf-top { display: flex; align-items: center; gap: 8px; }
.laf-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.laf-live { display: inline-flex; align-items: center; gap: 5px; margin-top: 4px; font-size: 13px; font-weight: 500; color: var(--live); }
.laf-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--live); animation: lb-blink 1.4s ease-in-out infinite; }
.laf-badge { flex-shrink: 0; background: var(--live); color: #fff; font-size: 12px; font-weight: 700; letter-spacing: 1px; border-radius: 999px; padding: 4px 12px; }
.laf-title { margin-top: 12px; font-size: 15px; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.laf-meta { margin-top: 4px; }
@keyframes lb-blink { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
""",
    """Component({
  properties: {
    avatar: { type: String, value: '' },
    name: { type: String, value: '' },
    platform: { type: String, value: '' },
    platformLabel: { type: String, value: '' },
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
  },
  methods: {
    onTap() { this.triggerEvent('tap') },
  },
})
""",
    using={
        "anchor-avatar": "/components/anchor-avatar/index",
        "platform-badge": "/components/platform-badge/index",
    },
)

# 9. reminder-status — 开播提醒状态开关行
write_comp(
    "reminder-status",
    """<view class="rs">
  <view class="rs-info">
    <view class="rs-title t-body">开播提醒</view>
    <view class="rs-sub t-meta">{{on ? '开播后第一时间告诉你' : '已关闭'}}</view>
  </view>
  <switch checked="{{on}}" color="#176B8A" bindchange="onChange"/>
</view>
""",
    """.rs { display: flex; align-items: center; justify-content: space-between; padding: 16px 0; }
.rs-info { flex: 1; }
.rs-title { font-weight: 600; }
.rs-sub { margin-top: 2px; }
""",
    """Component({
  properties: {
    on: { type: Boolean, value: true },
  },
  methods: {
    onChange(e) { this.triggerEvent('change', { on: e.detail.value }) },
  },
})
""",
)

# 10. reminder-quota — 还可提醒 N 次(用户语言)
write_comp(
    "reminder-quota",
    """<view class="rq">
  <view class="rq-label t-meta">开播提醒</view>
  <view class="rq-num-row">
    <text class="rq-num">还可提醒</text>
    <text class="rq-count">{{count}}</text>
    <text class="rq-unit">次</text>
  </view>
  <view class="rq-sub t-meta">{{sub}}</view>
</view>
""",
    """.rq { padding: 8px 0 4px; }
.rq-label { margin-bottom: 4px; }
.rq-num-row { display: flex; align-items: baseline; gap: 8px; }
.rq-num { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.rq-count { font-size: 48px; font-weight: 800; letter-spacing: -2px; color: var(--text-primary); line-height: 1; }
.rq-unit { font-size: 16px; font-weight: 600; color: var(--text-secondary); }
.rq-sub { margin-top: 6px; }
""",
    """Component({
  properties: {
    count: { type: Number, value: 0 },
    sub: { type: String, value: '开播后第一时间通知你' },
  },
})
""",
)

# 11. live-history-row — 最近直播记录行
write_comp(
    "live-history-row",
    """<view class="lh">
  <view class="lh-left">
    <view class="lh-title t-body">{{title}}</view>
    <view class="lh-meta t-meta">{{meta}}</view>
  </view>
  <view class="lh-state {{live ? 's-live' : 's-done'}}">{{live ? '直播中' : '已结束'}}</view>
</view>
""",
    """.lh { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--border); }
.lh:last-child { border-bottom: none; }
.lh-left { flex: 1; min-width: 0; }
.lh-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lh-meta { margin-top: 4px; }
.lh-state { flex-shrink: 0; margin-left: 12px; font-size: 12px; font-weight: 500; border-radius: 999px; padding: 3px 10px; }
.s-live { background: var(--live-soft); color: var(--live); }
.s-done { background: var(--surface-2); color: var(--text-tertiary); }
""",
    """Component({
  properties: {
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
    live: { type: Boolean, value: false },
  },
})
""",
)

# 12. notification-row — 通知记录行
write_comp(
    "notification-row",
    """<view class="nr">
  <view class="nr-left">
    <view class="nr-title t-body">{{title}}</view>
    <view class="nr-meta t-meta">{{meta}}</view>
  </view>
  <view class="nr-state {{kind === 'sent' ? 'k-sent' : kind === 'inapp' ? 'k-inapp' : 'k-fail'}}">{{label}}</view>
</view>
""",
    """.nr { display: flex; justify-content: space-between; align-items: center; padding: 14px 0; border-bottom: 1px solid var(--border); }
.nr:last-child { border-bottom: none; }
.nr-left { flex: 1; min-width: 0; }
.nr-title { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nr-meta { margin-top: 4px; }
.nr-state { flex-shrink: 0; margin-left: 12px; font-size: 12px; font-weight: 500; border-radius: 999px; padding: 3px 10px; }
.k-sent { background: var(--online-soft); color: var(--online); }
.k-inapp { background: var(--brand-soft); color: var(--brand); }
.k-fail { background: var(--destructive-soft); color: var(--destructive); }
""",
    """Component({
  properties: {
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
    kind: { type: String, value: 'sent' }, // sent | inapp | fail
    label: { type: String, value: '' },
  },
})
""",
)

# 13. search-field — 搜索框
write_comp(
    "search-field",
    """<view class="sf">
  <view class="sf-icon"></view>
  <input class="sf-input" placeholder="{{placeholder}}" placeholder-class="sf-ph" value="{{value}}" confirm-type="search" bindinput="onInput" bindconfirm="onConfirm"/>
  <view class="sf-clear" wx:if="{{value}}" bindtap="onClear">&times;</view>
</view>
""",
    """.sf { display: flex; align-items: center; gap: 8px; background: var(--surface-2); border-radius: var(--r-sm); padding: 10px 14px; }
.sf-icon { width: 14px; height: 14px; border: 1.5px solid var(--text-tertiary); border-radius: 50%; position: relative; flex-shrink: 0; }
.sf-icon::after { content: ''; position: absolute; right: -4px; bottom: -2px; width: 5px; height: 1.5px; background: var(--text-tertiary); transform: rotate(45deg); }
.sf-input { flex: 1; font-size: 15px; color: var(--text-primary); }
.sf-ph { color: var(--text-tertiary); }
.sf-clear { width: 18px; height: 18px; border-radius: 50%; background: var(--text-tertiary); color: #fff; font-size: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
""",
    """Component({
  properties: {
    placeholder: { type: String, value: '搜索主播名字或粘贴链接' },
    value: { type: String, value: '' },
  },
  methods: {
    onInput(e) { this.triggerEvent('input', { value: e.detail.value }) },
    onConfirm(e) { this.triggerEvent('confirm', { value: e.detail.value }) },
    onClear() { this.triggerEvent('clear') },
  },
})
""",
)

# 14. filter-tabs — 平台筛选器
write_comp(
    "filter-tabs",
    """<scroll-view scroll-x class="ft" show-scrollbar="{{false}}">
  <view class="ft-item {{active === item.value ? 'ft-on' : ''}}" wx:for="{{items}}" wx:key="value" data-value="{{item.value}}" bindtap="onTap">{{item.label}}</view>
</scroll-view>
""",
    """.ft { display: flex; white-space: nowrap; padding: 8px 0; }
.ft-item { display: inline-flex; align-items: center; font-size: 13px; color: var(--text-secondary); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 6px 14px; margin-right: 8px; }
.ft-on { background: var(--brand); color: #fff; border-color: var(--brand); font-weight: 500; }
""",
    """Component({
  properties: {
    items: { type: Array, value: [] },
    active: { type: String, value: 'all' },
  },
  methods: {
    onTap(e) { this.triggerEvent('change', { value: e.currentTarget.dataset.value }) },
  },
})
""",
)

# 15. primary-button
write_comp(
    "primary-button",
    """<button class="btn-primary {{block ? 'btn-block' : ''}}" hover-class="btn-hover" loading="{{loading}}" disabled="{{disabled}}" bindtap="onTap">
  <slot/>
</button>
""",
    """.btn-primary { background: var(--brand); color: #fff; font-size: 15px; font-weight: 600; border-radius: var(--r-md); padding: 0 24px; height: 48px; line-height: 48px; border: none; }
.btn-primary::after { border: none; }
.btn-block { width: 100%; }
.btn-hover { opacity: 0.85; }
""",
    """Component({
  properties: {
    loading: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    block: { type: Boolean, value: true },
  },
  methods: {
    onTap() { if (!this.data.disabled) this.triggerEvent('tap') },
  },
})
""",
)

# 16. secondary-button
write_comp(
    "secondary-button",
    """<button class="btn-secondary {{block ? 'btn-block' : ''}}" hover-class="btn-hover" bindtap="onTap">
  <slot/>
</button>
""",
    """.btn-secondary { background: var(--surface); color: var(--brand); font-size: 15px; font-weight: 600; border-radius: var(--r-md); padding: 0 24px; height: 48px; line-height: 46px; border: 1px solid var(--border); }
.btn-secondary::after { border: none; }
.btn-block { width: 100%; }
.btn-hover { opacity: 0.7; }
""",
    """Component({
  properties: { block: { type: Boolean, value: true } },
  methods: {
    onTap() { this.triggerEvent('tap') },
  },
})
""",
)

# 17. empty-state
write_comp(
    "empty-state",
    """<view class="empty">
  <view class="empty-icon">{{icon}}</view>
  <view class="empty-title t-section">{{title}}</view>
  <view class="empty-sub t-meta" wx:if="{{sub}}">{{sub}}</view>
  <slot/>
</view>
""",
    """.empty { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 80px 24px; text-align: center; }
.empty-icon { width: 64px; height: 64px; border-radius: 50%; background: var(--surface-2); display: flex; align-items: center; justify-content: center; font-size: 28px; margin-bottom: var(--sp-4); }
.empty-title { margin-bottom: var(--sp-2); }
.empty-sub { color: var(--text-secondary); margin-bottom: var(--sp-6); max-width: 280px; }
""",
    """Component({
  properties: {
    icon: { type: String, value: '' },
    title: { type: String, value: '' },
    sub: { type: String, value: '' },
  },
})
""",
)

# 18. bottom-action-sheet — 底部管理弹层(订阅管理: 取消/开关)
write_comp(
    "bottom-action-sheet",
    """<view class="mask" wx:if="{{show}}" bindtap="onClose"/>
<view class="sheet {{show ? 'sheet-in' : ''}}" wx:if="{{show}}">
  <view class="sheet-title t-body">{{title}}</view>
  <view class="sheet-row" wx:for="{{actions}}" wx:key="key" data-key="{{item.key}}" bindtap="onAction">{{item.label}}</view>
  <view class="sheet-cancel" bindtap="onClose">取消</view>
</view>
""",
    """.mask { position: fixed; inset: 0; background: rgba(23,26,25,0.4); z-index: 100; }
.sheet { position: fixed; left: 0; right: 0; bottom: 0; background: var(--surface); border-radius: var(--r-lg) var(--r-lg) 0 0; box-shadow: 0 -4px 24px rgba(23,26,25,0.10); z-index: 101; padding: 8px 0 calc(8px + env(safe-area-inset-bottom)); transform: translateY(100%); transition: transform 0.25s ease; }
.sheet-in { transform: translateY(0); }
.sheet-title { text-align: center; padding: 14px 16px 8px; font-weight: 600; color: var(--text-secondary); }
.sheet-row { text-align: center; padding: 16px; font-size: 16px; color: var(--text-primary); border-top: 1px solid var(--border); }
.sheet-row[data-key="danger"] { color: var(--destructive); }
.sheet-cancel { text-align: center; padding: 16px; font-size: 16px; color: var(--text-secondary); border-top: 1px solid var(--border); }
""",
    """Component({
  properties: {
    show: { type: Boolean, value: false },
    title: { type: String, value: '' },
    actions: { type: Array, value: [] },
  },
  methods: {
    onAction(e) { this.triggerEvent('action', { key: e.currentTarget.dataset.key }) },
    onClose() { this.triggerEvent('close') },
  },
})
""",
)

print("DONE 第二批")
