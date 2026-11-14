import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // Home — letters written and never signed (ADR 0040 widget).
  registerSlot('dashboard.attention', {
    id: 'consents.dashboard.unsigned',
    labelKey: 'settings.widgets.catalog.clinical_record.unsignedConsents.title',
    descriptionKey: 'settings.widgets.catalog.clinical_record.unsignedConsents.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/UnsignedConsentsPanel.vue')),
    permission: 'consents.read',
    order: 45
  })

  // Patient record — the Consentimientos tab. `patients` hosts the tab
  // strip and never imports this module (ADR 0041).
  registerSlot('patient.detail.tabs', {
    id: 'consents.patient.detail.tabs.consents',
    component: defineAsyncComponent(
      () => import('../components/consents/PatientConsentsTab.vue')
    ),
    tab: { value: 'consents', icon: 'i-lucide-file-signature' },
    labelKey: 'consents.title',
    permission: 'consents.read',
    order: 45
  })
})
