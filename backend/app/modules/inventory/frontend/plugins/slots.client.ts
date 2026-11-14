import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // Home — low stock, expiring and expired lots (ADR 0040 widget).
  registerSlot('dashboard.attention', {
    id: 'inventory.dashboard.stockAlerts',
    labelKey: 'settings.widgets.catalog.inventory.stockAlerts.title',
    descriptionKey: 'settings.widgets.catalog.inventory.stockAlerts.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/StockAlertsPanel.vue')),
    permission: 'inventory.stock.read',
    order: 60
  })

  // Implants are recorded where the patient already is. The patient
  // record owns its tabs and knows nothing about stock (ADR 0041), and
  // the tab's context carries the patient — which is why this module
  // needs no patient picker and never calls the Patients API.
  //
  // Switch the Inventario App off and the tab goes with it.
  registerSlot('patient.detail.tabs', {
    id: 'inventory.patient.detail.tabs.implants',
    component: defineAsyncComponent(
      () => import('../components/patient/PatientImplantsTab.vue')
    ),
    tab: { value: 'implants', icon: 'i-lucide-bone' },
    labelKey: 'inventory.implants.title',
    permission: 'inventory.implants.read',
    order: 55
  })
})
