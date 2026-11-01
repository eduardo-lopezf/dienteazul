import { test, expect } from './_fixtures'

/**
 * RBAC smoke — asserts the sidebar reflects what each role is allowed
 * to see. Backend-side permission enforcement has its own pytest
 * coverage; this file verifies the UI hides / shows the right entry
 * points so we don't regress the user experience.
 *
 * Labels come from the nav i18n block; keep the regexes loose so
 * copy-edits don't break the suite.
 */

const LABELS = {
  patients: /patients|pacientes/i,
  schedule: /schedule|agenda|citas|appointments/i,
  // Treatment plans no longer have their own nav entry — they live
  // under the "Treatments" section owned by `catalog` (nav.treatments,
  // /treatments), alongside the treatment catalog. See
  // backend/app/modules/treatment_plan/__init__.py's frontend.navigation
  // comment ("One menu entry, two surfaces").
  treatments: /^(treatments|tratamientos)$/i,
  // Budgets and invoices no longer have nav entries of their own: they
  // are tabs of the host's Finanzas page, alongside payments. The nav
  // check is therefore about Finanzas, and the per-module permission is
  // asserted on the tabs themselves — which is where it now lives, on
  // each module's `finance.tabs` slot registration.
  finance: /finance|finanzas/i,
  quotes: /quotes|budgets|presupuestos/i,
  invoices: /invoices|facturas/i,
  reports: /productivity|productividad|reports|informes/i
}

test.describe('hygienist sees clinical + scheduling, no reports', () => {
  test.use({ role: 'hygienist' })

  test('navigation is filtered to read-only flows', async ({ loggedIn }) => {
    const nav = loggedIn.getByRole('navigation').first()
    await expect(nav.getByRole('link', { name: LABELS.patients })).toBeVisible()
    await expect(nav.getByRole('link', { name: LABELS.schedule })).toBeVisible()
    // Reports require reports.billing.read which hygienist lacks.
    await expect(nav.getByRole('link', { name: LABELS.reports })).toHaveCount(0)
  })
})

test.describe('receptionist sees patients + schedule + invoices', () => {
  test.use({ role: 'receptionist' })

  test('navigation is filtered to front-desk flows', async ({ loggedIn }) => {
    const nav = loggedIn.getByRole('navigation').first()
    await expect(nav.getByRole('link', { name: LABELS.patients })).toBeVisible()
    await expect(nav.getByRole('link', { name: LABELS.schedule })).toBeVisible()
    await expect(nav.getByRole('link', { name: LABELS.finance })).toBeVisible()
  })

  test('reaches invoices and budgets through the Finanzas tabs', async ({ loggedIn }) => {
    await loggedIn.goto('/finanzas')
    const tabs = loggedIn.getByRole('tab')
    // Each tab is a module's slot registration pointing at an async
    // component, and the dev server compiles those on first request: the
    // tabs appeared at ~7.5 s here, against the 5 s default. The wait is
    // for the compiler, not for the app.
    await expect(tabs.filter({ hasText: LABELS.invoices })).toBeVisible({ timeout: 60_000 })
    await expect(tabs.filter({ hasText: LABELS.quotes })).toBeVisible()
  })
})

test.describe('dentist has full clinical access', () => {
  test.use({ role: 'dentist' })

  test('nav shows every clinical flow', async ({ loggedIn }) => {
    const nav = loggedIn.getByRole('navigation').first()
    for (const label of [
      LABELS.patients,
      LABELS.schedule,
      LABELS.treatments,
      LABELS.finance
    ]) {
      await expect(nav.getByRole('link', { name: label })).toBeVisible()
    }
  })
})
