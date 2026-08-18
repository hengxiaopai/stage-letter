Component({
  properties: {
    state: { type: String, value: 'off' },
    text: { type: String, value: '' },
  },
  data: { cls: 'st-off' },
  observers: {
    state(s) { this.setData({ cls: 'st-' + s }) },
  },
})
