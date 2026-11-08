import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'
import { PERMISSIONS } from '~~/app/config/permissions'

/**
 * Slot registrations for the `sat_cfdi` module.
 */
export default defineNuxtPlugin(() => {
  // Patient record → Administración → Facturas, above the invoices: the
  // fiscal profile of the patient's billing RFC. The component shows
  // nothing outside Mexican clinics.
  registerSlot('patient.detail.administracion.billing', {
    id: 'sat_cfdi.patient.detail.administracion.billing',
    component: defineAsyncComponent(() => import('../components/patient/PatientFiscalProfile.vue')),
    permission: PERMISSIONS.satCfdi.cfdiRead,
    order: 5
  })
})
