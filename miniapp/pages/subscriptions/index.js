// pages/subscriptions/index.js — 我的订阅(开放式 List + ··· 二级管理)
const { listSubscriptions, unsubscribe } = require('../../services/subscriptions')

const PLATFORM_LABEL = { douyin: '抖音', bilibili: 'B站', huya: '虎牙', douyu: '斗鱼' }

Page({
  data: {
    subs: [],
    total: 0,
    liveCount: 0,
    loading: true,
    error: null,
    sheetShow: false,
    sheetTitle: '',
    sheetActions: [],
    activeSub: null,
  },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 })
    }
    this.load()
  },

  async load() {
    const app = getApp()
    try {
      const openid = await app.ensureLogin()
      const res = await listSubscriptions(openid)
      const mapped = (res || []).map((s) => {
        // P0: live_state → UI 唯一映射(UNKNOWN/FAILED/STALE 不得显示"未开播")
        //   LIVE       → 正在直播
        //   OFFLINE    → 未开播
        //   CONFIRMING → 状态确认中…
        //   UNKNOWN    → 暂时无法确认状态
        //   freshness=stale → 状态待更新(附在 meta)
        const st = s.live_state || (s.is_live === true ? 'LIVE' : 'UNKNOWN')
        let meta = ''
        if (st === 'LIVE') meta = '正在直播'
        else if (st === 'OFFLINE') meta = '未开播'
        else if (st === 'CHECKING' || st === 'CONFIRMING') meta = '状态确认中…'
        else if (st === 'UNKNOWN' || st === 'DEGRADED') {
          // 2026-08-14: 从未成功探测(新订阅/worker 首轮未跑) → 首次检测中, 不是"持续失败"
          meta = s.freshness === 'never' ? '首次检测中…' : '检测失败 · 正在持续重试'
        }
        else meta = '未开播'
        if (s.freshness === 'stale' && st !== 'LIVE') meta += ' · 状态待更新'
        return {
          ...s,
          platformLabel: PLATFORM_LABEL[s.platform] || s.platform,
          meta,
          // 仅确认 LIVE 且 fresh 才算"直播中"(置顶/统计)
          isLiveFlag: st === 'LIVE' && s.freshness !== 'stale',
        }
      })
      // §2.2: 稳定排序 — 已确认直播固定置顶,其余保持后端顺序
      const subs = mapped.sort((a, b) => (b.isLiveFlag ? 1 : 0) - (a.isLiveFlag ? 1 : 0))
      this.setData({
        subs,
        total: subs.length,
        liveCount: subs.filter((s) => s.isLiveFlag).length,
        loading: false,
        error: null,
      })
    } catch (err) {
      this.setData({ loading: false, error: err.message })
    }
  },

  /** 行点击 → 进详情 */
  goDetail(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/detail/index?id=${id}` })
  },

  /** ··· 管理入口(§2.3: 点击不触发行详情;§2.4: 动态开关文案) */
  onManage(e) {
    const id = e.currentTarget.dataset.id
    const sub = this.data.subs.find((s) => s.id === id)
    if (!sub) return
    this.setData({
      sheetShow: true,
      sheetTitle: sub.display_name || sub.platform,
      activeSub: sub,
      sheetActions: [
        { key: 'toggle', label: '开启 / 关闭开播提醒' },
        { key: 'danger', label: '取消订阅' },
      ],
    })
  },

  /** ActionSheet 点击(§2.4: danger 需二次确认) */
  onSheetAction(e) {
    const { key } = e.detail
    const sub = this.data.activeSub
    this.setData({ sheetShow: false })

    if (key === 'danger' && sub) {
      // 二次确认,明确主播名
      wx.showModal({
        title: '取消订阅',
        content: `确定取消订阅「${sub.display_name || '该主播'}」吗？\n取消后将不再接收他的开播提醒。`,
        confirmText: '取消订阅',
        confirmColor: '#D7473F',
        success: (res) => {
          if (res.confirm) this.doUnsubscribe(sub.id, sub.display_name)
        },
      })
    } else if (key === 'toggle' && sub) {
      wx.showToast({ title: '开播提醒设置', icon: 'none' })
    }
  },

  onSheetClose() {
    this.setData({ sheetShow: false })
  },

  /**
   * 取消订阅 — 单向状态机 + single-flight(§二/§三/§四)
   * SUBSCRIBED → CONFIRM(二次确认) → UNSUBSCRIBING(锁定) → UNSUBSCRIBED
   *   失败 → ERROR → 回到 SUBSCRIBED
   * 404 = already unsubscribed → 幂等 reconcile(本地清掉,不弹错)
   */
  async doUnsubscribe(id, name) {
    // single-flight: 防重复 DELETE(锁定)
    if (this._unsubscribing) return
    this._unsubscribing = true
    wx.showLoading({ title: '正在取消…', mask: true })
    try {
      await unsubscribe(id)
      this.removeLocal(id)
      wx.showToast({ title: '已取消', icon: 'success' })
    } catch (err) {
      // 幂等: 404 = 已经没订阅了 → 视为成功
      if (err.message.includes('404') || err.message.includes('not found')) {
        this.removeLocal(id)
        wx.showToast({ title: '已取消', icon: 'success' })
      } else {
        wx.showToast({ title: err.message, icon: 'none' })
      }
    } finally {
      this._unsubscribing = false
      wx.hideLoading()
    }
  },

  removeLocal(id) {
    const subs = this.data.subs.filter((s) => s.id !== id)
    this.setData({
      subs,
      total: subs.length,
      liveCount: subs.filter((s) => s.is_live).length,
    })
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },

  goAdd() {
    wx.navigateTo({ url: '/pages/add/index' })
  },
})
