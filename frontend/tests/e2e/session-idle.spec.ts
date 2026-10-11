import type { Browser, Page } from '@playwright/test'
import { awaitHydration, expect, test } from './_fixtures'

const LAST_ACTIVITY_COOKIE = 'session:last-activity'
const HOUR_MS = 60 * 60 * 1000

async function freshContext(browser: Browser) {
  return browser.newContext({ baseURL: 'http://localhost:3000' })
}

async function logInThroughForm(page: Page): Promise<void> {
  // Only when we are not already there. Half the tests below arrive at the
  // login screen by being sent to it — `/login?redirect=%2Fpatients` — and
  // navigating again dropped the `redirect`, so the session resumed at `/`
  // and every "returns there after login" assertion failed on the app
  // doing exactly what it was asked.
  if (!new URL(page.url()).pathname.startsWith('/login')) {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 120_000 })
  }
  // Before Vue is in charge the button is enabled and inert, so clicking it
  // here filled the form and submitted nothing — which is what every test
  // below mistook for "the session did not survive".
  await awaitHydration(page)
  const submit = page.getByRole('button', { name: 'Entrar' })
  await expect(submit).toBeEnabled({ timeout: 60_000 })
  await page.getByPlaceholder('Correo electrónico').fill('admin@demo.clinic')
  await page.getByPlaceholder('Contraseña').fill('demo1234')
  await submit.click()
  // Returning on the click handed the next line a session that did not
  // exist yet: the cookies arrive with the response, so a request made in
  // between is anonymous and comes back 302. Where it lands is the test's
  // business — `/` or the deep link it was sent from — so wait for the
  // login screen to be gone, not for a particular page.
  await expect(page).not.toHaveURL(/\/login/, { timeout: 60_000 })
}

// Cold dev-server compiles of /patients and /login.
test.describe.configure({ timeout: 180_000 })

