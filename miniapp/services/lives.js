// services/lives.js — 直播相关 API
const { request } = require('./api')

/** 我订阅的正在直播 */
function getActive(openid) {
  return request('/lives/active', { query: { openid } })
}

/** P0-L3: 高优先级 Refresh — 触发可见主播即时探测, 返回探测后快照 */
function refreshActive(openid) {
  return request('/lives/refresh', { query: { openid }, method: 'POST' })
}

/** 最近开播 */
function getRecent(limit = 50) {
  return request('/lives/recent', { query: { limit } })
}

module.exports = { getActive, getRecent, refreshActive }
