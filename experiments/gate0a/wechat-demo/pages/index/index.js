const API = 'http://127.0.0.1:8765'

Page({
  data: {
    webcastId: '975645387460',
    label: 'X.四五六',
    loading: false,
    result: null,
    error: ''
  },

  onLoad() {
    this.refresh()
  },

  onInput(e) {
    this.setData({ webcastId: String(e.detail.value || '').trim() })
  },

  refresh() {
    const webcastId = this.data.webcastId
    if (!/^\d{5,20}$/.test(webcastId)) {
      this.setData({ error: '请输入 5-20 位数字 webcast_id', result: null })
      return
    }

    this.setData({ loading: true, error: '' })
    wx.request({
      url: `${API}/api/gate0a/douyin/live`,
      method: 'GET',
      data: { webcast_id: webcastId, label: this.data.label },
      timeout: 25000,
      success: (res) => {
        const payload = res.data || {}
        this.setData({
          result: payload,
          error: payload.ok === false ? (payload.error_type || 'UNKNOWN_ERROR') : ''
        })
      },
      fail: (err) => {
        this.setData({
          result: null,
          error: `本地代理不可达：${err.errMsg || 'request failed'}`
        })
      },
      complete: () => this.setData({ loading: false })
    })
  }
})
