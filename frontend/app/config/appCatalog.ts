/**
 * How each App of the catalog (`backend/apps.json`) presents itself in
 * Settings → Apps: the icon that stands for it, and the page where it is
 * configured, when it has one.
 *
 * Catalog names are code; this is the presentation the host adds to
 * them, next to their title and summary in `settings.apps.catalog`. An
 * App without a row here falls back to a generic icon and offers no
 * "Configure" link.
 */
export interface AppAction {
  /** i18n key of the button's label. */
  labelKey: string
  icon: string
  to: string
  /** Shown only to who holds it (`config/permissions.ts`). */
  permission?: string
}

export interface AppPresentation {
  icon: string
  /** The App's own settings page. Offered only while the App is enabled. */
  settingsPath?: string
  /** What the App is used for, one button each on its card. Offered only
   *  while the App is enabled, like its settings page. */
  actions?: AppAction[]
}

export const APP_CATALOG: Record<string, AppPresentation> = {
  workspace: { icon: 'i-lucide-layout-dashboard', settingsPath: '/settings/apps/workspace' },
  agenda: { icon: 'i-lucide-calendar-days' },
  calendar_sync: { icon: 'i-lucide-calendar-sync' },
  patients: { icon: 'i-lucide-users' },
  recalls: { icon: 'i-lucide-bell-ring' },
  treatments: { icon: 'i-lucide-clipboard-list', settingsPath: '/settings/apps/treatments' },
  budgets_payments: { icon: 'i-lucide-receipt' },
  cash: { icon: 'i-lucide-wallet' },
  communications: { icon: 'i-lucide-message-circle' },
  professionals: { icon: 'i-lucide-stethoscope' },
  clinical_record: { icon: 'i-lucide-book-open-text', settingsPath: '/settings/apps/clinical-record' },
  reports: { icon: 'i-lucide-bar-chart-3' },
  ai: { icon: 'i-lucide-sparkles' },
  data_migration: {
    icon: 'i-lucide-database-backup',
    settingsPath: '/settings/apps/data-migration',
    actions: [
      {
        labelKey: 'settings.apps.actions.importData',
        icon: 'i-lucide-database-zap',
        to: '/settings/apps/data-migration?tab=import',
        permission: 'migration_import.job.read'
      },
      {
        labelKey: 'settings.apps.actions.exportData',
        icon: 'i-lucide-hard-drive-download',
        to: '/settings/apps/data-migration?tab=export',
        permission: 'migration_import.export.run'
      }
    ]
  }
}

export const DEFAULT_APP_ICON = 'i-lucide-box'

export function appPresentation(name: string): AppPresentation {
  return APP_CATALOG[name] ?? { icon: DEFAULT_APP_ICON }
}
