import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

export default defineNuxtPlugin(() => {
  // The APIs page belongs to the host and knows nothing about this
  // module (ADR 0041). Switch the App off and the card goes with it.
  registerSlot('settings.apis.sections', {
    id: 'calendar_feed.settings.apis.subscription',
    labelKey: 'settings.apis.catalog.ics_feed.title',
    descriptionKey: 'settings.apis.catalog.ics_feed.summary',
    component: defineAsyncComponent(() => import('../components/settings/CalendarFeedCard.vue')),
    order: 10,
    permission: 'calendar_feed.subscription.manage'
  })
})
