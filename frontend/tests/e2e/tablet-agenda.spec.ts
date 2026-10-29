import type { Locator, Page } from '@playwright/test'
import { dayWithAppointment, expect, test } from './_fixtures'

/**
 * The agenda's touch gestures, run in both tablet orientations.
 *
 * These are the flows that were outright impossible before: the grids
 * drove create/move/resize from `mousedown` plus document `mousemove`,
 * and the kanban from HTML5 drag-and-drop. Chrome on Android delivers
 * neither while a finger is moving.
 *
 * Note on the input used here: the tablet projects run with a coarse
 * pointer, which is what the app branches on, while Playwright's mouse
 * API is what can express a press-hold-move-release sequence. The
 * synthetic input still arrives as pointer events, so this exercises the
 * touch state machine — select-then-drag, long-press, click suppression
 * — even though the pointer type is "mouse".
 *
 * Writes are intercepted rather than allowed through: these run against
 * the shared seeded database, and a test that nudges an appointment two
 * slots later on every run drifts the fixture out from under itself.
 * Observing the request is the assertion.
 */

async function awaitDetection(page: Page): Promise<void> {
  await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 60_000 })
}

/**
 * Navigate, tolerating one `net::ERR_ABORTED`.
 *
 * Vite discovers a dependency on the first visit to a route and answers
 * with a full page reload, which races Playwright's own navigation — the
 * same behaviour `nuxt.config.ts` calls out around `optimizeDeps.include`.
 * It can only happen once per dep, so a single retry settles it.
 */
async function gotoAgenda(page: Page, path = '/appointments'): Promise<void> {
  for (const attempt of [1, 2]) {
    try {
      await page.goto(path, { waitUntil: 'domcontentloaded' })
      return
    } catch (error) {
      if (attempt === 2 || !String(error).includes('ERR_ABORTED')) throw error
    }
  }
}

async function openAgenda(page: Page, path = '/appointments'): Promise<void> {
  await gotoAgenda(page, path)
  await awaitDetection(page)
  await expect(page.locator('html')).toHaveAttribute('data-pointer', 'coarse')
  // Wait for the grid itself, not for a duration: the view components are
  // async chunks and a cold dev server compiles them on first request,
  // which a fixed sleep loses to.
  await page.waitForSelector('[data-dense]', { timeout: 60_000 })
  // Populated, not merely present: the grid paints its frame before the
  // day's data arrives, and a cell is what every test here goes on to
  // click, drag or count. The 1.5 s sleep this replaces was a guess that
  // CI lost — twice.
  await expect(page.locator('[data-dense] .cursor-cell').first()).toBeVisible({ timeout: 60_000 })
}

/**
 * Press and hold over an element, using `hover()` to place the pointer —
 * it scrolls the element into view and picks a point that is actually
 * hittable, which hand-computed coordinates are not once a grid is
 * scrolled sideways in portrait.
 */
async function longPress(page: Page, target: Locator, until?: () => Promise<unknown>): Promise<void> {
  await target.scrollIntoViewIfNeeded()
  await target.hover()
  await page.mouse.down()
  if (until) {
    // Hold until the app says the press registered, rather than for a fixed
    // 500 ms against a 300 ms threshold. The margin looks generous and is
    // not: the timer is a `setTimeout`, and a busy dev server can run it
    // late — releasing first turns the long press into a plain click, which
    // opens the appointment instead of selecting it.
    await until()
    return
  }
  await page.waitForTimeout(500)
}

/** Selected: `touch-action: none` is what stops the browser scrolling instead
 *  of dragging on the next press, so it is also the proof the press landed. */
function selected(target: Locator): Promise<unknown> {
  return expect(target).toHaveCSS('touch-action', 'none', { timeout: 15_000 })
}

/** The first appointment block rendered in the week grid. */
function firstBlock(page: Page): Locator {
  return page.locator('[data-dense] .group.absolute').first()
}

// A cold dev server compiles these routes on first request.
test.describe.configure({ timeout: 120_000 })

