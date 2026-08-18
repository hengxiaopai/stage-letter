// services/api.js — 统一请求封装
// 注意: getApp() 必须在函数内部调用(模块顶层调用时 App() 可能尚未注册完)

/**
 * 通用请求
 * @param {string} path  API 路径(不含 /api/v1)
 * @param {object} options {method, data, query, timeout}
 */
function request(path, options = {}) {
  const app = getApp()
  const { method = 'GET', data = null, query = {} } = options
  const apiBase = app.globalData.apiBase

  // 拼 query(手写,避免依赖 URLSearchParams —— 兼容旧基础库)
  const qs = Object.keys(query)
    .filter((k) => query[k] !== undefined && query[k] !== null)
    .map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(query[k]))
    .join('&')
  const url = `${apiBase}${path}${qs ? '?' + qs : ''}`

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method,
      data,
      timeout: options.timeout || 10000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(new Error((res.data && res.data.detail) || 'HTTP ' + res.statusCode))
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络错误'))
      },
    })
  })
}

module.exports = { request }
