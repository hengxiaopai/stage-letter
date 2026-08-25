Component({
  properties: {
    count: { type: Number, value: 0 },
    refreshing: { type: Boolean, value: false },
  },

  methods: {
    refresh() {
      if (!this.properties.refreshing) this.triggerEvent('refresh')
    },
  },
})
