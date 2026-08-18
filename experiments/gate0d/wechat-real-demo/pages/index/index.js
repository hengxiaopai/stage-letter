Page({
  data: {
    templateId: '',
    subscribeResult: '',
    loginCode: '',
    error: ''
  },

  onTemplateInput(e) {
    this.setData({ templateId: String(e.detail.value || '').trim() })
  },

  requestSubscription() {
    const templateId = this.data.templateId
    if (!templateId) {
      this.setData({ error: '请先填写真实订阅消息模板 ID', subscribeResult: '' })
      return
    }

    this.setData({ error: '', subscribeResult: '' })
    wx.requestSubscribeMessage({
      tmplIds: [templateId],
      success: (res) => {
        const value = res[templateId]
        this.setData({
          subscribeResult: JSON.stringify({
            errMsg: res.errMsg || '',
            templateResult: value || 'MISSING'
          }),
          error: ''
        })
      },
      fail: (err) => {
        this.setData({
          subscribeResult: '',
          error: JSON.stringify({
            errMsg: err.errMsg || '',
            errCode: err.errCode === undefined ? null : err.errCode
          })
        })
      }
    })
  },

  getLoginCode() {
    this.setData({ error: '', loginCode: '' })
    wx.login({
      timeout: 10000,
      success: (res) => {
        if (!res.code) {
          this.setData({ error: 'wx.login 成功回调但没有 code' })
          return
        }
        this.setData({ loginCode: res.code })
      },
      fail: (err) => {
        this.setData({ error: err.errMsg || 'wx.login failed' })
      }
    })
  },

  copyLoginCode() {
    if (!this.data.loginCode) return
    wx.setClipboardData({ data: this.data.loginCode })
  }
})
