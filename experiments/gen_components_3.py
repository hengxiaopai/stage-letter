# -*- coding: utf-8 -*-
"""补: page-header(AppHeader) 二级页面头部"""
import os
import json

COMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "miniapp", "components", "page-header")
os.makedirs(COMP, exist_ok=True)

json.dump({"component": True, "styleIsolation": "apply-shared"}, open(os.path.join(COMP, "page-header.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

open(os.path.join(COMP, "page-header.js"), "w", encoding="utf-8").write("""Component({
  properties: {
    title: { type: String, value: '' },
    showBack: { type: Boolean, value: true },
  },
  methods: {
    onBack() {
      const pages = getCurrentPages()
      if (pages.length > 1) wx.navigateBack()
      else wx.switchTab({ url: '/pages/home/index' })
    },
  },
})
""")

open(os.path.join(COMP, "page-header.wxml"), "w", encoding="utf-8").write("""<view class="ph">
  <view class="ph-back" wx:if="{{showBack}}" bindtap="onBack"><view class="ph-arrow"></view></view>
  <view class="ph-title t-body">{{title}}</view>
  <view class="ph-right"><slot name="right"/></view>
</view>
""")

open(os.path.join(COMP, "page-header.wxss"), "w", encoding="utf-8").write(""".ph { display: flex; align-items: center; height: 48px; padding: 8px 0; }
.ph-back { width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; margin-left: -8px; }
.ph-arrow { width: 10px; height: 10px; border-left: 2px solid var(--text-primary); border-bottom: 2px solid var(--text-primary); transform: rotate(45deg); }
.ph-title { flex: 1; font-weight: 600; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ph-right { min-width: 36px; display: flex; justify-content: flex-end; }
""")

print("OK page-header")
