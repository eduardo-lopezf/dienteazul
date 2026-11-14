import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `budget` module.
 */
export default defineNuxtPlugin(() => {
  const { can } = usePermissions()

  // Home — budgets awaiting acceptance that lapse within a week
  // (ADR 0040 widget).
  registerSlot('dashboard.attention', {
    id: 'budget.dashboard.expiring',
    labelKey: 'settings.widgets.catalog.budgets_payments.expiringBudgets.title',
    descriptionKey: 'settings.widgets.catalog.budgets_payments.expiringBudgets.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/ExpiringBudgetsPanel.vue')),
    permission: 'budget.read',
    order: 40
  })

  // Tab of the host's Finanzas page. The host owns the page and the
  // sidebar entry; this module owns its own list and never learns about
  // its sibling tabs. Uninstalling the module removes the tab.
  registerSlot('finance.tabs', {
    id: 'budget.finance.tabs',
    component: defineAsyncComponent(() => import('../components/finance/BudgetsTab.vue')),
    permission: 'budget.read',
    labelKey: 'nav.budgets',
    order: 20
  })

  // Patient record — the Administración tab. Budgets are this module's;
  // invoices, payments and documents arrive through the
  // `patient.detail.administracion.*` slots, so this module never learns
  // about the ones that depend on it.
  registerSlot('patient.detail.tabs', {
    id: 'budget.patient.detail.tabs.administration',
    component: defineAsyncComponent(
      () => import('../components/patient/PatientAdministrationTabEntry.vue')
    ),
    tab: { value: 'administration', icon: 'i-lucide-briefcase' },
    labelKey: 'patientDetail.tabs.administration',
    condition: () => can('budget.read') || can('billing.read'),
    order: 40
  })
})
