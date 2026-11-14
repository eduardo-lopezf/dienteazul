import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // Home — each professional's workload. A clinic only: an individual
  // practice has a single professional (ADR 0040 widget).
  registerSlot('dashboard.activity', {
    id: 'professionals.dashboard.teamWorkload',
    labelKey: 'settings.widgets.catalog.professionals.teamWorkload.title',
    descriptionKey: 'settings.widgets.catalog.professionals.teamWorkload.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/TeamWorkloadPanel.vue')),
    order: 30,
    permission: 'professionals.read',
    tiers: ['clinic']
  })

  // The caller's own professional details, under their profile. The host
  // page offers the slot and knows nothing of this module (ADR 0041); an
  // account with no profile here gets nothing (the card hides itself).
  registerSlot('settings.profile.sections', {
    id: 'professionals.settings.profile.mine',
    component: defineAsyncComponent(() => import('../components/settings/MyProfessionalCard.vue')),
    order: 10
  })
})
