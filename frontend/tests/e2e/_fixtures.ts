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
  // The first spec's login is the dev server's first trip through the BFF
  // proxy (and the backend's first password hash), which can outlast the
  // 8 s actionTimeout these requests inherit.
  await ctx.request.get(`${APP_BASE}/api/v1/auth/setup/status`, { timeout: 60_000 })
  const csrf = (await ctx.cookies(APP_BASE)).find(cookie => cookie.name === 'csrf_token')?.value
  const response = await ctx.request.post(`${APP_BASE}/api/v1/auth/login`, {
    data: form.toString(),
    timeout: 60_000,
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

/**
 * Describe the interactive controls that are visible, outside a
 * `data-dense` surface, and smaller than the 44 px the design system
 * requires. Empty means the screen passes.
 *
 * Dense surfaces (calendar grids, the periodontal chart) are excluded
 * deliberately: they opt out of the touch minimums because their cells
 * are units of time or anatomy, not buttons, and they get purpose-built
 * touch interactions instead of bigger boxes.
 *
 * `scope` is a CSS selector to audit instead of the whole page — a modal
 * that opens over a screen the sweep does not cover.
 */
export async function countUndersizedTargets(page: Page, scope?: string): Promise<string[]> {
  return page.evaluate((scopeSelector) => {
    const selector = [
      'button',
      'a',
      'summary',
      'select',
      'input:not([type="hidden"])',
      'textarea',
      '[role="button"]',
      '[role="tab"]',
      '[role="slider"]'
    ].join(',')

    /** A control's box, grown by a `::after` hit area when it has one. */
    function expandedRect(el: Element): DOMRect {
      const rect = el.getBoundingClientRect()
      const after = getComputedStyle(el, '::after')
      if (after.content !== '""' || after.position !== 'absolute') return rect
      const px = (v: string) => {
        const n = Number.parseFloat(v)
        return Number.isFinite(n) ? n : 0
      }
      const sides = [after.top, after.right, after.bottom, after.left].map(px)
      // Only an outward inset counts; a decorative offset is not a target.
      if (sides.some(v => v > 0)) return rect
      const [top, right, bottom, left] = sides
      return new DOMRect(
        rect.x + left,
        rect.y + top,
        rect.width - left - right,
        rect.height - top - bottom
      )
    }

    // Named, not counted: "expected 0, received 1" says nothing about
    // which control is small, and the whole point of a failure here is to
    // go and resize that one control.
    const root = scopeSelector ? document.querySelector(scopeSelector) : document
    if (!root) return [`scope not found: ${scopeSelector}`]

    const undersized: string[] = []
    for (const el of root.querySelectorAll(selector)) {
      // The Nuxt devtools anchor is dev-server furniture, not our UI.
      if (el.closest('#nuxt-devtools-anchor,#nuxt-devtools-container')) continue
      if (el.closest('[data-dense]')) continue

      // The box a control draws is not always the box a finger hits: a
      // checkbox keeps its 16px square and carries the 44px in an
      // absolutely-positioned `::after` (see main.css). Measuring the
      // element alone would report every checkbox as undersized while the
      // target is fine, so the pseudo element is folded in.
      const rect = expandedRect(el)
      if (rect.width === 0 || rect.height === 0) continue
      if (rect.bottom < 0 || rect.top > window.innerHeight) continue
      if (rect.right < 0 || rect.left > window.innerWidth) continue

      if (rect.width < 44 || rect.height < 44) {
        const label = el.getAttribute('aria-label')
          || (el.textContent || '').trim().slice(0, 40)
          || '(no label)'
        undersized.push(
          `${el.tagName.toLowerCase()} "${label}" `
          + `${Math.round(rect.width)}x${Math.round(rect.height)} `
          + `[${(el.getAttribute('class') || '').slice(0, 60)}]`
        )
      }
    }
    return undersized
  }, scope)
}
