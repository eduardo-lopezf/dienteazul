/**
 * Registers the issuer's SAT settings under /settings/billing/sat.
 */
import { registerSettingsPage } from '~~/app/composables/useSettingsRegistry'
import { PERMISSIONS } from '~~/app/config/permissions'

export default defineNuxtPlugin(() => {
  registerSettingsPage({
    path: 'sat',
    category: 'billing',
    labelKey: 'satCfdi.settings.title',
    descriptionKey: 'satCfdi.settings.description',
    icon: 'i-lucide-landmark',
    permission: PERMISSIONS.satCfdi.settingsRead,
    component: () => import('../components/settings/SatIssuerPage.vue'),
    searchKeywords: ['sat', 'cfdi', 'csd', 'sello digital', 'factura electrónica', 'factura electronica', 'rfc', 'régimen fiscal', 'regimen fiscal', 'facturama'],
    order: 50
  })
})
