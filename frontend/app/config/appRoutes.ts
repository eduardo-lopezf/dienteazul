/**
 * Routes that belong to an App the deployment can switch off
 * (`backend/apps.json`, ADR 0038).
 *
 * Every layer is compiled into the build, so a disabled App's pages are
 * still routable: its menu entry goes, but a bookmark or a typed URL
 * lands on a screen whose API answers 404. `useAppRouteGuard` reads this
 * table and sends those visits home with a notice instead.
 *
 * `module` is the one whose absence makes the route unusable; `app` is
 * the catalog name, used for the notice. Add a row when an App gains a
 * page of its own.
 */
export interface AppRoute {
  prefix: string
  module: string
  app: string
  /** Overrides the generic "<App> is not enabled" notice. */
  noticeKey?: string
}

export const APP_ROUTES: AppRoute[] = [
  { prefix: '/appointments', module: 'agenda', app: 'agenda', noticeKey: 'appointments.unavailable' },
  { prefix: '/patients', module: 'patients', app: 'patients' },
  { prefix: '/professionals', module: 'professionals', app: 'professionals' },
  { prefix: '/recalls', module: 'recalls', app: 'recalls' },
  // More specific first: `appRouteFor` returns the first match.
  { prefix: '/treatments/plans', module: 'treatment_plan', app: 'treatments' },
  { prefix: '/treatments', module: 'catalog', app: 'treatments' },
  { prefix: '/settings/catalog', module: 'catalog', app: 'treatments' },
  { prefix: '/settings/vat-types', module: 'catalog', app: 'treatments' },
  { prefix: '/budgets', module: 'budget', app: 'budgets_payments' },
  { prefix: '/invoices', module: 'billing', app: 'budgets_payments' },
  { prefix: '/payments', module: 'payments', app: 'budgets_payments' },
  { prefix: '/settings/invoice-series', module: 'billing', app: 'budgets_payments' },
  { prefix: '/settings/verifactu', module: 'verifactu', app: 'budgets_payments' },
  { prefix: '/accounting-export', module: 'accounting_export', app: 'budgets_payments' },
  // Before `/reports`: this report belongs to `payments`.
  { prefix: '/reports/payments', module: 'payments', app: 'budgets_payments' },
  { prefix: '/settings/apps/treatments', module: 'catalog', app: 'treatments' },
  { prefix: '/settings/apps/clinical-record', module: 'record', app: 'clinical_record' },
  { prefix: '/settings/apps/data-migration', module: 'migration_import', app: 'data_migration' },
  { prefix: '/reports', module: 'reports', app: 'reports' },
  { prefix: '/copilot', module: 'copilot', app: 'ai' }
]

export function appRouteFor(path: string): AppRoute | undefined {
  return APP_ROUTES.find(r => path === r.prefix || path.startsWith(`${r.prefix}/`))
}
