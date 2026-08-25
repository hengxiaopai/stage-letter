// services/anchors.js — 主播 API
const { request } = require('./api')

/** 主播详情 */
function getAnchor(anchorId, openid) {
  return request(`/anchors/${anchorId}`, { query: openid ? { openid } : {} })
}

module.exports = { getAnchor }
