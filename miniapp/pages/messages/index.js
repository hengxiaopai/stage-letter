const { getHistory } = require('../../services/notifications')
const { parseISO } = require('../../utils/time')

const FILTERS = [
  { label: '全部', value: 'all' },
  { label: '已发送', value: 'sent' },
  { label: '未送达', value: 'failed' },
  { label: '重试中', value: 'retry' },
  { label: '待确认', value: 'ambiguous' },
]

function deliveryView(item) {
  const state = String(item.state || '')
  const channel = String(item.channel || '')
  let kind = 'failed'
  let label = '未送达'
  let detail = '本次通知未送达'
  if (channel === 'IN_APP') {
    kind = 'sent'
    label = '站内记录'
    detail = '已记录到站内通知'
  } else if (state === 'SENT') {
    kind = 'sent'
    label = '已发送'
    detail = '微信服务通知已提交'
  } else if (state === 'PENDING' || state === 'IN_FLIGHT' || state === 'WAITING_RETRY') {
    kind = 'retry'
    label = '重试中'
    detail = '网络波动，将自动重试'
  } else if (state === 'WAITING_AUTH') {
    detail = '当前没有可用的订阅消息授权'
  } else if (state === 'BLOCKED_CONFIG') {
    detail = '提醒配置暂不可用'
  } else if (state === 'AMBIGUOUS') {
    kind = 'ambiguous'
    label = '结果待确认'
    detail = '投递结果暂时无法确认'
  }
  return {
    ...item,
    kind,
    label,
    detail,
    title: '开播提醒',
    meta: item.sent_at || item.created_at || item.started_at,
  }
}

Page({
  data: { items: [], visibleItems: [], filters: FILTERS, activeFilter: 'all', loading: true, error: null },

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
      const items = (history.items || []).map((item) => {
        const view = deliveryView(item)
        return { ...view, timeLabel: this.formatTime(view.meta) }
      })
      this.setData({ items, loading: false, error: null }, () => this.applyFilter())
    } catch (err) {
      this.setData({ loading: false, error: 'load_failed' })
    }
  },

  retryLoad() {
    this.setData({ loading: true, error: null })
    this.load()
  },

  onFilterChange(e) {
    this.setData({ activeFilter: e.detail.value }, () => this.applyFilter())
  },

  applyFilter() {
    const { activeFilter, items } = this.data
    this.setData({ visibleItems: activeFilter === 'all' ? items : items.filter((item) => item.kind === activeFilter) })
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
