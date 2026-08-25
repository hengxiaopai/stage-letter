Component({
  properties: {
    on: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
  },
  methods: {
    onChange(e) { this.triggerEvent('change', { on: e.detail.value }) },
  },
})
