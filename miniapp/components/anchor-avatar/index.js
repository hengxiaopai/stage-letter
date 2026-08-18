Component({
  properties: {
    src: { type: String, value: '' },
    name: { type: String, value: '' },
    size: { type: String, value: 'md' },
  },
  data: { initial: '?', px: '44px' },
  observers: {
    name(n) { if (n) this.setData({ initial: n[0] }) },
    size(s) {
      const map = { sm: '36px', md: '44px', lg: '56px' }
      this.setData({ px: map[s] || '44px' })
    },
  },
})
