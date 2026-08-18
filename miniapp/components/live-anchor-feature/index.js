Component({
  properties: {
    avatar: { type: String, value: '' },
    name: { type: String, value: '' },
    platform: { type: String, value: '' },
    platformLabel: { type: String, value: '' },
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
  },
  methods: {
    onTap() { this.triggerEvent('tap') },
  },
})
