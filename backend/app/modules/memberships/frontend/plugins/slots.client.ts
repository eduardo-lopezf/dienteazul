import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'
import { PERMISSIONS } from '~~/app/config/permissions'

export default defineNuxtPlugin(() => {
  // The patient's membership, on the patient record. The record owns its
  // tabs and knows nothing about memberships (ADR 0041); the patient comes
  // in the slot's context. With the module off for the clinic its
  // permissions are not granted, and the tab goes with them (ADR 0066).
  registerSlot('patient.detail.tabs', {
    id: 'memberships.patient.detail.tabs.membership',
    component: defineAsyncComponent(
      () => import('../components/patient/PatientMembershipTab.vue')
    ),
    tab: { value: 'membership', icon: 'i-lucide-badge-percent' },
    labelKey: 'memberships.tab',
    permission: PERMISSIONS.memberships.membershipRead,
    order: 45
  })
})
