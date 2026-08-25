// pages/detail/index.js — 主播详情(主播消费页, UI-2 精修)
const { getAnchor } = require('../../services/anchors')
const { updateReminderPreference } = require('../../services/subscriptions')
const { fmtDur } = require('../../utils/time')

const PLATFORM_LABEL = { douyin: '抖音', bilibili: 'B站', huya: '虎牙', douyu: '斗鱼' }
const POSITIVE_ID_RE = /^[1-9]\d*$/

Page({
  data: {
    loading: true,
    error: null,
    name: '',
    avatar: '',
    platform: '',
    platformLabel: '',
    live: false,
    sessionTitle: '',
    sessionMeta: '',
    canonicalUrl: '',
    remindOn: false,
    remindSaving: false,
    isFollowing: false,
    history: [],
  },

  onLoad(options) {
    const anchorId = String((options && options.id) || '')
    if (!POSITIVE_ID_RE.test(anchorId)) {
      this.setData({ loading: false, error: '主播信息无效' })
      return
    }
    this.anchorId = anchorId
    this.load()
  },

  async load() {
    try {
      const openid = await getApp().ensureLogin()
      const anchor = await getAnchor(this.anchorId, openid)
      const platform = (anchor.platforms || []).sort((a, b) =>
        // P0: 仅确认 LIVE+fresh 排前(不按 is_live 旧 bool 排序)
        ((b.live_state === 'LIVE' && b.freshness !== 'stale') ? 1 : 0) -
        ((a.live_state === 'LIVE' && a.freshness !== 'stale') ? 1 : 0)
      )[0]
      const sess = platform && platform.current_session
      // P0: live_state → UI 唯一映射
      //   LIVE+fresh → 正在直播; OFFLINE → 未开播; CONFIRMING → 状态确认中; UNKNOWN → 暂时无法确认
      const pst = platform ? (platform.live_state || 'UNKNOWN') : 'UNKNOWN'
      const pFresh = platform ? (platform.freshness || 'stale') : 'stale'
      const isLiveConfirmed = pst === 'LIVE' && pFresh !== 'stale'
      let liveLabel = '未开播'
      if (pst === 'LIVE') liveLabel = isLiveConfirmed ? '正在直播' : '状态待更新'
      else if (pst === 'CHECKING' || pst === 'CONFIRMING') liveLabel = '状态确认中…'
      else if (pst === 'UNKNOWN' || pst === 'DEGRADED') {
        // 2026-08-14: 从未成功探测(新订阅未入库/worker 首轮未跑) → 首次检测中, 不是"持续失败"
        liveLabel = pFresh === 'never' ? '首次检测中…' : '检测失败 · 正在持续重试'
      }
      wx.setNavigationBarTitle({ title: anchor.display_name || '主播详情' })
      // 2026-08-14: 开播时间来源 — probe=探测时刻兜底(非真实开播时间), 不假装平台数据
      const sessSource = sess && sess.started_at_source
      const showSessionTime = sess && sessSource !== 'probe'
      const sessionMeta = sess
        ? (showSessionTime
            ? `${sess.started_at || ''} 开播 · ${fmtDur(sess.started_at_iso || sess.started_at)}`
            : '检测到直播中 · 开播时间未知')
        : ''
      this.setData({
        loading: false,
        name: anchor.display_name || '未知主播',
        avatar: anchor.avatar || '',
        platform: platform ? platform.platform : '',
        platformLabel: platform ? (PLATFORM_LABEL[platform.platform] || platform.platform) : '',
        live: isLiveConfirmed,
        liveLabel,
        // §3.2: 标题优先;时间"12:09 开播 · 已播 3小时12分"
        // probe 来源(抖音匿名等)不显示精确开播时间, 显示"检测到直播中 · 开播时间未知"
        sessionTitle: (sess && sess.title) || '',
        sessionMeta,
        canonicalUrl: platform ? platform.canonical_url : '',
        platformAccountId: platform ? platform.platform_account_id : null,
        isFollowing: Boolean(platform && platform.is_following),
        remindOn: Boolean(platform && platform.reminder_enabled),
        // §3.5: 当前 live session 显示"进行中",不显示"已结束"
        history: (anchor.recent_sessions || []).map((s, i) => {
          const isCurrent = isLiveConfirmed && i === 0 && s.id === (sess && sess.id)
          const isLiveFirst = isLiveConfirmed && i === 0
          const liveState = isLiveFirst // 首条且平台在播 → 进行中
          return {
            id: s.id,
            title: s.title || '直播',
            // 后端已给友好时间(08-13 12:09),直接用;结束"进行中"由后端 ended_at 处理
            // probe 来源不显示开播时刻(不是真实数据)
            meta: `${s.started_at_source !== 'probe' ? (s.started_at || '') : ''}${s.ended_at ? ' – ' + s.ended_at : ''}`,
            live: liveState,
            // 状态文字: 进行中(当前在播首条) / 已结束
            stateLabel: liveState ? '进行中' : '已结束',
          }
        }),
      })
    } catch (err) {
      this.setData({ loading: false, error: err.message })
    }
  },

  retryLoad() {
    this.setData({ loading: true, error: null })
    this.load()
  },

  /** §3.3 P0: 当前仅支持复制 → 按钮文案与行为一致 */
  onGoLive() {
    if (!this.data.canonicalUrl) {
      wx.showToast({ title: '暂无直播间链接', icon: 'none' })
      return
    }
    wx.setClipboardData({
      data: this.data.canonicalUrl,
      success: () => wx.showToast({ title: '直播间链接已复制', icon: 'none' }),
    })
  },

  async onRemindChange(e) {
    const enabled = e.detail.on
    const previous = this.data.remindOn
    if (!this.data.isFollowing || !this.data.platformAccountId) {
      wx.showToast({ title: '请先订阅该主播', icon: 'none' })
      return
    }
    if (this.data.remindSaving) return

    this.setData({ remindOn: enabled, remindSaving: true })
    try {
      const openid = await getApp().ensureLogin()
      const preference = await updateReminderPreference(
        openid,
        this.data.platformAccountId,
        enabled
      )
      this.setData({ remindOn: Boolean(preference.enabled) })
      wx.showToast({ title: preference.enabled ? '开播提醒已开启' : '开播提醒已关闭', icon: 'none' })
    } catch (err) {
      this.setData({ remindOn: previous })
      wx.showToast({ title: '保存失败，请重试', icon: 'none' })
    } finally {
      this.setData({ remindSaving: false })
    }
  },
})
