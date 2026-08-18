Component({
  properties: {
    items: { type: Array, value: [] },
    active: { type: String, value: 'all' },
  },
  methods: {
    onTap(e) { this.triggerEvent('change', { value: e.currentTarget.dataset.value }) },
  },
})
