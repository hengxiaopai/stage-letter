// services/notifications.js — 通知/grant API
const { request } = require('./api')

/** 查询 grant 余额 */
function getGrants(openid) {
  return request('/notifications/grants', { query: { openid } })
}

/** 记录授权(request-grant) */
function requestGrant(openid, acceptCount = 1) {
  return request('/notifications/request-grant', {
    method: 'POST',
    query: { openid },
    data: { accept_count: acceptCount },
  })
}

/** 通知历史 */
function getHistory(openid, limit = 20, cursor = 0) {
  return request('/notifications/history', {
    query: { openid, limit, cursor },
  })
}

module.exports = { getGrants, requestGrant, getHistory }
