// pages/profile/index.js — 我的：仅展示当前用户可验证的订阅与提醒事实
const { getGrants, getHistory, requestGrant } = require('../../services/notifications')
const { listSubscriptions } = require('../../services/subscriptions')

Page({
  data: {
    count: 0,
    granted: 0,
    subscriptionCount: 0,
    notificationCount: 0,
    loading: true,
    error: null,
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 3 })
    }
    this.load()
  },

  async load() {
    const app = getApp()
    try {
      const openid = await app.ensureLogin()
      const [grant, history, subscriptions] = await Promise.all([
        getGrants(openid),
        getHistory(openid, 10),
        listSubscriptions(openid),
      ])
      this.setData({
        count: grant ? grant.available : 0,
        granted: grant ? grant.granted_count : 0,
        subscriptionCount: (subscriptions || []).length,
        notificationCount: (history.items || []).length,
        loading: false,
        error: null,
      })
    } catch (err) {
      this.setData({ loading: false, error: 'load_failed' })
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
      wx.showToast({ title: '暂时无法补充提醒次数', icon: 'none' })
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

  goSubscriptions() {
    wx.navigateTo({ url: '/pages/subscriptions/index' })
  },

  goMessages() {
    wx.switchTab({ url: '/pages/messages/index' })
  },

  onSettings() {
    wx.showToast({ title: '设置功能即将开放', icon: 'none' })
  },

  onAbout() {
    wx.showModal({
      title: '关于开场信',
      content: '开场信为你汇集关注主播的开播状态，并在可用时及时提醒。',
      showCancel: false,
    })
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
})
