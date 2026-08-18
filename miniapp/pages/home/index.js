// pages/home/index.js — 首页:今天谁开播了？
const { getActive, refreshActive } = require('../../services/lives')
const { listSubscriptions } = require('../../services/subscriptions')
const { fmtHM, fmtDur } = require('../../utils/time')

const PLATFORM_LABEL = { douyin: '抖音', bilibili: 'B站', huya: '虎牙', douyu: '斗鱼' }

Page({
  data: {
    liveList: [],    // 正在直播(重点卡) — 仅 LIVE 状态(后端 active 已保证)
    checkingList: [], // 状态确认中(CHECKING/SUSPECT 短暂过渡态)
    unknownList: [],  // 暂时无法确认(UNKNOWN/PROBE_FAILED/DEGRADED — 检测失败)
    waitList: [],    // 等待开播(弱化)
    total: 0,
    liveCount: 0,
    checkingCount: 0,
    unknownCount: 0,
    loading: true,
    error: null,
  },

  onShow() {
    // custom-tab-bar 选中态同步(§十)
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 0 })
    }
    this.loadAll()
    // P0-L3: 高优先级 Refresh — 后台触发一轮即时探测(不阻塞 UI, 结果下次拉取生效)
    this.refreshStatus()
  },

  /** P0-L3: 触发可见主播即时探测(前端不等待, 失败静默) */
  async refreshStatus() {
    try {
      const openid = await getApp().ensureLogin()
      await refreshActive(openid)
    } catch (e) {
      // 刷新失败静默 — 主 loadAll 已展示缓存状态
    }
  },

  async loadAll() {
    const app = getApp()
    try {
      const openid = await app.ensureLogin()
      const [activeRes, subs] = await Promise.all([
        getActive(openid),
        listSubscriptions(openid),
      ])
      // P0-LiveTruth: Live State → UI 唯一映射(四组互斥)
      //   LIVE       → liveList(正在直播)
      //   CHECKING   → checkingList(状态确认中, 短暂过渡态)
      //   UNKNOWN/DEGRADED → unknownList(暂时无法确认 · 检测失败)
      //   OFFLINE    → waitList(等待开播)
      const liveList = (activeRes.items || []).map((it) => {
        const sess = it.session || {}
        // 2026-08-14: probe 来源(抖音匿名等)开播时间非真实 → 不显示精确时刻
        const showTime = sess.started_at_source !== 'probe'
        return {
          anchor_id: it.anchor_id,
          anchor_name: it.anchor_name,
          anchor_avatar: it.anchor_avatar,
          platform: it.platform,
          platformLabel: PLATFORM_LABEL[it.platform] || it.platform,
          live_state: it.live_state || 'LIVE',
          title: sess.title || '',
          meta: showTime ? `${fmtHM(sess.started_at)} 开播 · ${fmtDur(sess.started_at)}` : '检测到直播中',
        }
      })

      const liveIds = new Set(liveList.map((it) => it.anchor_id))
      const checkingList = []
      const unknownList = []
      const waitList = []

      for (const s of subs || []) {
        const st = s.live_state || (s.is_live === true ? 'LIVE' : 'UNKNOWN')
        const row = {
          anchor_id: s.anchor_id,
          anchor_name: s.display_name || s.platform,
          anchor_avatar: s.avatar,
          platform: s.platform,
          platformLabel: PLATFORM_LABEL[s.platform] || s.platform,
          live_state: st,
          freshness: s.freshness || 'stale',
        }
        // 唯一映射: 已在直播列表的不再进任何其他组
        if (liveIds.has(s.anchor_id)) continue
        if (st === 'CHECKING' || st === 'CONFIRMING') {
          checkingList.push(row)
        } else if (st === 'UNKNOWN' || st === 'DEGRADED') {
          unknownList.push(row)
        } else {
          waitList.push(row)
        }
      }

      this.setData({
        liveList,
        checkingList,
        unknownList,
        waitList,
        total: liveList.length + checkingList.length + unknownList.length + waitList.length,
        liveCount: liveList.length,
        checkingCount: checkingList.length,
        unknownCount: unknownList.length,
        loading: false,
        error: null,
      })
    } catch (err) {
      this.setData({ loading: false, error: err.message })
    }
  },

  onPullDownRefresh() {
    this.loadAll().finally(() => wx.stopPullDownRefresh())
  },

  goAdd() {
    wx.navigateTo({ url: '/pages/add/index' })
  },

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    wx.navigateTo({ url: `/pages/detail/index?id=${id}` })
  },
})
