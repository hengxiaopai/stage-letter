// app.js — StageLetter 小程序入口
const { login } = require('./services/auth')

App({
  globalData: {
    openid: null,
    apiBase: 'http://192.168.1.6:8899/api/v1',
    liveStartTemplateId: null,
    loginState: 'idle',
    loginError: null,
  },

  // 登录 Promise 缓存: 页面 onShow 早于登录完成时,等待同一个 Promise
  loginPromise: null,

  onLaunch() {
    // 页面会复用同一个登录 Promise；启动预热失败由页面重试并展示。
    this.ensureLogin().catch(() => {})
  },

  // 保证只登录一次,返回全局可等待的 Promise
  ensureLogin() {
    if (this.globalData.openid) return Promise.resolve(this.globalData.openid)
    if (this.loginPromise) return this.loginPromise
    Object.assign(this.globalData, { loginState: 'authenticating', loginError: null })
    this.loginPromise = login()
      .then((session) => {
        const openid = session.openid
        Object.assign(this.globalData, {
          openid,
          liveStartTemplateId: session.live_start_template_id || null,
          loginState: 'authenticated',
          loginError: null,
        })
        return openid
      })
      .catch((err) => {
        console.error('登录失败:', err)
        Object.assign(this.globalData, {
          openid: null,
          loginState: 'failed',
          loginError: err.message || '微信登录失败',
        })
        throw err
      })
      .finally(() => {
        this.loginPromise = null // 成功后走 openid 快路径；失败后允许重试
      })
    return this.loginPromise
  },
})
