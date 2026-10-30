import type { Page } from '@playwright/test'
import { API_BASE, countUndersizedTargets, expect, test, tokenFor } from './_fixtures'

/**
 * Touch-adaptation guarantees, run in both tablet orientations.
 *
 * These exist because a 1280x800 tablet in landscape passes every
 * width-based check — it is as wide as a laptop — and is still driven by
 * a finger. Only `hasTouch` with a coarse pointer catches a regression
 * here, so the desktop `chromium` project cannot stand in for it.
 *
 * See docs/technical/touch-adaptation.md and ADR 0022.
 */

/** What one hydration is allowed to cost on a cold module graph. */
const HYDRATION_TIMEOUT = 60_000

/**
 * Block until client-side device detection has run.
 *
 * Everything here is asserted on values the client computes at mount, and
 * the dev server hydrates this app in well over the default 5 s
 * expect timeout on a cold module graph. `data-ua` is written once, from
 * `useDevice`'s mount hook, so its presence is the hydration signal.
 *
 * The wait also buys the deadline it is allowed to spend. Raising only the
 * selector timeout left this wait permitted 60 s inside a suite whose
 * per-test budget is 30 s, so a slow route killed the test before its
 * assertion ever ran — and it did, intermittently, for exactly the five
 * tests that had not raised their own budget, while the five on 180 s never
 * flaked. Paying for it here rather than per test is what keeps the next
 * test anyone adds from inheriting the same trap.
 */
async function awaitDetection(page: Page): Promise<void> {
  test.setTimeout(test.info().timeout + HYDRATION_TIMEOUT)
  await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: HYDRATION_TIMEOUT })
}

/**
 * A plan the clinic counts as under way, with a budget already issued.
 *
 * Those two together are what freezes the plan's odontogram, so the test
 * that checks the freeze has to have both. Read through the API because
 * neither is visible from a list row.
 */
async function findLockedPlanId(page: Page): Promise<string | undefined> {
  const response = await page.request.get(
    `${API_BASE}/api/v1/treatment_plan/treatment-plans?page_size=100`,
    { headers: { authorization: `Bearer ${await tokenFor(page)}` } }
  )
  expect(response.ok(), `plan list: ${response.status()}`).toBe(true)
  const body = (await response.json()) as {
    data: { id: string, status: string, budget_id: string | null }[]
  }
  return body.data.find(
    plan => ['pending', 'active'].includes(plan.status) && plan.budget_id
  )?.id
}

