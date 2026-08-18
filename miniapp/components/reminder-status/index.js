Component({
  properties: {
    on: { type: Boolean, value: true },
  },
  methods: {
    onChange(e) { this.triggerEvent('change', { on: e.detail.value }) },
  },
})
