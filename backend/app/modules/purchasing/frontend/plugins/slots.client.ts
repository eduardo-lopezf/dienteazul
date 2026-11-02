import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // The Existencias screen owns its header and knows nothing about
  // purchase orders (ADR 0041). The dependency runs one way — purchasing
  // reads the inventory, never the reverse — so the way into Compras is
  // contributed from here. Disable this module and the button goes with
  // it, instead of leaving a dead link on somebody else's screen.
  registerSlot('inventory.stock.actions', {
    id: 'purchasing.inventory.stock.orders',
    labelKey: 'purchasing.orders.open',
    component: defineAsyncComponent(() => import('../components/PurchasingStockAction.vue')),
    order: 10,
    permission: 'purchasing.orders.read'
  })
})
