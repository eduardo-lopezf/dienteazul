import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'
import { PERMISSIONS } from '~~/app/config/permissions'

export default defineNuxtPlugin(() => {
  // A button on the professional's card in the directory. The directory is
  // a clinic's screen, so an individual practice never sees it (ADR 0041).
  registerSlot('professional.profile.actions', {
    id: 'commissions.professional.profile.actions',
    component: defineAsyncComponent(
      () => import('../components/professionals/ProfessionalCommissionsButton.vue')
    ),
    order: 10,
    permission: PERMISSIONS.commissions.agreementWrite
  })
})
