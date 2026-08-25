// services/subscriptions.js — 订阅管理 API
// 注意: 统一用 openid 调用后端(后端自动查/建 user)
const { request } = require('./api')

/** 订阅主播 */
function subscribe(openid, platform, platformUserId, canonicalUrl, displayName, avatar) {
  return request('/subscriptions', {
    method: 'POST',
    data: {
      openid,
      platform,
      platform_user_id: platformUserId,
      canonical_url: canonicalUrl,
      display_name: displayName,
      avatar: avatar || undefined,
    },
  })
}

/** 我的订阅列表 */
function listSubscriptions(openid) {
  return request('/subscriptions', { query: { openid } })
}

/** 取消订阅 */
function unsubscribe(subId) {
  return request(`/subscriptions/${subId}`, { method: 'DELETE' })
}

/** 更新已订阅平台账号的开播提醒偏好 */
function updateReminderPreference(openid, platformAccountId, enabled) {
  return request(`/notification-preferences/${platformAccountId}`, {
    method: 'PATCH',
    data: { openid, enabled },
  })
}

/** 解析主播 URL */
function parseAnchor(url) {
  return request('/anchors/parse', { method: 'POST', data: { url } })
}

/**
 * 按名字搜索主播 (V2 结构化响应)
 * 返回: {status, items, ms_used, source, hint, platform, keyword}
 * status: SUCCESS / EMPTY / DEGRADED / TIMEOUT / BLOCKED / PARSE_ERROR
 * 注意: 浏览器搜索(虎牙/斗鱼)需 8-15s,抖音直接 BLOCKED (P0-09 根因: 需登录态)
 */
function searchAnchors(openid, platform, keyword, limit = 15) {
  return request('/anchors/_search', {
    query: { openid, platform, keyword, limit },
    timeout: 35000,
  }).then((resp) => {
    // 兼容 V1 旧响应(纯数组)— 防御性
    if (Array.isArray(resp)) {
      return {
        status: resp.length > 0 ? 'SUCCESS' : 'EMPTY',
        items: resp,
        ms_used: 0,
        source: 'legacy',
        hint: '',
        platform,
        keyword,
      }
    }
    return resp
  })
}

module.exports = {
  subscribe,
  listSubscriptions,
  unsubscribe,
  updateReminderPreference,
  parseAnchor,
  searchAnchors,
}
