// pages/profile/index.js — 我的:还可提醒 N 次 + 通知记录
const { getGrants, getHistory, requestGrant } = require('../../services/notifications')
const { parseISO } = require('../../utils/time')

const DETAIL_PAGE_RE = /^pages\/detail\/index\?id=([1-9]\d*)$/

function canonicalDetailPage(anchorId, page) {
  const id = String(anchorId || '')
  const expected = `pages/detail/index?id=${id}`
  if (!DETAIL_PAGE_RE.test(expected) || page !== expected) return null
  return page
}

Page({
  data: {
    count: 0,
    granted: 0,
    loading: true,
    error: null,
    history: [],
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 })
    }
    this.load()
  },

  async load() {
    const app = getApp()
    try {
      const openid = await app.ensureLogin()
      const [grant, history] = await Promise.all([
        getGrants(openid),
        getHistory(openid, 10),
      ])
      const items = (history.items || []).map((h) => ({
        id: h.id,
        title: `${h.display_name || '主播'} 开始直播`,
        meta: this.formatTime(h.started_at) + ' · ' + (h.platform || ''),
        kind: h.channel === 'IN_APP' ? 'inapp' : (h.state === 'SENT' ? 'sent' : 'fail'),
        label: h.channel === 'IN_APP' ? '站内' : (h.state === 'SENT' ? '已发送' : '未送达'),
        page: canonicalDetailPage(h.anchor_id, h.miniapp_path),
      }))
      this.setData({
        count: grant ? grant.available : 0,
        granted: grant ? grant.granted_count : 0,
        history: items,
        loading: false,
        error: null,
      })
    } catch (err) {
      this.setData({ loading: false, error: err.message })
    }
  },

  retryLoad() {
    this.setData({ loading: true, error: null })
    this.load()
  },

  /** 补充提醒次数: 调微信授权,同意 N 次 = N 条额度(单飞锁 + fail 静默) */
  async onTopUp() {
    if (this._topUpPending) return // 单飞锁(UI-2.1A)
    this._topUpPending = true
    try {
      const app = getApp()
      const openid = await app.ensureLogin()
      const templateId = app.globalData.liveStartTemplateId
      if (!templateId) {
        wx.showToast({ title: '微信提醒暂不可用', icon: 'none' })
        return
      }
      const res = await new Promise((resolve) => {
        wx.requestSubscribeMessage({
          tmplIds: [templateId],
          success: resolve,
          fail: () => resolve(null), // fail 静默,不误导
        })
      })
      if (!res) return
      const keys = Object.keys(res).filter((k) => k !== 'errMsg')
      const acceptCount = keys.filter((k) => res[k] === 'accept').length
      if (keys.length > 0) {
        await requestGrant(openid, res)
      }
      if (acceptCount > 0) {
        wx.showToast({ title: `已补充 ${acceptCount} 次提醒`, icon: 'success' })
        this.load()
      }
      // 未 accept → 静默(不弹"未同意授权"误导)
    } catch (err) {
      wx.showToast({ title: err.message, icon: 'none' })
    } finally {
      this._topUpPending = false
    }
  },

  /** §5.4: 了解更多 — 完整机制说明 */
  onWhy() {
    wx.showModal({
      title: '为什么需要补充提醒？',
      content: '微信规定：每次向你发送开播提醒前，都需要你主动点一次「允许」授权。\n\n每点一次「允许」= 增加 1 次提醒额度。额度用完后，开播通知会转为站内记录，不会消失。',
      showCancel: false,
      confirmText: '知道了',
    })
  },

  onHistoryTap(e) {
    const page = e.currentTarget.dataset.page
    if (!page || !DETAIL_PAGE_RE.test(page)) {
      wx.showToast({ title: '通知链接无效', icon: 'none' })
      return
    }
    wx.navigateTo({ url: `/${page}` })
  },

  formatTime(iso) {
    if (!iso) return ''
    const t = parseISO(iso)
    if (isNaN(t)) return iso
    const d = new Date(t)
    const p = (n) => (n < 10 ? '0' + n : '' + n)
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
})
