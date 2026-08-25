Component({
  properties: {},
  methods: {
    discover() {
      // add 是 TabBar 页面；必须使用 switchTab。
      wx.switchTab({ url: '/pages/add/index' })
    },
  },
});
