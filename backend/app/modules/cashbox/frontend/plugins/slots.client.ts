import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `cashbox` module.
 *
 * One tab on the host's Finanzas page. Ordered after Cobros: the till is
 * read in the context of what was collected, and reception opens this
 * screen at the end of the day rather than through it.
 */
export default defineNuxtPlugin(() => {
  // Resumen tile: the days nobody counted. `pending_days` was only ever
  // visible to somebody who opened this tab and read the period card, so an
  // abandoned arqueo was found when a discrepancy was hunted.
  registerSlot('finance.summary', {
    id: 'cashbox.finance.summary.till',
    component: defineAsyncComponent(() => import('../components/finance/SummaryTill.vue')),
    permission: 'cashbox.closing.read',
    order: 30
  })

  // Home — the same tile: an uncounted day is found the next morning,
  // not when a discrepancy is hunted (ADR 0040 widget).
  registerSlot('dashboard.hero', {
    id: 'cashbox.dashboard.till',
    labelKey: 'settings.widgets.catalog.cash.till.title',
    descriptionKey: 'settings.widgets.catalog.cash.till.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/finance/SummaryTill.vue')),
    permission: 'cashbox.closing.read',
    order: 40
  })

  registerSlot('finance.tabs', {
    id: 'cashbox.finance.tabs',
    component: defineAsyncComponent(() => import('../components/finance/CashboxTab.vue')),
    permission: 'cashbox.movement.read',
    labelKey: 'cashbox.nav.cashbox',
    order: 15
  })
})
