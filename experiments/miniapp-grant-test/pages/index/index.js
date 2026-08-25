// pages/index/index.js — 订阅消息授权测试页
Page({
  data: {
    loginCode: '',
    templateId: 'VehDuOW2xRXubcWgFvcgnFnp42wdA3uesHpjfmBP-Cs',
    lastResult: '',
    log: [],
    busy: false,
  },

  onLoad() {
    // 如果 onLaunch 的 wx.login 已经完成,会在这里拿到 code
    this.addLog('页面已加载,等待授权操作')
  },

  addLog(msg) {
    const now = new Date()
    const ts = now.toTimeString().slice(0, 8)
    this.setData({ log: [`[${ts}] ${msg}`].concat(this.data.log).slice(0, 30) })
  },

  // 按钮 1:重新拿 code(如果之前没拿到)
  doLogin() {
    this.addLog('正在 wx.login ...')
    wx.login({
      success: (r) => {
        console.log('LOGIN_CODE:', r.code)
        this.setData({ loginCode: r.code || 'FAIL' })
        this.addLog(r.code ? '拿到 code:' + r.code.slice(0, 12) + '...' : 'wx.login 未返回 code')
      },
      fail: (e) => {
        console.error(e)
        this.addLog('wx.login 失败:' + JSON.stringify(e))
      },
    })
  },

  // 按钮 2:触发订阅消息授权弹窗(核心)
  requestSub() {
    if (this.data.busy) return
    this.setData({ busy: true })
    this.addLog('调用 wx.requestSubscribeMessage ...')

    wx.requestSubscribeMessage({
      tmplIds: [this.data.templateId],
      success: (res) => {
        console.log('SUB_RESULT:', res)
        const val = res[this.data.templateId]
        let msg
        if (val === 'accept') msg = '✅ 用户点【允许】授权成功'
        else if (val === 'reject') msg = '❌ 用户点【拒绝】'
        else if (val === 'ban') msg = '🚫 被系统拉黑/屏蔽'
        else if (val === 'filter') msg = '🔕 用户长期不点击,被过滤'
        else msg = '❓ 未知结果:' + JSON.stringify(res)

        this.setData({ lastResult: val || '?', busy: false })
        this.addLog(msg + ' (result=' + val + ')')
      },
      fail: (err) => {
        console.error(err)
        const e = err || {}
        this.setData({ busy: false })
        this.addLog('❌ 调用失败 errMsg=' + (e.errMsg || JSON.stringify(e)))
      },
    })
  },

  // 按钮 3:一键复制 loginCode(方便发给我)
  copyCode() {
    const c = this.data.loginCode
    if (!c) {
      this.addLog('还没有 code,先点"重新获取 code"')
      return
    }
    wx.setClipboardData({
      data: c,
      success: () => this.addLog('已复制 code 到剪贴板'),
    })
  },

  // 按钮 4:清空日志
  clearLog() {
    this.setData({ log: [] })
  },
})
