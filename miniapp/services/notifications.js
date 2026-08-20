// services/notifications.js — 通知/grant API
const { request } = require('./api')

/** 查询 grant 余额 */
function getGrants(openid) {
  return request('/notifications/grants', { query: { openid } })
}

/** 持久化 wx.requestSubscribeMessage 的逐模板结果(幂等 intake) */
function requestGrant(openid, grantResults, requestId) {
  const results = Object.keys(grantResults)
    .filter((templateId) => templateId !== 'errMsg')
    .map((templateId) => ({
      template_id: templateId,
      decision: grantResults[templateId],
    }))
  const durableRequestId = requestId || `${Date.now()}-${Math.random().toString(36).slice(2)}`
  return request('/notifications/request-grant', {
    method: 'POST',
    query: { openid },
    data: { request_id: durableRequestId, results },
  })
}

/** 通知历史 */
function getHistory(openid, limit = 20, cursor = null) {
  return request('/notifications/history', {
    query: { openid, limit, cursor },
  })
}

module.exports = { getGrants, requestGrant, getHistory }
