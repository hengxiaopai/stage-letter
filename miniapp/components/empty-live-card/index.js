Component({
  properties: {
    compact: { type: Boolean, value: false },
  },
  methods: {
    discover() {
      // add 是 TabBar 页面；navigateTo 会被微信拒绝，表现为按钮无响应。
      wx.switchTab({ url: '/pages/add/index' })
    },
  },
});
