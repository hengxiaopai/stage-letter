// pages/add/index.js — 添加订阅: 全局搜索(平台筛选器) / 粘贴链接
const { parseAnchor, subscribe, searchAnchors } = require('../../services/subscriptions')
const { requestGrant } = require('../../services/notifications')

const PLATFORM_LABEL = { douyin: '抖音', bilibili: 'B站', huya: '虎牙', douyu: '斗鱼' }

Page({
  data: {
    mode: 'search',           // search | link
    // 搜索 (P0-10: Tab 只是筛选, 不触发搜索)
    keyword: '',
    platform: 'all',          // all = 全局 | bilibili | douyin | huya | douyu
    searching: false,
    allResults: [],           // 完整结果集(platform=all 一次返回, Tab 切换只做本地筛选)
    results: [],              // 当前 Tab 显示的子集
    platformStatus: {},       // {platform: {status, hint, count}} (V3)
    searchError: null,
    searchMsg: null,
    searchStatus: null,       // V2: SUCCESS/EMPTY/TIMEOUT/BLOCKED/PARSE_ERROR
    searchHint: '',           // V2: 后端 hint
    showPasteLinkCta: false,  // V2: 当抖音 BLOCKED 或全平台 EMPTY 时显示「粘贴链接」按钮
    filterTabs: [
      { label: '全部', value: 'all' },
      { label: '抖音', value: 'douyin' },
      { label: 'B站', value: 'bilibili' },
      { label: '虎牙', value: 'huya' },
      { label: '斗鱼', value: 'douyu' },
    ],
    topicTabs: [
      { label: '推荐主播', value: 'recommended' },
      { label: '热门游戏', value: 'games' },
      { label: '娱乐', value: 'entertainment' },
      { label: '颜值', value: 'beauty' },
      { label: '聊天', value: 'chat' },
    ],
    activeTopic: 'recommended',
    platformLabelMap: PLATFORM_LABEL,
    // 链接
    url: '',
    parsed: null,
    parsing: false,
    parseError: null,
  },

  // P0-10: 递增 query session — 旧请求返回不污染新 query
  _querySession: 0,

  switchMode(e) {
    this.setData({
      mode: e.currentTarget.dataset.mode,
      results: [],
      searchMsg: null,
      searchError: null,
      searchStatus: null,
      searchHint: '',
      showPasteLinkCta: false,
    })
  },

  /** P0-08: 从订阅页返回时,同步搜索结果行的订阅状态(取消后立即恢复「订阅」) */
  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 })
    }
    if (this.data.results.length > 0) this.syncSubStatus()
  },

  /** 用订阅列表刷新现有搜索结果行的 is_existing(按 platform+canonical_url 匹配) */
  async syncSubStatus() {
    try {
      const openid = await getApp().ensureLogin()
      const { listSubscriptions } = require('../../services/subscriptions')
      const subs = await listSubscriptions(openid)
      const keyOf = (s) => `${s.platform}|${s.canonical_url}`
      const subMap = new Map((subs || []).map((s) => [keyOf(s), s]))
      const changed = {}
      for (const r of this.data.results) {
        const sub = subMap.get(`${r.platform}|${r.canonical_url}`)
        const wantExisting = !!sub
        const wantSubId = sub ? sub.id : null
        const wantAnchorId = sub ? sub.anchor_id : r.anchor_id
        if (r.is_existing !== wantExisting || r.subscription_id !== wantSubId) {
          changed[`${r.platform}|${r.user_id}`] = {
            is_existing: wantExisting,
            subscription_id: wantSubId,
            anchor_id: wantAnchorId,
          }
        }
      }
      for (const key in changed) {
        const [platform, userId] = key.split('|')
        this.updateResult(platform, userId, changed[key])
      }
    } catch (err) {
      // 同步失败静默(保留现有状态)
    }
  },

  // P0-10: Tab 切换 = 纯本地筛选, 绝不重新触发搜索
  onFilterChange(e) {
    const platform = e.detail.value
    this.setData({ platform }, () => {
      this.applyFilter()
      // 不能把“该平台请求超时/受限”误报为“没有这个主播”。
      this.applySearchMeta({
        items: this.data.allResults,
        platform_status: this.data.platformStatus,
      })
    })
  },

  /** 按当前 Tab 从 allResults 筛选展示(P0-10: Tab 不改搜索语义) — 必须过 renderRows 才有 meta/platformLabel/用户 key 等 */
  applyFilter() {
    const all = this.data.allResults || []
    const filtered = this.data.platform === 'all'
      ? all
      : all.filter((r) => r.platform === this.data.platform)
    const results = this.renderRows(filtered)
    this.setData({ results })
  },

  onTopicTap(e) {
    // 当前后端没有“按内容标签推荐”接口；此处只保持清晰的 UI 选中状态，
    // 搜索结果仍严格由上方关键词和平台筛选决定。
    this.setData({ activeTopic: e.currentTarget.dataset.value })
  },

  onKeywordInput(e) {
    this.setData({ keyword: e.detail.value })
  },

  onUniversalInput(e) {
    if (this.data.mode === 'search') this.onKeywordInput(e)
    else this.onUrlInput(e)
  },

  onUniversalConfirm() {
    if (this.data.mode === 'search') this.onSearch()
    else this.onParse()
  },

  onClearKeyword() {
    this.setData({ keyword: '', results: [], allResults: [], platformStatus: {}, searchMsg: null, searchError: null, searchStatus: null, searchHint: '', showPasteLinkCta: false })
  },

  async onSearch() {
    const kw = this.data.keyword.trim()
    if (!kw) {
      this.setData({ searchError: '请输入主播名字' })
      return
    }
    // P0-10: 新 query 自动清空上一 query 的缓存; 旧响应不得污染新 query
    const sessionId = ++this._querySession
    this.setData({
      searching: true,
      searchError: null,
      searchMsg: null,
      searchStatus: null,
      searchHint: '',
      results: [],
      allResults: [],
      platformStatus: {},
      showPasteLinkCta: false,
    })
    try {
      const openid = await getApp().ensureLogin()
      // P0-10: 「全部」= 后端一次并发搜索所有平台(V3 聚合端点), 不依赖用户点过哪些 Tab
      // 单平台也走同一管道(过滤/去重/订阅/排名一致)
      const resp = await searchAnchors(openid, this.data.platform, kw, 15)

      if (sessionId !== this._querySession) {
        console.log('[search] stale response dropped (query changed)')
        return  // 旧请求返回 → 丢弃, 不污染新 query
      }

      // 保存完整结果集 + 平台状态
      this.setData({
        allResults: resp.items || [],
        platformStatus: resp.platform_status || {},
      })
      this.applyFilter()
      this.applySearchMeta(resp)
      this.setData({ searching: false })
    } catch (err) {
      if (sessionId !== this._querySession) return  // 过期错误也丢弃
      const msg = err.message || ''
      let searchError
      if (msg.includes('timeout') || msg.includes('超时') || msg.includes('网络')) {
        searchError = '搜索超时，请稍后再试'
      } else {
        searchError = '搜索服务暂时不可用，请稍后再试'
      }
      this.setData({ searching: false, searchError, showPasteLinkCta: true })
    }
  },

  /** 根据聚合响应设置提示信息(抖音 BLOCKED / EMPTY / SUCCESS) */
  applySearchMeta(resp) {
    const items = resp.items || []
    const ps = resp.platform_status || {}
    let searchMsg = ''
    let showPasteLinkCta = false
    const activeResultCount = this.data.platform === 'all'
      ? items.length
      : items.filter((item) => item.platform === this.data.platform).length

    const douyinPs = ps.douyin || {}
    const activePs = this.data.platform === 'all' ? null : (ps[this.data.platform] || {})

    if (activePs && activePs.status === 'TIMEOUT') {
      searchMsg = `${PLATFORM_LABEL[this.data.platform] || this.data.platform}搜索超时，暂时无法确认；请稍后重试`
      showPasteLinkCta = this.data.platform === 'douyin'
    } else if (activePs && activePs.status === 'BLOCKED') {
      searchMsg = activePs.hint || `${PLATFORM_LABEL[this.data.platform] || this.data.platform}搜索暂不可用`
      showPasteLinkCta = this.data.platform === 'douyin'
    } else if (activePs && activePs.status === 'PARSE_ERROR') {
      searchMsg = `${PLATFORM_LABEL[this.data.platform] || this.data.platform}搜索服务暂时不可用，请稍后重试`
      showPasteLinkCta = this.data.platform === 'douyin'
    } else if (douyinPs.status === 'BLOCKED') {
      // 抖音配置/上游不可用不能遮蔽其它平台的有效结果。
      if (items.length > 0) {
        searchMsg = `${douyinPs.hint || '抖音昵称搜索暂不可用'}；已显示其他平台结果，可粘贴抖音主页链接`
      } else {
        searchMsg = douyinPs.hint || '抖音昵称搜索暂不可用，请粘贴主页链接'
      }
      showPasteLinkCta = true
    } else if (this.data.platform !== 'all' && (activePs.status === 'EMPTY' || activePs.status === 'SUCCESS') && activeResultCount === 0) {
      searchMsg = '没有找到相关主播，换个名字试试'
      showPasteLinkCta = this.data.platform === 'douyin'
    } else if (items.length === 0) {
      searchMsg = '没有找到相关主播，换个名字试试'
      showPasteLinkCta = true
    } else if (this.data.platform === 'douyin' && douyinPs.status === 'BLOCKED') {
      searchMsg = '抖音需登录，请粘贴链接'
      showPasteLinkCta = true
    }

    this.setData({ searchMsg, showPasteLinkCta, searchStatus: resp.status || 'SUCCESS' })
  },

  /** 渲染搜索结果行(P0-11: V3 DTO — 后端已排序, 前端只展示) */
  renderRows(rows) {
    return (rows || []).map((r) => ({
      ...r,
      // 归一化: V3 DTO 用 platform_user_id, 前端内部统一 user_id
      user_id: r.platform_user_id || r.user_id,
      platformLabel: PLATFORM_LABEL[r.platform] || r.platform,
      // P0-11: follower_count 后端已融合(null 不覆盖); 无数据显式 '-'
      meta: `粉丝 ${this.formatFans(r.follower_count)}`,
      // P0-11: 已订阅 + 高匹配 → 视觉徽章
      matchLabel: r.match_type || '',
      isSubscribed: !!r.is_subscribed,
    }))
  },

  /**
   * 应用 V2 结构化搜索结果到 UI(兼容旧前端逻辑, V3 主路径走 onSearch)
   */
  applySearchResult(result) {
    if (!result) return
    const view = this.renderRows(result.items || [])
    let searchMsg = ''
    let showPasteLinkCta = false

    if (result.status === 'SUCCESS') {
      if (view.length === 0) {
        searchMsg = '没有找到相关主播，换个名字试试'
        showPasteLinkCta = true
      } else if (result.hint) {
        searchMsg = result.hint
      }
    } else if (result.status === 'BLOCKED') {
      searchMsg = result.hint || '该平台暂不支持按名字搜索'
      showPasteLinkCta = true
    } else if (result.status === 'TIMEOUT') {
      searchMsg = '搜索超时，建议「粘贴链接」'
      showPasteLinkCta = true
    } else if (result.status === 'PARSE_ERROR') {
      searchMsg = '解析失败，建议「粘贴链接」'
      showPasteLinkCta = true
    } else {
      searchMsg = '没有找到相关主播，换个名字试试'
      showPasteLinkCta = true
    }
    if (this.data.platform === 'douyin') showPasteLinkCta = true

    this.setData({
      results: view,
      searchMsg,
      searchError: null,
      searchHint: result.hint || '',
      searchStatus: result.status,
      showPasteLinkCta,
    })
  },

  /** "粘贴链接" CTA: 切到链接模式, 并把搜索词作为 hint 提示 */
  onPasteLinkCta() {
    this.setData({
      mode: 'link',
      showPasteLinkCta: false,
      parseError: null,
    })
    wx.showToast({
      title: '请粘贴抖音/虎牙/斗鱼/B站链接',
      icon: 'none',
      duration: 2200,
    })
  },

  /**
   * 渲染搜索结果(全局搜索聚合时会被调用两次: 快平台先渲染,抖音补搜后合并再渲染)
   * - 按粉丝数降序,大主播在前
   * - 去重(同一 user_id 只保留一次)
   */
  renderResults(raw) {
    const seen = {}
    const dedup = []
    for (const r of raw || []) {
      const key = `${r.platform}:${r.user_id}`
      if (!seen[key]) {
        seen[key] = true
        dedup.push(r)
      }
    }
    dedup.sort((a, b) => (b.fans || 0) - (a.fans || 0))
    const view = dedup.map((r) => ({
      ...r,
      platformLabel: PLATFORM_LABEL[r.platform] || r.platform,
      meta: `粉丝 ${this.formatFans(r.fans)}`,
    }))
    this.setData({ results: view, searchMsg: null, searchError: null })
  },

  formatFans(n) {
    if (!n) return '-'
    if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿'
    if (n >= 10000) return (n / 10000).toFixed(1) + '万'
    return String(n)
  },

  /**
   * 搜索结果订阅交互(§七 + UI-2.1A 单飞锁)
   * - 未订阅 → [订阅] 主 CTA → 订阅流程
   * - 已订阅 → ✓ 已订阅(状态展示) → 点击不取消
   * 关键: subscribePending 单飞锁 — 用户连点 N 次只发起 1 次 requestSubscribeMessage
   */
  async onToggleSubscribe(e) {
    const item = e.currentTarget.dataset.item
    if (!item) return
    // 防御: V3 返回 platform_user_id, 老/裸数据返回 user_id — 取并集
    const userId = item.user_id || item.platform_user_id
    if (item.is_subscribed || item.is_existing) {
      wx.showToast({ title: '已订阅，可在「我的订阅」管理', icon: 'none' })
      return
    }
    if (this._subscribePending) return // 单飞锁: 防重复触发
    this._subscribePending = true
    console.log('[subscribe] tap', userId)

    // 按钮进入「授权中…」Disabled(只锁当前行)
    this.setData({ subscribingId: userId })

    try {
      const openid = await getApp().ensureLogin()
      await this.confirmSubscribe(openid, {
        platform: item.platform,
        platform_user_id: item.platform_user_id || item.user_id,
        canonical_url: item.canonical_url,
        display_name: item.display_name,
        avatar: item.avatar,
      }, (sub) => {
        // 补全 anchor_id: 订阅成功后可解析到合法记录(验收: isSubscribed=true 有合法订阅)
        this.updateResult(item.platform, item.user_id, {
          is_existing: true,
          is_subscribed: true,
          subscription_id: sub.id,
          anchor_id: sub.anchor_id || item.anchor_id || null,
        })
      })
    } finally {
      this._subscribePending = false // 解锁
      this.setData({ subscribingId: null })
      console.log('[subscribe] unlock')
    }
  },

  /** 更新搜索结果中的某条(按 platform+user_id 双键匹配,防跨平台同名串状态) */
  updateResult(platform, userId, patch) {
    this.setData({
      results: this.data.results.map((r) =>
        r.platform === platform && r.user_id === userId ? { ...r, ...patch } : r
      ),
    })
  },

  /** 点击搜索结果行 → 查看主播(订阅只由按钮负责,互不干扰) */
  async goAnchorDetail(e) {
    const item = e.currentTarget.dataset.item
    if (!item) return
    // 有 anchor_id 直接进
    if (item.anchor_id) {
      wx.navigateTo({ url: `/pages/detail/index?id=${item.anchor_id}` })
      return
    }
    // 已订阅但搜索结果无 anchor_id(未入库/信息不完整)→ 从订阅列表解析真实 anchor_id
    // 验收: ✓ 已订阅 点击后不再出现「需先订阅」
    if (item.is_existing || item.subscription_id) {
      try {
        const openid = await getApp().ensureLogin()
        const { listSubscriptions } = require('../../services/subscriptions')
        const subs = await listSubscriptions(openid)
        // 按 platform + canonical_url 匹配订阅(不依赖昵称,不用内部 id)
        const match = (subs || []).find(
          (s) => s.platform === item.platform && s.canonical_url === item.canonical_url
        )
        if (match && match.anchor_id) {
          this.updateResult(item.platform, item.user_id, { anchor_id: match.anchor_id })
          wx.navigateTo({ url: `/pages/detail/index?id=${match.anchor_id}` })
          return
        }
      } catch (err) {
        // 解析失败 fall through 到下方提示
      }
    }
    wx.showToast({ title: '该主播需先订阅后查看详情', icon: 'none' })
  },

  // ── 链接模式 ──
  onUrlInput(e) {
    this.setData({ url: e.detail.value, parsed: null, parseError: null })
  },

  async onParse() {
    if (!this.data.url.trim()) {
      this.setData({ parseError: '请粘贴直播间或主页链接' })
      return
    }
    this.setData({ parsing: true, parseError: null })
    try {
      const parsed = await parseAnchor(this.data.url.trim())
      this.setData({ parsed, parsing: false })
    } catch (err) {
      this.setData({ parsing: false, parseError: err.message })
    }
  },

  async onConfirm() {
    const { parsed } = this.data
    if (!parsed) return
    if (this._subscribePending) return // 单飞锁(UI-2.1A)
    this._subscribePending = true
    this.setData({ parsing: true })
    try {
      const openid = await getApp().ensureLogin()
      await this.confirmSubscribe(openid, {
        platform: parsed.platform,
        platform_user_id: parsed.platform_user_id,
        canonical_url: parsed.canonical_url,
        display_name: parsed.display_name,
        avatar: parsed.avatar,
      })
    } finally {
      this._subscribePending = false
      this.setData({ parsing: false })
    }
  },

  /**
   * 统一订阅流程 — 严格串行状态机(UI-2.1A)
   *
   * IDLE → REQUESTING_PERMISSION(模板可用时) → RECORDING_EVIDENCE
   *      → CREATING_SUBSCRIPTION → SUCCESS → ✓ 已订阅
   *
   * 铁律:
   * 1. wx 授权只能由当前用户点击触发,不能后台重放。
   * 2. accept/reject/ban 原样 intake;无授权时后端将使用 IN_APP。
   * 3. grant 结果不阻断关注关系,订阅创建仍保持幂等。
   */
  async confirmSubscribe(openid, anchor, onSubscribed) {
    console.log('[subscribe] wx.requestSubscribeMessage start')
    const templateId = getApp().globalData.liveStartTemplateId

    // ── REQUESTING_PERMISSION: 仅模板已配置时由当前点击触发 ──
    let res = null
    if (templateId) {
      try {
        res = await new Promise((resolve) => {
          wx.requestSubscribeMessage({
            tmplIds: [templateId],
            success: (r) => { console.log('[subscribe] wx success', r.errMsg); resolve(r) },
            fail: (e) => { console.log('[subscribe] wx fail:', e.errMsg); resolve(null) },
          })
        })
      } catch (e) {
        console.log('[subscribe] wx exception:', e && e.errMsg)
        res = null
      }
    }

    let acceptCount = 0
    if (res) {
      const tmplResults = Object.keys(res).filter((k) => k !== 'errMsg')
      acceptCount = tmplResults.filter((k) => res[k] === 'accept').length
      console.log('[subscribe] permission result:', tmplResults.map((k) => res[k]).join(','))

      // 原样记录逐模板 evidence;失败不伪造额度,也不阻断 IN_APP 关注关系。
      try {
        await requestGrant(openid, res)
      } catch (e) {
        console.log('[subscribe] grant intake fail(不阻塞订阅):', e.message)
      }
    }

    // ── CREATING_SUBSCRIPTION: grant 不可用时由 Gate 3 路由到 IN_APP ──
    console.log('[subscribe] create subscription start')
    try {
      const sub = await subscribe(
        openid, anchor.platform, anchor.platform_user_id,
        anchor.canonical_url, anchor.display_name, anchor.avatar
      )
      console.log('[subscribe] create subscription success, id=', sub.id)
      if (onSubscribed) onSubscribed(sub)
      wx.showToast({
        title: acceptCount > 0 ? '订阅成功' : '订阅成功，已启用站内提醒',
        icon: acceptCount > 0 ? 'success' : 'none',
      })
    } catch (err) {
      console.log('[subscribe] create subscription fail:', err.message)
      wx.showToast({ title: err.message, icon: 'none' })
    }
  },
})