test.describe('agenda by touch', () => {
  test('a long press selects an appointment instead of opening it', async ({ loggedIn: page }) => {
    // Portrait defaults to the day view, so land on a day that has one.
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)

    const block = firstBlock(page)
    await expect(block).toBeVisible()

    await longPress(page, block, () => selected(block))
    await page.mouse.up()

    // Still selected after the release — the point of the gesture.
    await expect(block).toHaveCSS('touch-action', 'none')

    // And the release did not also open the appointment.
    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('dragging a selected appointment reschedules it', async ({ loggedIn: page }) => {
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)

    const block = firstBlock(page)
    await expect(block).toBeVisible()

    await longPress(page, block, () => selected(block))
    await page.mouse.up()
    await expect(block).toHaveCSS('touch-action', 'none')

    // Keep the fixture intact: observe the write, do not perform it.
    await page.route('**/api/v1/agenda/appointments/*', route =>
      route.request().method() === 'PUT' ? route.abort() : route.continue()
    )
    const savePromise = page.waitForRequest(
      req => req.method() === 'PUT' && /\/api\/v1\/agenda\/appointments\/[0-9a-f-]+$/.test(req.url()),
      { timeout: 15_000 }
    )

    const box = (await block.boundingBox())!
    const x = box.x + box.width / 2
    // Near the top edge, not the centre: the bottom of a selected block is
    // the resize handle, and on a thirty-minute block the centre sits 8 px
    // above it. CI lost that margin to a reflow and the gesture resized
    // instead — a write of `end_time` alone, which is what this asserted on.
    const y = box.y + Math.min(8, box.height / 4)
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.mouse.move(x, y + 30, { steps: 5 })
    await page.mouse.move(x, y + 56, { steps: 5 })
    await page.mouse.up()

    const request = await savePromise
    expect(request.postDataJSON()).toHaveProperty('start_time')
  })

  test('a narrow portrait tablet still gets the agenda, not the phone list', async ({ loggedIn: page }) => {
    // Reported from a real device: a tablet held upright reports fewer
    // than 768 CSS px, so the old `isMobile` width rule handed it the
    // phone day-list. The portrait project is 800 px wide and sailed
    // over that threshold, which is why the suite missed it. 720x1152 is
    // a real tablet shape that lands under it.
    await page.setViewportSize({ width: 720, height: 1152 })
    await openAgenda(page)

    // The grid is present...
    await expect(page.locator('[data-dense]').first()).toBeVisible()
    // ...and the phone list, identified by its min-duration chips, is not.
    await expect(page.getByText(/Mínimo/)).toHaveCount(0)
  })

  test('the day grid fits across an upright tablet instead of running off it', async ({ loggedIn: page }) => {
    // The companion to the test above. Portrait defaults to the day view
    // *because* a seven-day week does not fit across a tablet held
    // upright — but the day grid asked for a flat 200 px per
    // professional, so a five-professional clinic demanded 1080 px
    // against the ~620 px it actually had and nearly half the day sat
    // off the right edge. Landscape has 1168 px and hid the bug.
    await page.setViewportSize({ width: 720, height: 1152 })
    await openAgenda(page)

    await expect(page.getByRole('tab', { name: 'Día', exact: true }))
      .toHaveAttribute('aria-selected', 'true')

    const geometry = await page.evaluate(() => {
      const grid = document.querySelector('[data-dense]')!
      const scroller = grid.closest('.overflow-auto')!
      // The header row: one time gutter plus one cell per professional.
      const header = grid.firstElementChild!
      const columns = [...header.children].slice(1)
      return {
        available: scroller.clientWidth,
        needed: scroller.scrollWidth,
        columnWidths: columns.map(c => Math.round(c.getBoundingClientRect().width))
      }
    })

    // Nothing off the right edge.
    expect(geometry.needed, 'the day grid must fit the width an upright tablet has')
      .toBeLessThanOrEqual(geometry.available)

    // ...and not by shrinking the columns into illegibility, which is the
    // other way this assertion could be satisfied. A column still has to
    // hold a card's time and a first name.
    expect(geometry.columnWidths.length).toBeGreaterThan(0)
    expect(Math.min(...geometry.columnWidths), 'professional columns must stay readable')
      .toBeGreaterThanOrEqual(100)
  })

  test('tapping an empty slot opens the create modal', async ({ loggedIn: page }) => {
    await openAgenda(page)

    // Wait for the grid to be filled, not for a duration: the cells only
    // exist once the professionals have loaded, and each one is a column.
    // A fixed index into them was a bet on how many there would be — 121
    // of an expected 132 — and it lost on CI, where the grid was still
    // empty. The last cell is the latest slot of the last column, which
    // is also the least likely to have an appointment sitting on it.
    const cells = page.locator('[data-dense] .cursor-cell')
    await expect(cells.first()).toBeVisible({ timeout: 30_000 })
    expect(await cells.count(), 'the day grid should have slots to tap').toBeGreaterThan(20)

    // ...but not one sitting under the corner other Apps put their
    // agenda shortcuts in (`agenda.calendar.subscribe`): those buttons
    // sit over the last hours of the last column and take the tap, so
    // the slot underneath never hears it. The slot entries arrive
    // asynchronously, so the corner is measured after the grid has been
    // scrolled to where the tap is going, not before.
    await cells.last().scrollIntoViewIfNeeded()
    const corner = page.locator('[data-agenda-corner] > *').first()
    const obstruction = await corner.count() ? await corner.boundingBox() : null
    const cell = await (async () => {
      for (let i = await cells.count() - 1; i >= 0; i--) {
        const candidate = cells.nth(i)
        const box = await candidate.boundingBox()
        if (!box) continue
        const covered = obstruction
          && box.x < obstruction.x + obstruction.width
          && box.x + box.width > obstruction.x
          && box.y < obstruction.y + obstruction.height
          && box.y + box.height > obstruction.y
        if (!covered) return candidate
      }
      throw new Error('every slot of the day grid is covered')
    })()
    await cell.scrollIntoViewIfNeeded()
    await cell.click()

    // The create modal specifically: tapping an appointment opens the
    // edit one, and both are dialogs.
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog.getByText(/Nueva cita|New appointment/i).first()).toBeVisible()
  })

  test('the kanban lays out for the orientation it is held in', async ({ loggedIn: page }) => {
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)
    await page.getByRole('tab', { name: 'Kanban', exact: true }).click()
    await page.waitForSelector('[data-kanban-column]', { timeout: 30_000 })
    await page.waitForTimeout(1500)

    const portrait = page.viewportSize()!.height > page.viewportSize()!.width
    const board = page.locator('[data-kanban-column]').first().locator('..')

    // Five columns need 1320 px. Landscape has it and scrolls sideways;
    // portrait does not, and wraps into two so the height it does have
    // is used instead.
    const columns = await board.evaluate(el => getComputedStyle(el).gridTemplateColumns.split(' ').length)
    expect(columns, portrait ? 'portrait should wrap to two columns' : 'landscape should keep five')
      .toBe(portrait ? 2 : 5)

    // Either way the page itself must not overflow sideways.
    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    )
    expect(overflow).toBeLessThanOrEqual(2)
  })

  test('a kanban card follows the pointer after a long press', async ({ loggedIn: page }) => {
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)
    await page.getByRole('tab', { name: 'Kanban', exact: true }).click()
    await page.waitForTimeout(3000)

    const card = page.locator('[data-kanban-column] .group.relative').first()
    await expect(card).toBeVisible()

    await longPress(page, card)

    // The ghost is the proof the drag began: under HTML5 drag-and-drop
    // nothing at all happened by touch, so nothing followed the pointer.
    const ghost = page.locator('body > div.pointer-events-none.fixed')
    await expect(ghost).toBeVisible()
    const startBox = (await ghost.boundingBox())!

    await page.mouse.move(startBox.x + 200, startBox.y + 60, { steps: 10 })
    const movedBox = (await ghost.boundingBox())!
    expect(movedBox.x).toBeGreaterThan(startBox.x)

    // Release over the page chrome, outside any column: a cancelled drag,
    // so the appointment's status is left alone.
    await page.mouse.move(4, 4, { steps: 5 })
    await page.mouse.up()
    await expect(ghost).toHaveCount(0)
  })

  test('a kanban card picked up and put back does not open', async ({ loggedIn: page }) => {
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)
    await page.getByRole('tab', { name: 'Kanban', exact: true }).click()
    await page.waitForTimeout(3000)

    const card = page.locator('[data-kanban-column] .group.relative').first()
    await expect(card).toBeVisible()

    // Hold until the drag has begun, then let go on the spot: the user
    // changed their mind. The release still fires a click on the card.
    const ghost = page.locator('body > div.pointer-events-none.fixed')
    await longPress(page, card, () => expect(ghost).toBeVisible({ timeout: 15_000 }))
    await page.mouse.up()
    await expect(ghost).toHaveCount(0)

    await expect(page.getByRole('dialog')).toHaveCount(0)
  })

  test('a tapped kanban card still opens', async ({ loggedIn: page }) => {
    await openAgenda(page, `/appointments?date=${await dayWithAppointment(page)}`)
    await page.getByRole('tab', { name: 'Kanban', exact: true }).click()
    await page.waitForTimeout(3000)

    const card = page.locator('[data-kanban-column] .group.relative').first()
    await expect(card).toBeVisible()

    // The other side of the rule above: only a pick-up swallows the click.
    await card.click()
    await expect(page.getByRole('dialog')).toBeVisible({ timeout: 10_000 })
  })
})
