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

  // The two shortcuts in the agenda's bottom-right corner. Same slot
  // contract: the agenda owns the corner, this module owns what sits in
  // it and knows nothing of the page around it.
  registerSlot('agenda.calendar.subscribe', {
    id: 'calendar_feed.agenda.subscribe',
    labelKey: 'calendarFeed.subscribe.google.button',
    component: defineAsyncComponent(
      () => import('../components/agenda/CalendarSubscribeButtons.vue')
    ),
    order: 10,
    permission: 'calendar_feed.subscription.manage'
  })
})
