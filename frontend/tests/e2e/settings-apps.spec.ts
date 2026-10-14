import { test, expect } from './_fixtures'

/**
 * Smoke for the read-only apps screen at /settings/apps.
 * - Admin can reach the page and see the app list, with nothing to click
 *   that would turn one on or off.
 * - Non-admin cannot (page shows a forbidden message).
 */

test.describe('admin sees the apps screen', () => {
  test.use({ role: 'admin' })

  test('admin loads /settings/apps and sees module cards', async ({ loggedIn }) => {
    await loggedIn.goto('/settings/apps')

    // Page title (ES or EN, depending on user locale).
    await expect(
      loggedIn.getByRole('heading', { level: 1, name: /^apps$/i })
    ).toBeVisible()

    // At least one of the core modules must be listed — they are always
    // discovered, so this is a deterministic smoke check. The list is
    // fetched after hydration, which the dev server takes its time over.
    await expect(
      loggedIn.getByRole('heading', { level: 3, name: /^patients$/ })
    ).toBeVisible({ timeout: 15_000 })

    // The base App opens the catalog, always on (ADR 0043).
    const workspace = loggedIn.getByTestId('app-card-workspace')
    await expect(workspace.getByRole('heading', { level: 3 })).toHaveText(/Espacio de trabajo|Workspace/)
    await expect(loggedIn.getByTestId('app-tier-workspace')).toHaveText(/App principal|Main app/)
    await expect(workspace).toContainText(/Siempre habilitada|Always enabled/)
    await expect(loggedIn.getByTestId('app-configure-workspace')).toHaveAttribute('href', '/settings/apps/workspace')
    // Data migration is configured — and run — from its own card.
    if (await loggedIn.getByTestId('app-card-data_migration').count()) {
      await expect(loggedIn.getByTestId('app-configure-data_migration')).toHaveAttribute('href', '/settings/apps/data-migration')
      // …and its two procedures have a button each, straight to their tab.
      await expect(loggedIn.getByTestId('app-action-data_migration-import')).toHaveAttribute('href', '/settings/apps/data-migration?tab=import')
      await expect(loggedIn.getByTestId('app-action-data_migration-export')).toHaveAttribute('href', '/settings/apps/data-migration?tab=export')
    }
    await expect(loggedIn.locator('[data-testid^="app-card-"]').first()).toHaveAttribute(
      'data-testid',
      'app-card-workspace'
    )
    await expect(loggedIn.getByTestId('app-tier-agenda')).toHaveText(/App core|Core app/)
    // Every App not yet classified is an optional App, Communications among them.
    await expect(loggedIn.getByTestId('app-tier-communications')).toHaveText(/App opcional|Optional app/)
    await expect(loggedIn.getByTestId('app-tier-professionals')).toHaveText(/App opcional|Optional app/)

    // The catalog (`backend/apps.json`): Agenda v0.1, enabled.
    const agenda = loggedIn.getByTestId('app-card-agenda')
    await expect(agenda.getByRole('heading', { level: 3, name: /^Agenda$/ })).toBeVisible()
    await expect(agenda).toContainText('v0.1')
    // Case matters: "Deshabilitada" contains "habilitada".
    await expect(agenda).toContainText(/(^|\s)(Habilitada|Enabled)(\s|$)/)

    // Widgets and APIs are pages of their own now, not tabs of this one.
    await expect(loggedIn.getByRole('tab')).toHaveCount(0)

    // Read-only: enabling or disabling is an operator decision (ADR 0035).
    await expect(
      loggedIn.getByRole('button', { name: /habilitar|enable|desinstalar|uninstall|instalar|install/i })
    ).toHaveCount(0)
  })

  test('admin sees the widgets of each App, with examples, on their own page', async ({ loggedIn }) => {
    await loggedIn.goto('/settings/widgets')
    await expect(
      loggedIn.getByRole('heading', { level: 1, name: /^widgets$/i })
    ).toBeVisible()

    // Grouped by App: the five Agenda contributes, each with a live example…
    const agenda = loggedIn.getByTestId('widget-group-agenda')
    await expect(agenda.locator('[data-testid^="widget-card-"]')).toHaveCount(5, {
      timeout: 15_000
    })
    await expect(agenda.getByTestId('widget-group-title')).toContainText('Agenda')
    // The examples are filled with made-up data, whatever the clinic's
    // day looks like: three unconfirmed visits, none of them real.
    const unconfirmed = loggedIn.getByTestId('widget-card-agenda.dashboard.unconfirmed')
    await expect(unconfirmed).toContainText('Sofía Ejemplo')
    await expect(unconfirmed).toContainText('Carmen Modelo')

    // …and the four of Patients, also filled with made-up data.
    const patients = loggedIn.getByTestId('widget-group-patients')
    await expect(patients.locator('[data-testid^="widget-card-"]')).toHaveCount(4)
    await expect(patients.getByTestId('widget-group-title')).toContainText('Pacientes')
    await expect(patients.getByTestId('widget-card-patients.dashboard.recent'))
      .toContainText('Marcos Prueba')
    await expect(patients.getByTestId('widget-card-patients_clinical.patient.summary.cards.medical'))
      .toContainText('Penicilina')
    await expect(patients.getByTestId('widget-card-patients_clinical.patient.header.alerts'))
      .toContainText('Alergia a penicilina')
  })

  test('admin sees the APIs an App can connect to on their own page', async ({ loggedIn }) => {
    await loggedIn.goto('/settings/apis')
    await expect(
      loggedIn.getByRole('heading', { level: 1, name: /^apis$/i })
    ).toBeVisible()

    // Google Calendar is listed for Agenda and not available yet.
    const calendar = loggedIn.getByTestId('api-card-google_calendar')
    // The list is fetched after hydration, which the dev server takes its time over.
    await expect(calendar).toContainText('Google Calendar', { timeout: 15_000 })
    await expect(calendar).toContainText(/Próximamente|Coming soon/)

    // WhatsApp is listed for Communications, not available yet either.
    const whatsapp = loggedIn.getByTestId('api-card-whatsapp')
    await expect(whatsapp).toContainText('WhatsApp')
    await expect(whatsapp).toContainText(/Comunicaciones|Communications/)
    await expect(whatsapp).toContainText(/Próximamente|Coming soon/)
  })
})

test.describe('hygienist cannot reach the apps screen', () => {
  test.use({ role: 'hygienist' })

  test('hygienist sees forbidden message, no module cards', async ({ loggedIn }) => {
    await loggedIn.goto('/settings/apps')

    // No module cards rendered.
    await expect(
      loggedIn.getByRole('heading', { level: 3, name: /^patients$/ })
    ).toHaveCount(0)

    // The page renders a forbidden fallback.
    await expect(
      loggedIn.getByText(/acceso denegado|access denied/i)
    ).toBeVisible()
  })
})
