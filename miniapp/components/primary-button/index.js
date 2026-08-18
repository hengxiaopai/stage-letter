Component({
  properties: {
    loading: { type: Boolean, value: false },
    disabled: { type: Boolean, value: false },
    block: { type: Boolean, value: true },
  },
  methods: {
    onTap() { if (!this.data.disabled) this.triggerEvent('tap') },
  },
})
