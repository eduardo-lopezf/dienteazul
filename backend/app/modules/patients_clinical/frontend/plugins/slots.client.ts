import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the ``patients_clinical`` module.
 *
 * The patients module exposes ``patient.summary.cards`` (Resumen grid)
 * and ``patient.header.alerts`` (sticky header). patients_clinical
 * contributes its medical-history card and inline alert chips without
 * either side importing the other.
 */
export default defineNuxtPlugin(() => {
  registerSlot('patient.summary.cards', {
    id: 'patients_clinical.patient.summary.cards.medical',
    labelKey: 'settings.widgets.catalog.patients.medicalHistory.title',
    descriptionKey: 'settings.widgets.catalog.patients.medicalHistory.summary',
    widget: true,
    component: defineAsyncComponent(
      () => import('../components/summary/MedicalHistoryCard.vue')
    ),
    order: 50,
    permission: 'patients_clinical.medical.read'
  })

  // The patient's ASA physical status: the current class, and where a
  // clinician assesses again.
  registerSlot('patient.summary.cards', {
    id: 'patients_clinical.patient.summary.cards.asa',
    component: defineAsyncComponent(
      () => import('../components/summary/AsaCard.vue')
    ),
    order: 55,
    permission: 'patients_clinical.medical.read'
  })

  // While an appointment is booked: the patient is ASA III or IV.
  registerSlot('appointment.patient.alerts', {
    id: 'patients_clinical.appointment.patient.alerts.asa',
    component: defineAsyncComponent(
      () => import('../components/appointment/AppointmentAsaNotice.vue')
    ),
    order: 10,
    // The class alone is `asa.read`; the component adds the clinical
    // detail only for who may read the history.
    permission: 'patients_clinical.asa.read'
  })

  // The health questionnaire the patient answers at a visit.
  registerSlot('patient.detail.tabs', {
    id: 'patients_clinical.patient.detail.tabs.questionnaire',
    component: defineAsyncComponent(
      () => import('../components/questionnaire/PatientQuestionnairesTab.vue')
    ),
    tab: { value: 'questionnaire', icon: 'i-lucide-clipboard-list' },
    labelKey: 'healthQuestionnaire.title',
    permission: 'patients_clinical.medical.read',
    order: 40
  })

  registerSlot('patient.header.alerts', {
    id: 'patients_clinical.patient.header.alerts',
    labelKey: 'settings.widgets.catalog.patients.alerts.title',
    descriptionKey: 'settings.widgets.catalog.patients.alerts.summary',
    widget: true,
    component: defineAsyncComponent(
      () => import('../components/header/PatientHeaderAlertsChips.vue')
    ),
    order: 10,
    permission: 'patients_clinical.medical.read'
  })
})
