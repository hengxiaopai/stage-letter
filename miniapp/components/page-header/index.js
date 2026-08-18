Component({
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
