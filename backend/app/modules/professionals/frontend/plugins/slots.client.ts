import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // The caller's own professional details, under their profile. The host
  // page offers the slot and knows nothing of this module (ADR 0041); an
  // account with no profile here gets nothing (the card hides itself).
  registerSlot('settings.profile.sections', {
    id: 'professionals.settings.profile.mine',
    component: defineAsyncComponent(() => import('../components/settings/MyProfessionalCard.vue')),
    order: 10
  })
})
