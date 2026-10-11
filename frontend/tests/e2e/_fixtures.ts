import { test as base, expect, type BrowserContext, type Page } from '@playwright/test'

/**
 * Credentials for the seeded demo users (`./scripts/seed-demo.sh`).
 * All share the password `demo1234`.
 */
export const ROLES = {
  admin: 'admin@demo.clinic',
  dentist: 'dentist@demo.clinic',
  hygienist: 'hygienist@demo.clinic',
  assistant: 'assistant@demo.clinic',
  receptionist: 'receptionist@demo.clinic'
} as const

export type Role = keyof typeof ROLES

export const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000'
const APP_BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'
const testTokens = new WeakMap<BrowserContext, Map<Role, string>>()

/** Establish the browser session through the same-origin BFF. */
export async function login(page: Page, role: Role): Promise<void> {
  const ctx = page.context()
  const form = new URLSearchParams({ username: ROLES[role], password: 'demo1234' })
  await ctx.request.get(`${APP_BASE}/api/v1/auth/setup/status`)
  const csrf = (await ctx.cookies(APP_BASE)).find(cookie => cookie.name === 'csrf_token')?.value
  const response = await ctx.request.post(`${APP_BASE}/api/v1/auth/login`, {
    data: form.toString(),
    headers: {
      'origin': APP_BASE,
      'content-type': 'application/x-www-form-urlencoded',
      ...(csrf ? { 'x-csrf-token': csrf } : {})
    }
  })
  if (!response.ok()) throw new Error(`login failed: ${response.status()} ${await response.text()}`)

  await page.goto('/')
  await page.waitForURL(url => url.pathname === '/', { timeout: 10_000 })
}

/** A test-process-only bearer for legacy direct backend setup/inspection calls. */
/**
 * Wait until Vue has taken the page over.
 *
 * The login form is server-rendered and its button arrives **enabled** on
 * purpose: the one page a user must always reach cannot depend on
 * hydration finishing. That costs a test its old signal — `toBeEnabled()`
 * used to imply "hydrated", because the button was disabled until
 * `onMounted` ran, and it no longer does. The form is submitted by Vue
 * alone now (`type="button"` with `@click`), so a click that lands before
 * hydration does nothing at all: no request, no error on screen, just a
 * page that stays where it was.
 */
export async function awaitHydration(page: Page): Promise<void> {
  await page.waitForFunction(
    () => (document.getElementById('__nuxt') as HTMLElement & { __vue_app__?: unknown })
      ?.__vue_app__ !== undefined,
    undefined,
    { timeout: 60_000 }
  )
}

/**
 * An API token for `role`, signed in on purpose — **not** the token of
 * whoever this page is logged in as.
 *
 * It used to be exactly that: it read the `access_token` cookie off the
 * context. The BFF made that cookie httpOnly and its own, so the token has
 * to be minted here, and the role became an argument with a default. A
 * bare `tokenFor(page)` in a spec that runs as somebody else therefore asks
 * for an **admin**, which is harmless where the call only needs permission
 * and wrong where it needs an identity.
 */
export async function tokenFor(page: Page, role: Role = 'admin'): Promise<string> {
  const ctx = page.context()
  const cached = testTokens.get(ctx)?.get(role)
  if (cached) return cached
  const response = await ctx.request.post(`${API_BASE}/api/v1/auth/login`, {
    data: new URLSearchParams({ username: ROLES[role], password: 'demo1234' }).toString(),
    headers: { 'content-type': 'application/x-www-form-urlencoded' }
  })
  if (!response.ok()) throw new Error(`test API login failed: ${response.status()}`)
  const body = await response.json() as { access_token: string }
  const tokens = testTokens.get(ctx) ?? new Map<Role, string>()
  tokens.set(role, body.access_token)
  testTokens.set(ctx, tokens)
  return body.access_token
}

type RoleFixture = {
  role: Role
  loggedIn: Page
}

export const test = base.extend<RoleFixture>({
  role: ['admin', { option: true }],
  loggedIn: async ({ page, role }, use) => {
    await login(page, role)
    await use(page)
  }
})

/**
 * Statuses the board draws into a column that is expanded by default.
 * `completed` and `no_show`/`cancelled` land in "Finalizadas" and "No
 * asistió", both `collapsedByDefault` — their cards exist in the DOM's
 * eyes only once a human opens the column, so a day made of those is
 * indistinguishable from an empty one here.
 */
const EXPANDED_COLUMN_STATUSES = new Set([
  'scheduled',
  'confirmed',
  'checked_in',
  'in_treatment'
])

/**
 * The local date of a seeded appointment that a single-day view will
 * actually draw, as `YYYY-MM-DD` for the page's `?date=` param.
 *
 * Needed by the kanban and, since a portrait tablet now defaults to the
 * day view, by the drag tests too. The board renders a single day
 * (`currentDate`, defaulting to today), so it needs a day that really
 * has cards. Neither "today" nor any hardcoded weekday is that day:
 * `generate_appointments_data` places visits Monday–Friday only *and*
 * carries its slot counter across the past/current/future weeks, so
 * which weekdays get filled shifts per week — the current week can
 * start on a Tuesday and leave Monday empty. Asking the API keeps this
 * correct whatever day CI runs on and however the fixtures are
 * redistributed later.
 */
export async function dayWithAppointment(page: Page): Promise<string> {
  const token = await tokenFor(page)

  const from = new Date()
  from.setDate(from.getDate() - 7)
  const to = new Date()
  to.setDate(to.getDate() + 21)

  const response = await page.context().request.get(`${API_BASE}/api/v1/agenda/appointments`, {
    params: { start_date: from.toISOString(), end_date: to.toISOString(), page_size: 500 },
    headers: { Authorization: `Bearer ${token}` }
  })
  if (!response.ok()) {
    throw new Error(`appointment lookup failed: ${response.status()} ${await response.text()}`)
  }

  const body = (await response.json()) as { data: { start_time: string, status: string }[] }
  const usable = body.data
    .filter(a => EXPANDED_COLUMN_STATUSES.has(a.status))
    .sort((a, b) => a.start_time.localeCompare(b.start_time))[0]
  if (!usable) {
    throw new Error('no seeded appointment lands in an expanded kanban column')
  }

  // Local getters on purpose: the board's own `isSameDay` compares local
  // date parts, and `?date=` is parsed as local midnight.
  const day = new Date(usable.start_time)
  const mm = String(day.getMonth() + 1).padStart(2, '0')
  const dd = String(day.getDate()).padStart(2, '0')
  return `${day.getFullYear()}-${mm}-${dd}`
}

export { expect }