test.describe('session inactivity', () => {
  test('a deep link opened without a session returns there after login', async ({ browser }) => {
    const context = await freshContext(browser)
    const page = await context.newPage()

    await page.goto('/patients', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await expect(page).toHaveURL(/\/login\?/, { timeout: 60_000 })
    // Parsed rather than matched: whether `/` is escaped in a query is the
    // router's business, not this test's.
    const url = new URL(page.url())
    expect(url.searchParams.get('redirect')).toBe('/patients')
    // Never had a session, so nothing ended — no notice.
    expect(url.searchParams.get('reason')).toBeNull()

    await logInThroughForm(page)
    await expect(page).toHaveURL(/\/patients$/, { timeout: 60_000 })

    await context.close()
  })

  test('an hour without use sends an open page to login, and login resumes it', async ({
    browser
  }) => {
    const context = await freshContext(browser)
    const page = await context.newPage()
    await page.clock.install()

    await logInThroughForm(page)
    await page.goto('/patients?page=1', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    // The default layout publishes this on mount — the same mount that
    // starts the inactivity watch.
    await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 60_000 })

    const authCookies = (await context.cookies()).filter(c =>
      c.name === 'access_token' || c.name === 'refresh_token'
    )
    expect(authCookies).toHaveLength(2)
    expect(authCookies.every(cookie => cookie.httpOnly)).toBe(true)

    await page.clock.fastForward('01:01:00')

    // Sent to login, told why, and carrying where it was.
    await expect(page).toHaveURL(/\/login\?/, { timeout: 30_000 })
    const url = new URL(page.url())
    expect(url.searchParams.get('redirect')).toBe('/patients?page=1')
    expect(url.searchParams.get('reason')).toBe('idle')
    await expect(page.getByText(/inactividad/i)).toBeVisible()

    // The BFF cleared both server-only cookies as part of termination.
    const cookies = await context.cookies()
    expect(cookies.some(c => c.name === 'access_token' || c.name === 'refresh_token')).toBe(false)

    await logInThroughForm(page)
    await expect(page).toHaveURL(/\/patients\?page=1$/, { timeout: 60_000 })

    await context.close()
  })

  test('waking a sleeping laptop and moving the mouse does not revive the session', async ({
    browser
  }) => {
    // Timers do not run while a machine sleeps, so the interval never got
    // its chance: the first thing the page sees afterwards is a person
    // moving the mouse. Stamping that movement before checking would renew
    // a session that ended hours ago.
    const context = await freshContext(browser)
    const page = await context.newPage()
    await page.clock.install()
    await logInThroughForm(page)
    await page.goto('/patients', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 60_000 })

    // Asleep: time moves, no timer fires.
    const start = await page.evaluate(() => Date.now())
    await page.clock.pauseAt(start + 1_000)
    await page.clock.setSystemTime(start + 3 * HOUR_MS)

    // Awake. With timers still frozen, only the movement can end the session.
    const logout = page.waitForRequest(
      req => req.method() === 'POST' && req.url().endsWith('/api/v1/auth/logout'),
      { timeout: 15_000 }
    )
    await page.mouse.move(200, 200)
    await page.mouse.move(260, 240)
    await logout

    await page.clock.resume()
    await expect(page).toHaveURL(/\/login\?/, { timeout: 30_000 })
    expect(new URL(page.url()).searchParams.get('reason')).toBe('idle')

    await context.close()
  })

  test('choosing to log out does not remember the page', async ({ loggedIn: page }) => {
    // Resuming is for sessions that ended on their own. On a shared
    // front-desk computer, whoever logs in next should not open on the
    // previous person's patient.
    await page.goto('/patients', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 60_000 })

    await page.getByRole('button', { name: 'Cerrar sesión' }).click()

    await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 })
  })

  test('reopening the app after an hour away lands on login without rendering the page', async ({
    browser
  }) => {
    const context = await freshContext(browser)
    const page = await context.newPage()
    await logInThroughForm(page)

    const stale = Date.now() - 2 * HOUR_MS
    await context.addCookies([{
      name: LAST_ACTIVITY_COOKIE,
      value: String(stale),
      url: 'http://localhost:3000',
      sameSite: 'Lax'
    }])
    const response = await context.request.get('/patients', {
      maxRedirects: 0,
      timeout: 120_000
    })

    // A redirect from the server, not a page that renders and then leaves:
    // the protected content must never reach a screen nobody is watching.
    expect(response.status()).toBe(302)
    const location = new URL(response.headers().location!, 'http://localhost:3000')
    expect(location.pathname).toBe('/login')
    expect(location.searchParams.get('redirect')).toBe('/patients')
    expect(location.searchParams.get('reason')).toBe('idle')

    expect((await context.cookies()).some(c => c.name === 'access_token' || c.name === 'refresh_token')).toBe(false)

    await context.close()
  })

  // Login is the one page a user must always be able to use, so nothing on it
  // may depend on hydration having finished. The submit button used to be
  // disabled until `onMounted` ran: when hydration did not complete, the form
  // accepted typing and the button stayed dead, and only a reload got anyone
  // in — which is what this test exists to stop coming back.
  test('the login button does not wait for hydration to become usable', async ({
    browser
  }) => {
    // Scripting off is that state made permanent: whatever the client manages
    // later, this is the button the server sent.
    const context = await browser.newContext({
      baseURL: 'http://localhost:3000',
      javaScriptEnabled: false
    })
    const page = await context.newPage()
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 120_000 })

    await expect(
      page.getByRole('button', { name: 'Entrar' }),
      'the submit button must not arrive disabled'
    ).toBeEnabled()

    await context.close()
  })

  test('both the button and Enter sign in', async ({ browser }) => {
    // Removing the gate must not have cost the ordinary paths — and since the
    // form can no longer be submitted by the browser, both of them are now
    // Vue's. Which means waiting for hydration before pressing anything:
    // before it, nothing happens at all, which is the point.
    const context = await freshContext(browser)
    const page = await context.newPage()
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await page.waitForFunction(
      () => (document.getElementById('__nuxt') as unknown as { __vue_app__?: unknown })?.__vue_app__ !== undefined,
      undefined,
      { timeout: 60_000 }
    )

    await page.getByPlaceholder('Correo electrónico').fill('admin@demo.clinic')
    await page.getByPlaceholder('Contraseña').fill('demo1234')
    await page.getByPlaceholder('Contraseña').press('Enter')
    await expect(page).toHaveURL(/localhost:3000\/$/, { timeout: 60_000 })

    await page.getByRole('button', { name: 'Cerrar sesión' }).click()
    await expect(page).toHaveURL(/\/login$/, { timeout: 30_000 })

    await page.getByPlaceholder('Correo electrónico').fill('admin@demo.clinic')
    await page.getByPlaceholder('Contraseña').fill('demo1234')
    await page.getByRole('button', { name: 'Entrar' }).click()
    await expect(page).toHaveURL(/localhost:3000\/$/, { timeout: 60_000 })

    await context.close()
  })

  test('recent activity keeps the session', async ({ browser }) => {
    const context = await freshContext(browser)
    const page = await context.newPage()
    await logInThroughForm(page)
    await context.addCookies([{
      name: LAST_ACTIVITY_COOKIE,
      value: String(Date.now() - 5 * 60 * 1000),
      url: 'http://localhost:3000',
      sameSite: 'Lax'
    }])

    const response = await context.request.get('/patients', {
      maxRedirects: 0,
      timeout: 120_000
    })

    expect(response.status()).toBe(200)
    expect((await context.request.get('/api/v1/auth/me')).status()).toBe(200)

    await context.close()
  })
})
