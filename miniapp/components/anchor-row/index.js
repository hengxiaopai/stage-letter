Component({
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
    // 拦截 action 区域冒泡,防双触发(按钮自身的 catchtap 已是第一道防线)
    onActionTap() {},
  },
  options: { multipleSlots: true },
})
