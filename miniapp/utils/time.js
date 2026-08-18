// utils/time.js — 时间工具(兼容小程序 JSCore 的 ISO 解析差异)
//
// 背景: 部分小程序基础库/真机 JSCore 对 ISO 字符串
//   '2026-08-13T04:09:26.178823Z'(6 位毫秒)解析会产生错误时间戳,
//   导致"已播 219152 小时"这类错误。这里统一用正则手动解析,不依赖 new Date(iso)。

/** 手动解析 ISO → UTC 毫秒(不依赖 new Date 的解析行为) */
function parseISO(iso) {
  if (!iso) return NaN
  if (typeof iso === 'number') return iso
  const m = String(iso).match(
    /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$/
  )
  if (!m) return NaN
  const [, y, mo, d, h, mi, s, ms, tz] = m
  let t = Date.UTC(+y, +mo - 1, +d, +h, +mi, +s, +(ms || '').slice(0, 3) || 0)
  if (tz && tz !== 'Z') {
    const sign = tz[0] === '-' ? -1 : 1
    const hm = String(tz).replace(':', '').slice(1)
    t -= sign * (parseInt(hm.slice(0, 2), 10) * 60 + parseInt(hm.slice(2) || 0, 10)) * 60000
  }
  return t
}

/** 时间格式化: 今天只显示 HH:mm,跨天显示 MM-DD HH:mm */
function fmtSmart(iso) {
  const t = parseISO(iso)
  if (isNaN(t)) return ''
  const d = new Date(t)
  const p = (n) => (n < 10 ? '0' + n : '' + n)
  const hm = `${p(d.getHours())}:${p(d.getMinutes())}`
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  return sameDay ? hm : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${hm}`
}

/** HH:mm(不带日期) */
function fmtHM(iso) {
  const t = parseISO(iso)
  if (isNaN(t)) return ''
  const d = new Date(t)
  const p = (n) => (n < 10 ? '0' + n : '' + n)
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 已播时长: 8 小时 30 分 / 45 分钟 / 刚刚开播 */
function fmtDur(iso) {
  const start = parseISO(iso)
  if (isNaN(start)) return ''
  const mins = Math.floor((Date.now() - start) / 60000)
  if (mins < 0) return '刚刚开播'
  if (mins < 1) return '刚刚开播'
  if (mins < 60) return `已播 ${mins} 分钟`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m > 0 ? `已播 ${h} 小时 ${m} 分` : `已播 ${h} 小时`
}

module.exports = { parseISO, fmtSmart, fmtHM, fmtDur }
