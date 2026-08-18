// app.js — StageLetter 小程序入口
const { login } = require('./services/auth')

App({
  globalData: {
    openid: null,
    apiBase: 'http://127.0.0.1:8899/api/v1',
  },

  // 登录 Promise 缓存: 页面 onShow 早于登录完成时,等待同一个 Promise
  loginPromise: null,

  onLaunch() {
    this.ensureLogin()
  },

  // 保证只登录一次,返回全局可等待的 Promise
  ensureLogin() {
    if (this.loginPromise) return this.loginPromise
    this.loginPromise = login()
      .then((openid) => {
        this.globalData.openid = openid
        return openid
      })
      .catch((err) => {
        console.error('登录失败:', err)
        this.loginPromise = null // 失败后允许重试
        throw err
      })
    return this.loginPromise
  },
})
