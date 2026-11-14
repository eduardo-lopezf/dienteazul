import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // Each tile reads another App's figures: shown only while it runs (ADR 0037).
  const { on } = useReportApps()

  registerSlot('dashboard.hero', {
    id: 'reports.dashboard.overdueHero',
    labelKey: 'settings.home.labels.overdueHero',
    descriptionKey: 'settings.widgets.catalog.reports.overdueHero.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/OverdueHeroTile.vue')),
    order: 30,
    permission: 'reports.billing.read',
    condition: () => on('billing')
  })

  registerSlot('dashboard.attention', {
    id: 'reports.dashboard.overduePanel',
    labelKey: 'settings.home.labels.overduePanel',
    descriptionKey: 'settings.widgets.catalog.reports.overduePanel.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/OverdueInvoicesPanel.vue')),
    order: 20,
    permission: 'reports.billing.read',
    condition: () => on('billing')
  })

  registerSlot('dashboard.activity', {
    id: 'reports.dashboard.weekGlance',
    labelKey: 'settings.home.labels.weekGlance',
    descriptionKey: 'settings.widgets.catalog.reports.weekGlance.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/WeekGlancePanel.vue')),
    order: 20,
    permission: 'reports.billing.read',
    condition: () => on('agenda', 'billing')
  })
})
