import { test, expect } from './_fixtures'

/**
 * Sidebar navigation smoke: every module an admin can see must render
 * its landing page without 404 / 500. The minimum bar after the Fase
 * B.6 layer split — catches broken `modules.json`, missing
 * `components:` registration, or a layer page that crashes in SSR.
 */

const ADMIN_ROUTES = [
  // Home renders a time-of-day greeting ("Good morning, X" / "Buenos días, X")
  // or a welcome empty state when no module registers dashboard slots.
  { path: '/', selector: /home|inicio|dashboard|panel|good (morning|afternoon|evening)|buen(os días|as tardes|as noches)|welcome|bienvenid/i },
  { path: '/patients', selector: /patients|pacientes/i },
  { path: '/appointments', selector: /schedule|agenda|appointment|cita/i },
  { path: '/treatment-plans', selector: /plans|planes|treatment/i },
  { path: '/finanzas', selector: /finance|finanzas/i },
  // The old list routes redirect into the Finanzas tabs. Keeping them
  // here is what proves the redirects still land on something that
  // renders, rather than 404ing for anyone with an old bookmark.
  { path: '/budgets', selector: /quotes|budgets|presupuesto/i },
  { path: '/invoices', selector: /invoices|facturas/i },
  { path: '/payments', selector: /payments|cobros/i },
  { path: '/reports', selector: /productivity|productividad|reports|informes/i },
  { path: '/settings', selector: /settings|configuración|configuracion/i },
  { path: '/settings/catalog', selector: /catalog|catálogo|catalogo/i },
  { path: '/settings/vat-types', selector: /vat|iva/i },
  { path: '/settings/invoice-series', selector: /series|serie/i },
  { path: '/settings/notifications', selector: /notifications|notificaciones/i }
]

// This suite drives the Nuxt **dev** server, which compiles a route the first
// time it is asked for: a cold /finanzas took 8.4 s to show its tabs here,
// against an 8 s budget, so the finance routes failed or passed depending on
// what had warmed them earlier in the run. The budgets below are sized for a
// compile, not for a render — a real breakage still fails, just later.
test.describe.configure({ timeout: 120_000 })

test.describe('admin navigation smoke', () => {
  test.use({ role: 'admin' })

  for (const { path, selector } of ADMIN_ROUTES) {
    test(`renders ${path}`, async ({ loggedIn }) => {
      const response = await loggedIn.goto(path, { waitUntil: 'domcontentloaded' })
      expect(response?.status() ?? 0).toBeLessThan(400)
      // The route renders *something* matching its section — a heading,
      // a button, a link, or a tab. `toBeVisible` accepts the first hit
      // so the assertion stays independent of component layout churn.
      // Tabs are in the list because a section is no longer necessarily
      // a page: the old /budgets, /invoices and /payments routes now
      // redirect into tabs of Finanzas, where the section's name is the
      // tab's.
      // Scope to the page main content so the sidebar links don't
      // fire false positives.
      const main = loggedIn.getByRole('main').first()
      const heading = main.getByRole('heading', { name: selector })
      const link = main.getByRole('link', { name: selector })
      const button = main.getByRole('button', { name: selector })
      const tab = main.getByRole('tab', { name: selector })
      await expect(heading.or(link).or(button).or(tab).first()).toBeVisible({ timeout: 45_000 })
    })
  }
})
