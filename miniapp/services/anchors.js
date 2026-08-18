// services/anchors.js — 主播 API
const { request } = require('./api')

/** 主播详情 */
function getAnchor(anchorId) {
  return request(`/anchors/${anchorId}`)
}

module.exports = { getAnchor }
