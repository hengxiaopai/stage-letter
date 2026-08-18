Component({
  properties: {
    show: { type: Boolean, value: false },
    title: { type: String, value: '' },
    actions: { type: Array, value: [] },
  },
  methods: {
    onAction(e) { this.triggerEvent('action', { key: e.currentTarget.dataset.key }) },
    onClose() { this.triggerEvent('close') },
  },
})