test.describe('touch adaptation', () => {
  test('detects the coarse pointer and publishes it on <html>', async ({ loggedIn: page }) => {
    await awaitDetection(page)
    const html = page.locator('html')
    await expect(html).toHaveAttribute('data-pointer', 'coarse')

    const viewport = page.viewportSize()!
    const expected = viewport.height > viewport.width ? 'portrait' : 'landscape'
    await expect(html).toHaveAttribute('data-orientation', expected)
  })

  test('forces the touch density regardless of viewport width', async ({ loggedIn: page }) => {
    await awaitDetection(page)
    // The landscape project is 1280 px wide — under the old width-based
    // rule this was "desktop" and compact density stayed available.
    await expect(page.locator('html')).toHaveClass(/density-touch/)

    // The density toggle would be a control that does nothing here.
    await expect(page.getByRole('button', { name: /vista (cómoda|compacta)/i })).toHaveCount(0)
  })

  test('collapses the sidebar by default so the canvas keeps its width', async ({ loggedIn: page }) => {
    await awaitDetection(page)
    await expect(page.locator('aside').first()).toHaveClass(/w-16/)
  })

  test('every control outside a dense surface meets the 44 px minimum', async ({ loggedIn: page }) => {
    for (const route of ['/', '/appointments', '/patients', '/treatments/plans']) {
      await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 120_000 })
      await awaitDetection(page)
      // Let the async view components and their data land.
      await expect(page.locator('main')).toBeVisible()
      await page.waitForTimeout(2000)

      expect(await countUndersizedTargets(page), `undersized targets on ${route}`).toEqual([])
    }
  })

  /**
   * The bandeja rows used to lay themselves out from `md:`, a *viewport*
   * breakpoint. Held upright the viewport is 800 px while the card is
   * barely 500, so the row went horizontal in a box that could not hold
   * it and the plan number, the badge and "Tratamientos" were painted on
   * top of one another. Container queries fixed it; this keeps it fixed,
   * because nothing else in the suite would notice text overlapping text.
   */
  test('bandeja rows never overlap their own text', async ({ loggedIn: page }) => {
    await page.goto('/treatments/plans', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForTimeout(2000)

    const collisions = await page.evaluate(() => {
      const hit = (a: DOMRect, b: DOMRect) =>
        !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top)

      const cards = [...document.querySelectorAll('main div')].filter(el =>
        String((el as HTMLElement).className).includes('@container')
      )

      const found: string[] = []
      for (const card of cards) {
        // Leaf elements only: an ancestor always "overlaps" its child.
        const leaves = [...card.querySelectorAll('div,span,button')].filter(
          el => el.children.length === 0 && (el.textContent || '').trim()
        )
        for (let i = 0; i < leaves.length; i++) {
          for (let j = i + 1; j < leaves.length; j++) {
            const a = leaves[i].getBoundingClientRect()
            const b = leaves[j].getBoundingClientRect()
            if (a.width && b.width && hit(a, b)) {
              found.push(`${leaves[i].textContent?.trim()} ⨯ ${leaves[j].textContent?.trim()}`)
            }
          }
        }
      }
      return found
    })

    expect(collisions, `overlapping text in the bandeja: ${collisions.join(', ')}`).toEqual([])
  })

  /**
   * The plan detail is the screen reception actually works in once a plan
   * is open, and it carries the odontogram, so it is worth auditing in
   * both orientations. Reached through the list rather than by a fixed id
   * so the test does not depend on which plans are seeded.
   */
  test('the plan detail meets the 44 px minimum in both orientations', async ({
    loggedIn: page
  }) => {
    // Two cold page compiles (list, then detail with the odontogram) do
    // not fit the 30 s default on a dev server.
    test.setTimeout(180_000)

    // The Listado tab renders real links, so the first row's href is the
    // detail URL — no clicking through a router.push to get there.
    await page.goto('/treatments/plans?tab=listado', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()

    const firstRow = page.locator('main a[href*="/treatments/plans/"]').first()
    await expect(firstRow).toBeVisible({ timeout: 60_000 })
    const href = await firstRow.getAttribute('href')
    expect(href, 'no plan row to open').toBeTruthy()

    await page.goto(href!, { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForTimeout(2000)

    expect(await countUndersizedTargets(page), 'undersized targets on the plan detail').toEqual([])
  })

  /**
   * The budget's sidebar opens on its treatment plan, where the money is
   * followed — the collections card that used to sit there is gone. The
   * plan is found through the API because it is the one pair the seed
   * guarantees: a plan under way carrying a budget.
   */
  test('the budget detail links to its plan and meets the 44 px minimum', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)
    const planId = await findLockedPlanId(page)
    expect(planId, 'the seed has no plan in progress carrying a budget').toBeTruthy()
    const plan = await page.request.get(
      `${API_BASE}/api/v1/treatment_plan/treatment-plans/${planId}`,
      { headers: { authorization: `Bearer ${await tokenFor(page)}` } }
    )
    const budgetId = ((await plan.json()) as { data: { budget_id: string } }).data.budget_id

    await page.goto(`/budgets/${budgetId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    await expect(page.locator(`main a[href="/treatments/plans/${planId}"]`)).toBeVisible({
      timeout: 60_000
    })
    await expect(page.getByText('Cobros del presupuesto')).toHaveCount(0)
    await page.waitForTimeout(1000)

    expect(await countUndersizedTargets(page), 'undersized targets on the budget detail').toEqual([])
  })

  /**
   * Agenda → patient record → the summary's active-plan card. The card
   * linked to the legacy `/treatment-plans/{id}`, which exists only as a
   * server redirect: followed inside the app the client applied it
   * literally and landed on `/treatments/plans/**` — a plan with id `**`,
   * "No encontrado", and a reload was the only way out. The path is walked
   * client-side on purpose; a fresh `goto` would hide the bug.
   */
  test('the active-plan card opens the plan when reached from the agenda', async ({
    loggedIn: page
  }) => {
    test.setTimeout(240_000)
    const planId = await findLockedPlanId(page)
    expect(planId, 'the seed has no plan in progress carrying a budget').toBeTruthy()
    const plan = await page.request.get(
      `${API_BASE}/api/v1/treatment_plan/treatment-plans/${planId}`,
      { headers: { authorization: `Bearer ${await tokenFor(page)}` } }
    )
    const patientId = ((await plan.json()) as { data: { patient_id: string } }).data.patient_id

    await page.goto('/appointments', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    await page.evaluate(
      (id) => {
        const app = (document.querySelector('#__nuxt') as unknown as {
          __vue_app__: { config: { globalProperties: { $router: { push: (p: string) => void } } } }
        }).__vue_app__
        app.config.globalProperties.$router.push(`/patients/${id}`)
      },
      patientId
    )

    const card = page.locator(`main a[href^="/treatments/plans/${planId}"]`).first()
    await expect(card).toBeVisible({ timeout: 90_000 })
    await card.click()
    await expect(page).toHaveURL(new RegExp(`/treatments/plans/${planId}`), { timeout: 60_000 })
    await expect(page.getByText('No encontrado')).toHaveCount(0)
  })

  /**
   * Finanzas' tabs come from client-only slot registrations. Rendered on
   * the server the page took its empty-state branch, and hydration left
   * the tabs inside that state's centred box: every finance list read
   * centred under a 48 px gap. The tab strip must never sit in it.
   */
  test('the finance tabs are not rendered inside the empty state', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)
    await page.goto('/finanzas?tab=budget', { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    const tabs = page.getByRole('tablist').first()
    await expect(tabs).toBeVisible({ timeout: 60_000 })
    expect(await tabs.evaluate(el => el.closest('.text-center') !== null)).toBe(false)

    // A budget is deleted only with its treatment plan, so the list offers
    // no delete — it used to, on accepted budgets too.
    await expect(page.locator('main a[href^="/budgets/"]').first()).toBeVisible({ timeout: 60_000 })
    await expect(page.getByRole('button', { name: 'Eliminar presupuesto' })).toHaveCount(0)
  })

  /**
   * The in-clinic acceptance is signed with a finger, so its dialog is
   * the one surface here that has to survive touch: a signature canvas
   * plus a name field plus two actions, on the short side of a tablet.
   * Route audits never open it, so nothing else in the suite would
   * notice the controls shrinking.
   */
  test('the accept-in-clinic dialog meets the 44 px minimum', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)

    // This test drives a dialog whose whole purpose is to accept a real
    // budget, against the dev database, on whatever plan happens to be
    // first in the queue. Twice now a suite run has left a budget signed
    // that nobody meant to sign. Blocking the request makes the dialog
    // safe to open and measure: the layout is all this test is about, and
    // acceptance has its own coverage in the backend suite.
    await page.route('**/accept-in-clinic', route => route.abort())

    await page.goto('/treatments/plans?tab=por_presupuestar', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()
    await page.waitForTimeout(2000)

    const accept = page.getByRole('button', { name: 'Aceptar en clínica' }).first()
    if (await accept.count() === 0) {
      // The button only exists while some plan still has an unsigned
      // budget. Say so rather than passing silently on an empty queue.
      test.skip(true, 'no budget in draft/sent to accept in this dataset')
    }

    await accept.click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(1000)

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the accept-in-clinic dialog'
    ).toEqual([])
  })

  /**
   * The plan builder: a blank chart, and the patient asked last.
   *
   * It is the screen a dentist uses on a tablet at the chair, so both
   * orientations have to work — the chart is the widest thing in the app and
   * a tablet held upright is the narrowest it ever gets.
   */
  test('the builder draws a plan on a blank chart, tooth by tooth', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    await page.goto('/treatments/plans/new', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()

    // A full permanent dentition, and no patient behind it.
    const teeth = page.locator('main .tooth-cell')
    await expect(teeth.first()).toBeVisible({ timeout: 60_000 })
    expect(await teeth.count()).toBe(32)

    // Tapping a tooth opens the panel, and it is not empty before you type:
    // the treatments the clinic used most recently are the head start.
    await teeth.filter({ hasText: '16' }).first().click()
    await expect(page.getByText('Usados recientemente')).toBeVisible({ timeout: 30_000 })
    const firstRecent = page.locator('.treatment-row').first()
    await expect(firstRecent).toBeVisible()
    await firstRecent.click()

    // The tap lands in the plan, and the plan is what the chart now shows.
    await expect(page.locator('.draft-line')).toHaveCount(1)
    await expect(page.getByRole('button', { name: 'Continuar' })).toBeEnabled()

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the plan builder'
    ).toEqual([])
  })

  /**
   * Searching the panel, which is the other half of how a plan gets built.
   *
   * Two groups come back from one box — the clinic's plan templates and the
   * loose catalog — and on a tablet both have to be tappable, which the 44 px
   * rule covers, *and* visible, which it does not: the panel opens to show a
   * list, and autofocus raises the on-screen keyboard straight over it. The
   * field is focused on a mouse and left alone under a finger, so this is the
   * only project where the assertion below can fail.
   */
  test('searching returns templates and treatments without raising the keyboard', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    await page.goto('/treatments/plans/new', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()

    await page.getByRole('button', { name: 'Boca completa' }).click()
    await expect(page.getByText('Usados recientemente')).toBeVisible({ timeout: 30_000 })

    // The panel opened on a list; the keyboard must not be covering it.
    const search = page.getByPlaceholder('Buscar un tratamiento o una plantilla')
    await expect(search).not.toBeFocused()

    // One query, both groups: a template to start from and the loose lines.
    await search.fill('endodoncia')
    await expect(page.getByText('Empezar el plan')).toBeVisible({ timeout: 30_000 })

    // The loose treatments come grouped by category, so "Tratamientos
    // sueltos" is a prefix repeated once per category — three of them for
    // this query — and matching it as bare text is ambiguous. The heading
    // carries a testid precisely so a test does not have to guess how many
    // there will be.
    const looseGroups = page.getByTestId('search-treatment-group')
    await expect(looseGroups.first()).toBeVisible()
    for (const heading of await looseGroups.allInnerTexts()) {
      // Case-insensitive: `.group-title` is uppercased in CSS, and
      // `allInnerTexts` reads what is rendered, not what is written.
      expect(heading).toMatch(/^Tratamientos sueltos · /i)
    }

    expect(await page.locator('.treatment-row').count()).toBeGreaterThan(1)

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the treatment search'
    ).toEqual([])
  })

  /**
   * Every line stays editable until the plan exists.
   *
   * The screen's own argument is that nothing is written until *Crear*, and
   * this is what that buys: a line drawn on the wrong tooth is corrected on
   * the chart that drew it, not by deleting the line and searching the
   * treatment out again. After *Crear* the same correction costs a Reabrir,
   * which throws a budget away — so the cheap window is worth pinning.
   *
   * Tooth-scoped on purpose (`REST-COMP`): a whole-mouth line has no teeth
   * to edit, so it could not fail this test and could not pass it either.
   */
  test('a drawn treatment can be moved to another tooth before the plan exists', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    await page.goto('/treatments/plans/new', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()

    const teeth = page.locator('main .tooth-cell')
    await expect(teeth.first()).toBeVisible({ timeout: 60_000 })
    await teeth.filter({ hasText: '16' }).first().click()

    await page.getByPlaceholder('Buscar un tratamiento o una plantilla')
      .fill('Obturación composite')
    const treatment = page.locator('.treatment-row')
      .filter({ hasText: 'Obturación composite' }).first()
    await expect(treatment).toBeVisible({ timeout: 30_000 })
    await treatment.click()

    const line = page.locator('.draft-line').first()
    await expect(line).toBeVisible()
    await expect(line.locator('.line-teeth')).toContainText('16')

    // Open the line's editor and hand the chart over to it.
    await line.getByRole('button', { name: /^Editar / }).click()
    await line.getByRole('button', { name: 'Elegir en el odontograma' }).click()
    await expect(page.getByText('Toca las piezas de')).toBeVisible()

    // Now a tap edits this line instead of opening the treatment panel.
    await teeth.filter({ hasText: '26' }).first().click()
    await expect(line.locator('.line-teeth')).toContainText('26')
    // ...and tapping the wrong one again takes it off.
    await teeth.filter({ hasText: '16' }).first().click()
    await expect(line.locator('.line-teeth')).not.toContainText('16')

    // Still one treatment: the chart edited the line, it did not add lines.
    await expect(page.locator('.draft-line')).toHaveCount(1)

    // A per-tooth line with no tooth left cannot be created, and says so
    // rather than failing at the server with a 422.
    await teeth.filter({ hasText: '26' }).first().click()
    await expect(page.getByText('Falta la pieza').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Continuar' })).toBeDisabled()

    // Putting a tooth back releases it.
    await teeth.filter({ hasText: '26' }).first().click()
    await expect(page.getByRole('button', { name: 'Continuar' })).toBeEnabled()

    // Faces are editable too, for a treatment the catalog describes by face.
    await line.getByRole('button', { name: 'Oclusal' }).click()
    await expect(line.locator('.line-teeth')).toContainText('O')

    expect(
      await countUndersizedTargets(page),
      'undersized targets while editing a draft line'
    ).toEqual([])
  })

  /**
   * The other side of that window: once the plan exists, the chart is shut.
   *
   * This is the boundary the editable-line test is worth having. A plan in
   * progress carries a budget the patient may have seen, so its odontogram
   * is read-only and a tap explains itself rather than doing nothing —
   * changing it means Reabrir, which cancels that budget.
   *
   * Reached through the `en_curso` bandeja, whose leading rows the demo seed
   * fills with plans that carry a budget (`seed-demo.sh`). The test asserts
   * the lock before it asserts anything about the tap, so a seed that ever
   * stops producing one fails loudly here instead of passing vacuously.
   */
  test('a plan in progress shuts its chart and says how to open it', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    // Asked of the API rather than picked off a list. The bandeja's own
    // tabs are not links — only "Listado" renders real hrefs, and its
    // first row is whatever is newest, which is as likely to be a draft.
    // The lock needs a specific pair (status pending|active *and* a live
    // budget), so the test names that pair instead of hoping for it.
    const planId = await findLockedPlanId(page)
    expect(planId, 'the seed has no plan in progress carrying a budget').toBeTruthy()

    await page.goto(`/treatments/plans/${planId}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    // "Plan confirmado", not "Plan bloqueado": the banner names the state
    // rather than shouting, and follows the plan's status now, not its budget.
    await expect(page.getByText('Plan confirmado')).toBeVisible({ timeout: 60_000 })

    // The chart says it is frozen...
    await expect(page.getByText('Solo lectura')).toBeVisible()

    // ...and a tap on it answers, instead of being swallowed. The banner is
    // a scroll above the chart, so without this the screen looks broken.
    const teeth = page.locator('main .tooth-cell')
    await expect(teeth.first()).toBeVisible({ timeout: 60_000 })
    await teeth.filter({ hasText: '11' }).first().click()
    // `exact` matters: a toast also renders a screen-reader announcement
    // that repeats the title inside a longer string, and a loose match
    // resolves to both.
    await expect(
      page.getByText('Odontograma bloqueado', { exact: true })
    ).toBeVisible({ timeout: 30_000 })

    // No treatment panel: the tap changed nothing, which is the point.
    await expect(page.getByText('Usados recientemente')).toHaveCount(0)
  })

  /**
   * The half that cannot be checked while the chart is blank.
   *
   * Choosing the patient last is the point of the screen, so the warning is
   * the only thing standing between a plan and a crown on a tooth that is
   * not there. It warns; it never refuses.
   */
  test('choosing the patient names the plan and flags what clashes', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    await page.goto('/treatments/plans/new', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    await expect(page.locator('main')).toBeVisible()

    // Tooth 36 and this patient both come from the seed: `seed-demo.sh
    // --lang es` gives María Teresa Romero Vega the `adult_with_implant`
    // chart, whose only missing tooth is 36. Picking a name and a tooth
    // that merely exist on a developer's database is what made this test
    // pass locally and fail in CI.
    const teeth = page.locator('main .tooth-cell')
    await expect(teeth.first()).toBeVisible({ timeout: 60_000 })
    await teeth.filter({ hasText: '36' }).first().click()

    // Searched by name, not `.treatment-row` first: that class is shared by
    // three lists in the panel — recents, templates and treatments — and
    // recents are ordered by what the clinic has used, so the first row is
    // whatever the history happens to put there. It has to be a *tooth*
    // treatment or `addTreatment` attaches no tooth (`teethFor` only fills
    // it for tooth/multi_tooth scope), the line lands on no tooth, and the
    // conflict this test is about never fires. `REST-COMP` is tooth-scoped
    // and comes from the catalog seed.
    await page.getByPlaceholder('Buscar un tratamiento o una plantilla')
      .fill('Obturación composite')
    const treatment = page.locator('.treatment-row')
      .filter({ hasText: 'Obturación composite' }).first()
    await expect(treatment).toBeVisible({ timeout: 30_000 })
    await treatment.click()

    await page.getByRole('button', { name: 'Continuar' }).click()
    // Unaccented on purpose — it is how a receptionist types, and the
    // search is accent-insensitive. "Romero Vega" matches this patient
    // alone; "Romero" alone also matches Francisco García Romero.
    await page.getByPlaceholder('Nombre o teléfono').fill('Romero Vega')
    const match = page.locator('main button').filter({ hasText: 'Romero Vega' }).first()
    await expect(match).toBeVisible({ timeout: 30_000 })
    await match.click()

    // The title writes itself from the patient, and stays editable.
    await expect(
      page.locator('input[value*="Plan de Tratamiento para"]')
    ).toBeVisible({ timeout: 30_000 })

    // The warning names the tooth, and Crear stays available underneath it.
    await expect(page.getByText('Revisa estas piezas antes de crear el plan')).toBeVisible()
    await expect(page.locator('.conflict-list')).toContainText('36')
    await expect(page.getByRole('button', { name: 'Crear', exact: true })).toBeEnabled()

    expect(
      await countUndersizedTargets(page),
      'undersized targets on the patient step'
    ).toEqual([])
  })

  /**
   * The till, which is the only finance tab that is a working surface rather
   * than a list.
   *
   * **Every assertion here is structural on purpose.** `seed-demo.sh` creates
   * no till movements and no arqueos — it cannot, because a count is
   * something a person does — so a test that expected a figure would pass on
   * a developer's database and fail in CI. What is asserted instead is that
   * the screen exists, that its controls are tappable, and that the one
   * product rule the whole feature rests on holds with no data at all.
   *
   * `cashbox` is `auto_install=True`, so it is mounted wherever the suite
   * runs. If that ever changes, this fails loudly on the first assertion
   * rather than skipping quietly.
   */
  test('the till counts before it reveals what it expected', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)

    await page.goto('/finanzas?tab=cashbox', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)

    // The tab is mounted through the `finance.tabs` slot, which registers
    // client-side — so this is the assertion that catches a module that
    // failed to mount, and it has to wait for hydration rather than assume.
    await expect(page.getByRole('tab', { name: 'Caja' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('Arqueo de caja')).toBeVisible({ timeout: 60_000 })

    // Counted on a day far older than anything the seed writes, rather than
    // on today. A developer's database has real arqueos in it, and a day
    // that happens to be counted already hides the button this test needs —
    // failing locally while passing in CI, which is the least useful shape
    // a failure can take. Nothing is ever counted on this date.
    await page.locator('input[type="date"]').first().fill('2020-01-06')
    await expect(page.getByRole('button', { name: 'Hacer el arqueo' })).toBeVisible({
      timeout: 30_000
    })

    // **The rule.** Show somebody "you should have 4.350" and then ask them
    // to count, and 4.350 is what they type: the difference reads zero every
    // day and a year of counts says nothing. The workings are on screen from
    // the start; the total they add up to appears only after a count.
    await page.getByRole('button', { name: 'Hacer el arqueo' }).click()
    const reveal = page.locator('.reveal')
    await expect(reveal).toHaveCount(0)

    await page.getByPlaceholder('Lo que hay en el cajón').fill('0')
    await expect(reveal).toHaveCount(1)
    await expect(reveal).toContainText('Esperado')

    expect(
      await countUndersizedTargets(page),
      'undersized targets while counting the till'
    ).toEqual([])
  })

  /**
   * The till's movement form, which route audits never open.
   *
   * Same reasoning as the accept-in-clinic dialog above: a dialog's controls
   * are invisible to a sweep of the page behind it, so the one surface
   * reception types into every day would go unaudited.
   */
  test('the till movement form meets the 44 px minimum', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)

    await page.goto('/finanzas?tab=cashbox', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)

    // Same old day, same reason: on a day this developer's database has
    // already counted, the button is gone and the form cannot open.
    await page.locator('input[type="date"]').first().fill('2020-01-06')
    await page.getByRole('button', { name: 'Registrar movimiento' }).click()
    await expect(page.getByText('Nuevo movimiento de caja')).toBeVisible({ timeout: 30_000 })
    // Not a stray sleep: the modal animates in with a scale transform, and
    // `getBoundingClientRect` mid-animation reports a 44 px control as 43.
    // The same wait is in the accept-in-clinic test above, for the same
    // reason — measuring a transform is measuring the animation.
    await page.waitForTimeout(1000)

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the till movement form'
    ).toEqual([])
  })

  /**
   * A treatment row stopped carrying its own links.
   *
   * It used to hold five targets a finger apart — a note button, a recall
   * button, a doctor chip, a tick and a bin — where the two that *open*
   * something looked exactly like the two that *change the plan*. The row
   * now keeps only what changes the plan; everything you open moved into a
   * dialog the row opens.
   */
  test('a treatment row opens a dialog instead of carrying its own links', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    // Reached through the list so the test does not name a plan: seeded ids
    // are not the ids of whatever database this runs against.
    // `listado` is the tab that renders real links to each plan; the
    // pipeline tabs are cards. The existing plan-detail audit reaches the
    // detail the same way.
    await page.goto('/treatments/plans?tab=listado', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    const firstRow = page.locator('main a[href*="/treatments/plans/"]').first()
    await expect(firstRow).toBeVisible({ timeout: 60_000 })
    const href = await firstRow.getAttribute('href')
    expect(href, 'no plan to open').toBeTruthy()

    await page.goto(href!, { waitUntil: 'domcontentloaded', timeout: 120_000 })
    await awaitDetection(page)
    const row = page.locator('main .plan-item').first()
    await expect(row).toBeVisible({ timeout: 60_000 })

    // Gone from the row: the two contributed by sibling modules.
    await expect(row.getByTitle('Programar recordatorio')).toHaveCount(0)
    await expect(row.getByLabel(/Notas del tratamiento/)).toHaveCount(0)

    await row.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 30_000 })
    // And present in the dialog's footer, as words rather than icons.
    await expect(dialog.getByRole('button', { name: /^(Añadir nota|Notas \(\d+\))$/ }))
      .toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Programar recordatorio' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Receta médica' })).toBeVisible()
    // The dialog opens with a scale animation; measure once it has settled.
    await page.waitForTimeout(1200)

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the treatment dialog'
    ).toEqual([])
  })

  /**
   * "Receta médica" opens its own dialog: the signing doctor, preselected
   * from the treatment and shown with their licence, and the text. It is
   * not submitted — generating a prescription writes a clinical record.
   */
  test('a treatment opens a prescription dialog', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)
    await page.route('**/prescriptions', (route) => {
      if (route.request().method() === 'POST') return route.abort()
      return route.continue()
    })

    await page.goto('/treatments/plans?tab=listado', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    const firstRow = page.locator('main a[href*="/treatments/plans/"]').first()
    await expect(firstRow).toBeVisible({ timeout: 60_000 })
    await page.goto((await firstRow.getAttribute('href'))!, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)
    const row = page.locator('main .plan-item').first()
    await expect(row).toBeVisible({ timeout: 60_000 })
    await row.click()

    await page.getByRole('dialog').getByRole('button', { name: 'Receta médica' }).click()
    const prescription = page.getByRole('dialog').filter({ hasText: 'Doctor que firma' })
    await expect(prescription).toBeVisible({ timeout: 30_000 })

    const generate = prescription.getByRole('button', { name: 'Generar receta' })
    await expect(generate).toBeDisabled()
    await prescription.getByRole('textbox').fill('Ibuprofeno 400 mg cada 8 horas')
    // Enabled once there is text — as long as the treatment names a doctor,
    // which the seeded plans do.
    await expect(generate).toBeEnabled()
    await page.waitForTimeout(1200)

    expect(
      await countUndersizedTargets(page),
      'undersized targets in the prescription dialog'
    ).toEqual([])
  })

  /**
   * Paid off, and therefore closed — derived from the ledger rather than
   * stored, so a refund recorded in Finanzas un-closes it with no second
   * write. Skipped rather than faked when the dataset has no such treatment:
   * it needs completed work that has also been collected.
   */
  test('a treatment that is paid off reads as closed and asks before reopening', async ({
    loggedIn: page
  }) => {
    test.setTimeout(180_000)

    await page.goto('/treatments/plans?tab=listado', {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    await awaitDetection(page)

    const links = page.locator('main a[href*="/treatments/plans/"]')
    await expect(links.first()).toBeVisible({ timeout: 60_000 })
    const hrefs = await links.evaluateAll(els =>
      els.map(el => (el as HTMLAnchorElement).getAttribute('href')).filter(Boolean)
    )

    for (const href of hrefs.slice(0, 10)) {
      await page.goto(href!, { waitUntil: 'domcontentloaded', timeout: 120_000 })
      await awaitDetection(page)
      await expect(page.locator('main')).toBeVisible()

      // Completed treatments live behind an accordion labelled with a count.
      const accordion = page.locator('main button', { hasText: /\(\d+\)/ }).first()
      if (await accordion.count() === 0) continue
      await accordion.click()
      await page.waitForTimeout(800)

      const closed = page.locator('main').getByText('Cerrado', { exact: true })
      if (await closed.count() === 0) continue

      // The badge sits inside the row, and the row is what opens the dialog.
      await closed.first().click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible({ timeout: 30_000 })
      await expect(dialog.getByText('Tratamiento cerrado')).toBeVisible()

      const reopen = dialog.getByRole('button', { name: 'Reabrir tratamiento' })
      await expect(reopen).toBeVisible()
      await reopen.click()
      // Reopening is a real undo — the item goes back to pending and its
      // charge is withdrawn — so it asks first. The test stops at the
      // question: answering it would write to the dataset.
      await expect(dialog.getByText('¿Reabrir este tratamiento?')).toBeVisible()
      await expect(dialog.getByRole('button', { name: 'Sí, reabrir' })).toBeVisible()
      await dialog.getByRole('button', { name: 'Cancelar' }).click()
      await expect(dialog.getByText('Tratamiento cerrado')).toBeVisible()
      return
    }

    test.skip(true, 'no completed-and-collected treatment in this dataset')
  })

  /**
   * The patient-facing budget page, which is the one surface here that a
   * patient touches on their own phone or tablet — and the one this audit
   * had never covered. It is where a treatment plan is accepted and signed,
   * so an unreachable control there is not a papercut.
   *
   * Nothing is hardcoded: the seed mints a random `public_token` on every
   * run, so a literal would pass locally and fail in CI. The token, the
   * patient and the verification digits are all discovered through the API
   * the logged-in session already has.
   *
   * Opening the page marks the budget as viewed — that is what the product
   * does for any visit, and it is the only trace this test leaves. It never
   * accepts or rejects: both are blocked at the network as well as unclicked.
   */
  test('the public budget page meets the 44 px minimum', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)

    await page.route('**/public/budgets/*/accept', route => route.abort())
    await page.route('**/public/budgets/*/reject', route => route.abort())

    const apiBase = process.env.API_BASE_URL || 'http://localhost:8000'
    const headers = { Authorization: `Bearer ${await tokenFor(page)}` }

    const list = await page.request.get(
      `${apiBase}/api/v1/budget/budgets?status=sent&page_size=1`,
      { headers }
    )
    expect(list.ok(), 'budget list unavailable').toBeTruthy()
    const row = (await list.json()).data?.[0]
    if (!row) {
      // A budget has to be *sent* to have a patient-facing page at all.
      test.skip(true, 'no budget in sent status in this dataset')
    }

    const detail = await page.request.get(
      `${apiBase}/api/v1/budget/budgets/${row.id}`,
      { headers }
    )
    const publicToken = (await detail.json()).data?.public_token
    expect(publicToken, 'sent budget without a public token').toBeTruthy()

    const patient = await page.request.get(
      `${apiBase}/api/v1/patients/${row.patient.id}`,
      { headers }
    )
    const digits = String((await patient.json()).data?.phone ?? '').replace(/\D/g, '')
    if (digits.length < 4) {
      test.skip(true, 'patient has no phone to verify against')
    }

    // 1. The gate.
    await page.goto(`/p/budget/${publicToken}`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    const last4 = page.getByPlaceholder('1234')
    await expect(last4).toBeVisible({ timeout: 60_000 })
    expect(
      await countUndersizedTargets(page),
      'undersized targets on the budget verification gate'
    ).toEqual([])

    // 2. The budget itself.
    await last4.fill(digits.slice(-4))
    await page.getByRole('button', { name: 'Continuar' }).click()
    await expect(page.getByRole('button', { name: 'Aceptar y firmar' }))
      .toBeVisible({ timeout: 60_000 })
    expect(
      await countUndersizedTargets(page),
      'undersized targets on the public budget'
    ).toEqual([])

    // 3. The signing dialog — the consent checkbox lives here, and it is
    //    what gates the signature.
    await page.getByRole('button', { name: 'Aceptar y firmar' }).click()
    await expect(page.getByLabel('Tu nombre completo')).toBeVisible({ timeout: 30_000 })
    // The dialog opens with a scale transform, and a 44px control measures
    // 43 while it is still growing. Measure the layout, not the animation.
    await page.waitForTimeout(1200)
    expect(
      await countUndersizedTargets(page),
      'undersized targets in the accept-and-sign dialog'
    ).toEqual([])
  })

  /**
   * The budget page's cold states: rejected, expired, locked out.
   *
   * They are the screens a patient meets when something has gone wrong, so
   * they are the ones nobody looks at — and the only control on them is the
   * "call the clinic" button, which is the whole point of the screen.
   *
   * `expired` and `locked` are flags on the `meta` call, so they are
   * produced by answering that one call differently. **No budget is
   * altered to see them**: making a real one expire or locking a real link
   * would leave a patient's record in a state this test invented.
   */
  test('the budget page cold states meet the 44 px minimum', async ({ loggedIn: page }) => {
    test.setTimeout(180_000)

    const apiBase = process.env.API_BASE_URL || 'http://localhost:8000'
    const headers = { Authorization: `Bearer ${await tokenFor(page)}` }

    /** The public token of the first budget in one of the given statuses.
     *  Named apart from the imported `tokenFor`: a function declaration
     *  shadows the import for the whole test, and the Authorization
     *  header above was handing this one a `Page`. */
    async function publicTokenFor(statuses: string[]): Promise<string | null> {
      const query = statuses.map(s => `status=${s}`).join('&')
      const list = await page.request.get(
        `${apiBase}/api/v1/budget/budgets?${query}&page_size=1`,
        { headers }
      )
      if (!list.ok()) return null
      const row = (await list.json()).data?.[0]
      if (!row) return null
      const detail = await page.request.get(`${apiBase}/api/v1/budget/budgets/${row.id}`, { headers })
      return (await detail.json()).data?.public_token ?? null
    }

    // Rejected is a real state of a real budget; nothing to simulate.
    const rejected = await publicTokenFor(['rejected'])
    if (rejected) {
      await page.goto(`/p/budget/${rejected}`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000
      })
      await expect(page.getByText('Llamar a la clínica'))
        .toBeVisible({ timeout: 60_000 })
      expect(
        await countUndersizedTargets(page),
        'undersized targets on a rejected budget'
      ).toEqual([])
    }

    const anyToken = rejected ?? await publicTokenFor(['sent', 'accepted', 'completed'])
    if (!anyToken) {
      test.skip(true, 'no budget with a public link in this dataset')
    }

    for (const flag of ['expired', 'locked'] as const) {
      await page.route('**/public/budgets/*/meta', async (route) => {
        const response = await route.fetch()
        const body = await response.json()
        // `requires_verification` off as well: a cold state never asks the
        // patient to prove who they are first.
        body.data = { ...body.data, [flag]: true, requires_verification: false }
        await route.fulfill({ response, json: body })
      })

      await page.goto(`/p/budget/${anyToken}`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000
      })
      await expect(page.getByText('Llamar a la clínica'))
        .toBeVisible({ timeout: 60_000 })
      expect(
        await countUndersizedTargets(page),
        `undersized targets on a ${flag} budget`
      ).toEqual([])

      await page.unroute('**/public/budgets/*/meta')
    }
  })

  /**
   * The five list toolbars, which share `FilterBar`.
   *
   * `FilterBar` collapses its chips to a "Filtros" button when they stop
   * fitting, precisely so they never cover the sort control pinned to the
   * right. It did the opposite on a tablet held upright: the chips region
   * is `flex-1 min-w-0`, so it shrank to ~8px while the button inside it
   * stayed 78px wide and spilled over the sort.
   *
   * Controls, not text: the labels sit in buttons that also hold an icon,
   * so a text-node sweep finds no leaf carrying them and reports nothing.
   */
  const LIST_ROUTES = [
    ['patients', '/patients'],
    ['professionals', '/professionals'],
    ['payments', '/finanzas?tab=payments'],
    ['budgets', '/finanzas?tab=budget'],
    ['invoices', '/finanzas?tab=billing']
  ] as const

  for (const [name, route] of LIST_ROUTES) {
    test(`the ${name} toolbar never overlaps its own controls`, async ({ loggedIn: page }) => {
      test.setTimeout(120_000)

      // The squeeze that matters is the canvas width, not the viewport,
      // and the rail is what decides it. Left to auto-collapse, an
      // upright tablet leaves ~736px and everything fits; expanded — the
      // user's choice, remembered in localStorage — the canvas drops to
      // ~555px and the toolbar has to cope. Narrowing the viewport
      // instead would prove nothing: below `md` the chips region is not
      // rendered at all, so the crowded layout never happens.
      await page.addInitScript(() => {
        localStorage.setItem('sidebar:collapsed', 'false')
      })

      await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 120_000 })
      await awaitDetection(page)
      await expect(page.locator('main')).toBeVisible()
      // FilterBar decides the collapse from a ResizeObserver, so the
      // assertion has to wait for that to settle, not just for paint.
      await page.waitForTimeout(2500)

      const overlaps = await page.evaluate(() => {
        const main = document.querySelector('main') || document.body
        const controls = [
          ...main.querySelectorAll('button,[role="combobox"],input,select')
        ]
          .map(el => ({ el, r: el.getBoundingClientRect() }))
          .filter(
            c =>
              c.r.width > 0
              && c.r.height > 0
              && getComputedStyle(c.el).visibility !== 'hidden'
          )

        const found: string[] = []
        for (let i = 0; i < controls.length; i++) {
          for (let j = i + 1; j < controls.length; j++) {
            const a = controls[i]!
            const b = controls[j]!
            // A control inside another (icon in a button) is not a clash.
            if (a.el.contains(b.el) || b.el.contains(a.el)) continue
            // Nor is an affordance sitting inside a field — a clear "x",
            // a reveal toggle. `contains` cannot see those: an <input>
            // has no DOM children, so the button is a sibling drawn on
            // top of it on purpose.
            const nested = (outer: DOMRect, inner: DOMRect) =>
              inner.left >= outer.left - 1
              && inner.right <= outer.right + 1
              && inner.top >= outer.top - 1
              && inner.bottom <= outer.bottom + 1
            const isField = (el: Element) => el.tagName === 'INPUT'
            if (isField(a.el) && nested(a.r, b.r)) continue
            if (isField(b.el) && nested(b.r, a.r)) continue
            const hit
              = a.r.left < b.r.right - 1
                && b.r.left < a.r.right - 1
                && a.r.top < b.r.bottom - 1
                && b.r.top < a.r.bottom - 1
            if (hit) {
              const label = (el: Element) =>
                (el.textContent || (el as HTMLInputElement).placeholder || el.tagName)
                  .trim()
                  .slice(0, 20)
              found.push(`${label(a.el)} x ${label(b.el)}`)
            }
          }
        }
        return found
      })

      expect(overlaps, `overlapping controls on ${route}: ${overlaps.join(', ')}`).toEqual([])
    })
  }
})
