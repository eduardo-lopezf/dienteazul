// Treatment-plan slot registrations.
//
// Clinical-notes-related slots (patient.timeline.treatments,
// patient.summary.feed, odontogram.diagnosis.sidebar,
// odontogram.condition.actions) are owned by the ``clinical_notes``
// module since issue #60.
import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  const { can } = usePermissions()

  // Home — plans waiting on the patient's answer (ADR 0040 widget).
  registerSlot('dashboard.attention', {
    id: 'treatment_plan.dashboard.awaitingPlans',
    labelKey: 'settings.widgets.catalog.treatments.awaitingPlans.title',
    descriptionKey: 'settings.widgets.catalog.treatments.awaitingPlans.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/AwaitingPlansPanel.vue')),
    order: 30,
    permission: 'treatment_plan.plans.read'
  })

  // Patient Resumen — active-plan smart card. The patients module
  // exposes the ``patient.summary.cards`` slot and never imports
  // anything from treatment_plan; this registration is the contract.
  registerSlot('patient.summary.cards', {
    id: 'treatment_plan.patient.summary.cards.plan',
    component: defineAsyncComponent(
      () => import('../components/summary/PlanCard.vue')
    ),
    order: 10,
    permission: 'treatment_plan.plans.read'
  })

  // Patient record — the Clínico tab (diagnosis, plans, appointments).
  // None of it is `patients`' own, so the tab is contributed here and the
  // patient page hosts it without importing this module. Shown to anyone
  // who can read the chart *or* the plans, as before the move.
  registerSlot('patient.detail.tabs', {
    id: 'treatment_plan.patient.detail.tabs.clinical',
    component: defineAsyncComponent(
      () => import('../components/patient/PatientClinicalTabEntry.vue')
    ),
    tab: { value: 'clinical', icon: 'i-lucide-stethoscope' },
    labelKey: 'patientDetail.tabs.clinical',
    condition: () => can('odontogram.read') || can('treatment_plan.plans.read'),
    order: 30
  })
})
