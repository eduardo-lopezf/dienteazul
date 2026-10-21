/**
 * Registers the odontogram's settings page on the host registry: the
 * clinic's eruption chronology, under Settings → Clinical.
 */
import { registerSettingsPage } from '~~/app/composables/useSettingsRegistry'

export default defineNuxtPlugin(() => {
  registerSettingsPage({
    path: 'eruption-chronology',
    category: 'clinical',
    labelKey: 'odontogram.eruption.settings.title',
    descriptionKey: 'odontogram.eruption.settings.description',
    icon: 'i-lucide-baby',
    permission: 'admin.clinic.write',
    component: () => import('../components/settings/EruptionChronologyPage.vue'),
    searchKeywords: ['erupcion', 'eruption', 'cronologia', 'chronology', 'odontopediatria', 'dentición', 'dentition'],
    order: 40
  })
})
