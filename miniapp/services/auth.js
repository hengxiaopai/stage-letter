// services/auth.js — 微信登录
const { request } = require('./api')

/**
 * 微信登录
 * @returns {Promise<object>} 登录会话配置
 */
function login() {
  return new Promise((resolve, reject) => {
    wx.login({
      success(res) {
        if (!res.code) {
          reject(new Error('微信登录失败，请重试'))
          return
        }
        request('/auth/login', {
          method: 'POST',
          data: { code: res.code },
        })
          .then((data) => {
            if (!data || !data.openid) {
              reject(new Error('登录响应无效，请重试'))
              return
            }
            resolve(data)
          })
          .catch(reject)
      },
      fail() {
        reject(new Error('微信登录失败，请检查网络后重试'))
      },
    })
  })
}

module.exports = { login }
