// pages/profile/index.js — 我的:还可提醒 N 次 + 通知记录
const { getGrants, getHistory, requestGrant } = require('../../services/notifications')
const { parseISO } = require('../../utils/time')

Page({
  data: {
    count: 0,
    granted: 0,
    loading: true,
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
        kind: h.channel === 'in_app' ? 'inapp' : (h.state === 'SENT' ? 'sent' : 'fail'),
        label: h.channel === 'in_app' ? '站内' : (h.state === 'SENT' ? '已发送' : '未送达'),
      }))
      this.setData({
        count: grant ? grant.available : 0,
        granted: grant ? grant.granted_count : 0,
        history: items,
        loading: false,
      })
    } catch (err) {
      this.setData({ loading: false })
    }
  },

  /** 补充提醒次数: 调微信授权,同意 N 次 = N 条额度(单飞锁 + fail 静默) */
  async onTopUp() {
    if (this._topUpPending) return // 单飞锁(UI-2.1A)
    this._topUpPending = true
    const openid = await getApp().ensureLogin()
    try {
      const res = await new Promise((resolve) => {
        wx.requestSubscribeMessage({
          tmplIds: ['VehDuOW2xRXubcWgFvcgnFnp42wdA3uesHpjfmBP-Cs'],
          success: resolve,
          fail: () => resolve(null), // fail 静默,不误导
        })
      })
      if (!res) return
      const keys = Object.keys(res).filter((k) => k !== 'errMsg')
      const acceptCount = keys.filter((k) => res[k] === 'accept').length
      if (acceptCount > 0) {
        await requestGrant(openid, acceptCount)
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
