/**
 * The case the inactivity tests cannot reach: the **server** has ended
 * the session and the browser does not know it yet.
 *
 * That is the shape of the incident behind ADR 0062. The local stamp was
 * fresh — the browser had been writing it without the server's agreement
 * — so every local check said "still signed in", and the refusal only
 * surfaced on the next request. What the user then got was a generic
 * "your session expired" with nothing to quote to anybody, because the
 * reason was guessed from that same stamp and the refusal was logged
 * nowhere.
 *
 * `session-idle.spec.ts` drives the rule the browser enforces (the clock
 * is fast-forwarded and the page ends its own session). This drives the
 * other direction and asserts what the user is left looking at: the
 * right sentence, and the reference that finds the line in the
 * operator's log.
 *
 * The family is revoked from a second browser context holding a copy of
 * the refresh cookie, so the first context's cookies stay exactly as a
 * working tab would have them. Over HTTP only — no database access, so
 * this runs wherever the e2e job runs.
 */
import type { Browser, Page } from '@playwright/test'
import { awaitHydration, expect, test } from './_fixtures'

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000'
const LAST_ACTIVITY_COOKIE = 'session:last-activity'

async function logIn(page: Page): Promise<void> {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await awaitHydration(page)
  const submit = page.getByRole('button', { name: 'Entrar' })
  await expect(submit).toBeEnabled({ timeout: 60_000 })
  await page.getByPlaceholder('Correo electrónico').fill('admin@demo.clinic')
  await page.getByPlaceholder('Contraseña').fill('demo1234')
  await submit.click()
  await expect(page).not.toHaveURL(/\/login/, { timeout: 60_000 })
}

/**
 * End the session family server-side without touching this context's
 * cookies: a throwaway context gets a copy of the refresh cookie and
 * signs out with it. The BFF's logout takes the exact origin and no CSRF
 * token (ADR 0052), which is what makes this reachable from here.
 */
async function revokeFamilyElsewhere(browser: Browser, refreshToken: string): Promise<void> {
  const other = await browser.newContext({ baseURL: BASE_URL })
  await other.addCookies([{
    name: 'refresh_token',
    value: refreshToken,
    url: BASE_URL,
    httpOnly: true,
    sameSite: 'Lax'
  }])
  const response = await other.request.post('/api/v1/auth/logout', {
    data: {},
    headers: { 'origin': BASE_URL, 'content-type': 'application/json' },
    timeout: 60_000
  })
  expect(response.status(), 'the copy of the refresh cookie must end the family').toBe(204)
  await other.close()
}

// Cold dev-server compiles of /patients and /login.
test.describe.configure({ timeout: 180_000 })

test.describe('a session the server has ended', () => {
  test('says it was revoked, not that it timed out, and carries a reference', async ({
    browser
  }) => {
    const context = await browser.newContext({ baseURL: BASE_URL })
    const page = await context.newPage()
    await logIn(page)

    const refresh = (await context.cookies(BASE_URL)).find(c => c.name === 'refresh_token')
    expect(refresh?.value, 'logging in must leave a refresh cookie').toBeTruthy()
    await revokeFamilyElsewhere(browser, refresh!.value)

    // The tab is none the wiser: its access cookie is still there and its
    // activity stamp is seconds old. Every local check passes.
    await context.addCookies([{
      name: LAST_ACTIVITY_COOKIE,
      value: String(Date.now()),
      url: BASE_URL,
      sameSite: 'Lax'
    }])
    expect((await context.cookies(BASE_URL)).some(c => c.name === 'access_token')).toBe(true)

    // A server render is what notices. It must redirect rather than
    // paint a protected page, and say which case it was.
    const response = await context.request.get('/patients?page=3', {
      maxRedirects: 0,
      timeout: 120_000
    })
    expect(response.status()).toBe(302)
    const location = new URL(response.headers().location!, BASE_URL)
    expect(location.pathname).toBe('/login')
    expect(location.searchParams.get('redirect')).toBe('/patients?page=3')
    // Not `idle` — nobody was away — and not a bare `expired`, which is
    // what the browser used to guess from its own fresh stamp.
    expect(location.searchParams.get('reason')).toBe('revoked')
    // The backend's request id for the refusal, which heads the WARNING
    // it logged (ADR 0059, ADR 0060).
    expect(location.searchParams.get('ref')).toMatch(/^[\w-]{8,64}$/)

    await context.close()
  })

  test('the login screen shows the case and the reference it was given', async ({ browser }) => {
    const context = await browser.newContext({ baseURL: BASE_URL })
    const page = await context.newPage()
    await logIn(page)

    const refresh = (await context.cookies(BASE_URL)).find(c => c.name === 'refresh_token')
    await revokeFamilyElsewhere(browser, refresh!.value)
    await context.addCookies([{
      name: LAST_ACTIVITY_COOKIE,
      value: String(Date.now()),
      url: BASE_URL,
      sameSite: 'Lax'
    }])

    await page.goto('/patients', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await expect(page).toHaveURL(/\/login\?/, { timeout: 60_000 })

    // What the person is actually left reading. The wording may be
    // reworded; that it is not the inactivity one, and that a reference
    // is on screen, is the contract.
    await expect(page.getByText(/seguridad|otro sitio/i)).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText(/inactividad/i)).toHaveCount(0)
    const reference = new URL(page.url()).searchParams.get('ref')!
    await expect(page.getByText(new RegExp(`Referencia:\\s*${reference}`))).toBeVisible()

    await context.close()
  })
})
