import { defineAsyncComponent } from 'vue'
import { registerSlot } from '~~/app/composables/useModuleSlots'

/**
 * Slot registrations for the `notifications` module.
 *
 * The patient WhatsApp conversation thread (channel-agnostic comms log +
 * reply box) renders as a card on the patient summary. The slot registry is
 * the only contract — no host import.
 */
export default defineNuxtPlugin(() => {
  // Home — messages that never reached the patient (ADR 0040 widget).
  registerSlot('dashboard.attention', {
    id: 'notifications.dashboard.failedMessages',
    labelKey: 'settings.widgets.catalog.communications.failedMessages.title',
    descriptionKey: 'settings.widgets.catalog.communications.failedMessages.summary',
    widget: true,
    component: defineAsyncComponent(() => import('../components/home/FailedMessagesPanel.vue')),
    permission: 'notifications.logs.read',
    order: 50
  })

  registerSlot('patient.summary.cards', {
    id: 'notifications.patient.conversation',
    component: defineAsyncComponent(() => import('../components/ConversationThread.vue')),
    permission: 'notifications.logs.read',
    order: 60
  })
})
