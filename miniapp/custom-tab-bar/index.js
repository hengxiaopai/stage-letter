// custom-tab-bar — 编辑式导航(§十: Brand Soft 选中底 + 轻过渡)
Component({
  data: {
    selected: 0,
    list: [
      { pagePath: '/pages/home/index', text: '首页', icon: 'home' },
      { pagePath: '/pages/subscriptions/index', text: '订阅', icon: 'star' },
      { pagePath: '/pages/profile/index', text: '我的', icon: 'user' },
    ],
  },

  methods: {
    onTap(e) {
      const index = e.currentTarget.dataset.index
      const item = this.data.list[index]
      if (index === this.data.selected) return
      wx.switchTab({ url: item.pagePath })
    },
  },
})
