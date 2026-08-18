Component({
  properties: {
    title: { type: String, value: '' },
    meta: { type: String, value: '' },
    kind: { type: String, value: 'sent' }, // sent | inapp | fail
    label: { type: String, value: '' },
  },
})
