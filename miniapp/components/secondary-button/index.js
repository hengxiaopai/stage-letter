Component({
  properties: { block: { type: Boolean, value: true } },
  methods: {
    onTap() { this.triggerEvent('tap') },
  },
})
