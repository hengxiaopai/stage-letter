const { getHistory } = require('../../services/notifications')
const { parseISO } = require('../../utils/time')

Page({
  data: { items: [], loading: true, error: null },

  onShow() {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 })
    }
    this.load()
  },

  async load() {
    try {
      const openid = await getApp().ensureLogin()
      const history = await getHistory(openid, 20)
      this.setData({
        items: (history.items || []).map((item) => ({
          ...item,
          title: `${item.display_name || '主播'} 开播了`,
          meta: this.formatTime(item.started_at),
        })),
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

  goDetail(e) {
    const id = e.currentTarget.dataset.id
    if (id) wx.navigateTo({ url: `/pages/detail/index?id=${id}` })
  },

  formatTime(iso) {
    if (!iso) return '刚刚'
    const timestamp = parseISO(iso)
    if (isNaN(timestamp)) return iso
    const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000))
    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes} 分钟前`
    if (minutes < 1440) return `${Math.floor(minutes / 60)} 小时前`
    return `${Math.floor(minutes / 1440)} 天前`
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
})
