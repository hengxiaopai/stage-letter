// services/auth.js — 微信登录
const { request } = require('./api')

// Dev 模式: 固定本地联调 openid(不走微信真实登录)
// 生产: 置为 null,走 wx.login → code2session
const DEV_OPENID = 'dev_miniapp_local_001'

/**
 * 微信登录
 * @returns {Promise<string>} openid
 */
function login() {
  // Dev 模式: 直接返回固定 openid(本地联调,避免 wx.login 每次新用户)
  if (DEV_OPENID) {
    return Promise.resolve(DEV_OPENID)
  }

  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (!res.code) {
          reject(new Error('wx.login 未返回 code'))
          return
        }
        request('/auth/login', {
          method: 'POST',
          data: { code: res.code },
        })
          .then((data) => resolve(data.openid))
          .catch(reject)
      },
      fail: reject,
    })
  })
}

module.exports = { login }
