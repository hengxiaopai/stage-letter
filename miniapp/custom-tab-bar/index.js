// custom-tab-bar — 编辑式导航(§十: Brand Soft 选中底 + 轻过渡)
Component({
  data: {
    selected: 0,
    list: [
      { pagePath: '/pages/home/index', text: '首页', icon: '/assets/tabbar/home-mail.png' },
      { pagePath: '/pages/add/index', text: '发现', icon: '/assets/tabbar/discover-compass.png' },
      { pagePath: '/pages/messages/index', text: '消息', icon: '/assets/tabbar/messages-bubble.png' },
      { pagePath: '/pages/profile/index', text: '我的', icon: '/assets/tabbar/profile-user.png' },
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
