/**
 * Registers the host-owned settings pages with the registry. Modules
 * register their own pages via their own client plugins (same pattern
 * as the existing slot system).
 */
import {
  registerSettingsPage,
  registerGettingStartedRule
} from '~/composables/useSettingsRegistry'

export default defineNuxtPlugin(() => {
  // ---- General -------------------------------------------------------
  registerSettingsPage({
    path: 'clinic',
    category: 'general',
    labelKey: 'settings.clinicInfo',
    descriptionKey: 'settings.clinicInfoDescription',
    icon: 'i-lucide-building-2',
    permission: 'admin.clinic.read',
    component: () => import('~/components/settings/pages/ClinicInfoPage.vue'),
    searchKeywords: ['clinica', 'clinic', 'cif', 'nif', 'razon social', 'direccion', 'address', 'tax id'],
    order: 10
  })
  // The standard the clinical record refers to: printed by more than one App.
  registerSettingsPage({
    path: 'record-regulation',
    category: 'general',
    labelKey: 'regulation.title',
    descriptionKey: 'regulation.description',
    icon: 'i-lucide-scale',
    permission: 'admin.clinic.read',
    component: () => import('~/components/settings/pages/RecordRegulationPage.vue'),
    searchKeywords: ['normativa', 'norma', 'nom', 'nom-004', 'regulation', 'expediente', 'ley'],
    order: 30
  })
  // What heads every printed document, whichever App prints it (ADR 0046).
  registerSettingsPage({
    path: 'letterheads',
    category: 'general',
    labelKey: 'letterhead.title',
    descriptionKey: 'letterhead.description',
    icon: 'i-lucide-stamp',
    permission: 'admin.clinic.read',
    component: () => import('~/components/settings/pages/LetterheadsPage.vue'),
    searchKeywords: ['membrete', 'letterhead', 'logotipo', 'logo', 'encabezado', 'cédula', 'pdf'],
    order: 20
  })

  // ---- Workspace -----------------------------------------------------
  registerSettingsPage({
    path: 'cabinets',
    category: 'workspace',
    labelKey: 'settings.cabinets',
    descriptionKey: 'settings.cabinetsDescription',
    icon: 'i-lucide-door-open',
    component: () => import('~/components/settings/pages/CabinetsPage.vue'),
    searchKeywords: ['gabinete', 'sala', 'box', 'consulta', 'cabinet', 'room'],
    order: 10
  })

  // ---- People --------------------------------------------------------
  registerSettingsPage({
    path: 'users',
    category: 'people',
    labelKey: 'settings.users',
    descriptionKey: 'settings.usersDescription',
    icon: 'i-lucide-users',
    permission: 'admin.users.read',
    component: () => import('~/components/settings/pages/UsersPage.vue'),
    searchKeywords: ['usuarios', 'users', 'roles', 'permisos', 'staff', 'equipo', 'team'],
    order: 10
  })

  // ---- Clinical (stub) ----------------------------------------------
  registerSettingsPage({
    path: 'catalog',
    category: 'clinical',
    labelKey: 'catalog.title',
    descriptionKey: 'catalog.description',
    icon: 'i-lucide-list',
    permission: 'admin.clinic.read',
    to: '/settings/catalog',
    searchKeywords: ['catalogo', 'catalog', 'tratamientos', 'treatments', 'precios', 'prices'],
    order: 10
  })

  // ---- Billing (module-provided pages) ------------------------------
  registerSettingsPage({
    path: 'invoice-series',
    category: 'billing',
    labelKey: 'invoiceSeries.title',
    descriptionKey: 'invoiceSeries.description',
    icon: 'i-lucide-hash',
    permission: 'admin.clinic.read',
    to: '/settings/invoice-series',
    searchKeywords: ['series', 'numeracion', 'invoice', 'numbering', 'factura'],
    order: 10
  })
  registerSettingsPage({
    path: 'vat-types',
    category: 'billing',
    labelKey: 'vatTypes.title',
    descriptionKey: 'vatTypes.description',
    icon: 'i-lucide-percent',
    permission: 'admin.clinic.read',
    to: '/settings/vat-types',
    searchKeywords: ['iva', 'vat', 'impuesto', 'tax'],
    order: 20
  })

  // ---- Communications (module-provided pages) ----------------------
  registerSettingsPage({
    path: 'notifications',
    category: 'communications',
    labelKey: 'notifications.title',
    descriptionKey: 'notifications.description',
    icon: 'i-lucide-mail',
    permission: 'admin.clinic.read',
    to: '/settings/notifications',
    searchKeywords: ['email', 'smtp', 'plantillas', 'templates', 'notificaciones', 'notifications'],
    order: 10
  })

  // ---- Privacy -------------------------------------------------------
  registerSettingsPage({
    path: 'subject-requests',
    category: 'privacy',
    labelKey: 'privacy.subjectRequest',
    descriptionKey: 'privacy.subjectRequestDescription',
    icon: 'i-lucide-shield-check',
    permission: 'privacy.subject.read',
    component: () => import('~/components/settings/pages/PrivacyPage.vue'),
    searchKeywords: [
      'privacidad', 'privacy', 'arco', 'gdpr', 'rgpd', 'lfpdppp',
      'exportar', 'export', 'portabilidad', 'supresion', 'borrar',
      'derechos', 'rights', 'erasure'
    ],
    order: 10
  })

  // ---- Apps (links to the /settings/apps, /widgets and /apis pages) ---
  registerSettingsPage({
    path: 'manage',
    category: 'modules',
    labelKey: 'settings.modules.title',
    descriptionKey: 'settings.modules.description',
    icon: 'i-lucide-blocks',
    permission: 'admin.clinic.read',
    to: '/settings/apps',
    searchKeywords: ['app', 'apps', 'aplicacion', 'modulo', 'module', 'plugin', 'habilitar', 'enable'],
    order: 10
  })

  // The workspace App's own settings, starting with the home page (ADR 0043).
  registerSettingsPage({
    path: 'workspace-app',
    category: 'modules',
    labelKey: 'settings.apps.catalog.workspace.title',
    descriptionKey: 'settings.home.workspaceCard',
    icon: 'i-lucide-house',
    permission: 'admin.clinic.read',
    to: '/settings/apps/workspace',
    searchKeywords: ['espacio de trabajo', 'workspace', 'inicio', 'home', 'dashboard', 'widget', 'personalizar', 'customize', 'orden', 'order', 'ocultar', 'hide'],
    order: 15
  })

  // Siblings of Apps over the same catalog (ADR 0040), each its own page.
  registerSettingsPage({
    path: 'widgets',
    category: 'modules',
    labelKey: 'settings.widgets.title',
    descriptionKey: 'settings.widgets.description',
    icon: 'i-lucide-layout-dashboard',
    permission: 'admin.clinic.read',
    to: '/settings/widgets',
    searchKeywords: ['widget', 'widgets', 'tarjeta', 'card', 'ejemplo', 'example'],
    order: 20
  })

  registerSettingsPage({
    path: 'apis',
    category: 'modules',
    labelKey: 'settings.apis.title',
    descriptionKey: 'settings.apis.description',
    icon: 'i-lucide-plug',
    permission: 'admin.clinic.read',
    to: '/settings/apis',
    searchKeywords: ['api', 'apis', 'integracion', 'integration', 'google', 'calendar', 'conectar', 'connect'],
    order: 30
  })

  // ---- Account -------------------------------------------------------
  registerSettingsPage({
    path: 'profile',
    category: 'account',
    labelKey: 'settings.profile',
    descriptionKey: 'settings.profileDescription',
    icon: 'i-lucide-user',
    component: () => import('~/components/settings/pages/ProfilePage.vue'),
    searchKeywords: ['perfil', 'profile', 'cuenta', 'account'],
    order: 10
  })
  registerSettingsPage({
    path: 'language',
    category: 'account',
    labelKey: 'settings.language',
    descriptionKey: 'settings.languageDescription',
    icon: 'i-lucide-languages',
    component: () => import('~/components/settings/pages/LanguagePage.vue'),
    searchKeywords: ['idioma', 'language', 'locale', 'lang'],
    order: 20
  })
  // A professional's own letterhead. Open to every account: the page says
  // so when the account is not one of the clinic's professionals.
  registerSettingsPage({
    path: 'my-letterhead',
    category: 'account',
    labelKey: 'letterhead.mine.title',
    descriptionKey: 'letterhead.mine.description',
    icon: 'i-lucide-stamp',
    component: () => import('~/components/settings/pages/MyLetterheadPage.vue'),
    searchKeywords: ['membrete', 'letterhead', 'logotipo', 'logo', 'encabezado', 'cédula'],
    order: 25
  })
  // Of the whole account, so only whoever administers it sees it.
  registerSettingsPage({
    path: 'storage',
    category: 'account',
    labelKey: 'settings.storage.title',
    descriptionKey: 'settings.storage.description',
    icon: 'i-lucide-hard-drive',
    permission: 'admin.clinic.read',
    component: () => import('~/components/settings/pages/StorageUsagePage.vue'),
    searchKeywords: ['espacio', 'disco', 'almacenamiento', 'storage', 'disk', 'space', 'base de datos', 'database'],
    order: 30
  })

  // ---- Onboarding rules ---------------------------------------------
  // Rules read state lazily inside the predicate to stay reactive
  // across login transitions.
  registerGettingStartedRule({
    id: 'clinic-info-incomplete',
    labelKey: 'settings.onboarding.items.clinicInfo.label',
    descriptionKey: 'settings.onboarding.items.clinicInfo.description',
    icon: 'i-lucide-building-2',
    to: '/settings/general/clinic',
    severity: 'warning',
    when: () => {
      const clinic = useClinic()
      const c = clinic.currentClinic.value
      if (!c) return false
      return !c.name || !c.tax_id || !c.address?.street
    }
  })

  registerGettingStartedRule({
    id: 'no-cabinets',
    labelKey: 'settings.onboarding.items.cabinets.label',
    descriptionKey: 'settings.onboarding.items.cabinets.description',
    icon: 'i-lucide-door-open',
    to: '/settings/workspace/cabinets',
    severity: 'info',
    when: () => {
      const clinic = useClinic()
      return clinic.cabinets.value.length === 0
    }
  })
})
