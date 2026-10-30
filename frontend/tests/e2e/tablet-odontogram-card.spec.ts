import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * The tooth diagnosis card on a tablet, held either way (the
 * `tablet-landscape` and `tablet-portrait` projects run it).
 *
 * A tap on a tooth opens the card: the anatomical chart shrinks to the
 * card's width without scrolling sideways, the card fits the screen with
 * Accept and Cancel in reach, its controls (outside the dense chart) are
 * finger-sized, and a tap on another tooth picks it too.
 *
 * Undo, Redo and Clear step through what is pending.
 *
 * Nothing is saved: the test presses findings and cancels, and checks
 * through the API that the patient's chart did not change.
 */
test.describe('tooth diagnosis card on a tablet', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 240_000 })

  test('fits the screen, picks teeth by touch and cancels cleanly', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, { headers: auth })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id
    expect(patientId, 'the seed has no patients').toBeTruthy()

    const treatmentsUrl = `${API_BASE}/api/v1/odontogram/patients/${patientId}/treatments?page_size=100`
    const countTreatments = async () => {
      const res = await page.request.get(treatmentsUrl, { headers: auth })
      return ((await res.json()) as { data: unknown[] }).data.length
    }
    const before = await countTreatments()

    await page.goto(`/patients/${patientId}?tab=clinical&clinicalMode=diagnosis`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    const firstTooth = page.locator('.odontogram-grid .tooth-dual-view-wrapper').first()
    await firstTooth.waitFor({ state: 'visible', timeout: 120_000 })
    await firstTooth.locator('svg.lateral-view').tap()

    const card = page.getByTestId('tooth-diagnosis-modal')
    await expect(card).toBeVisible({ timeout: 30_000 })

    // The arches shrink to the card instead of scrolling sideways.
    const chart = card.locator('.diagnosis-chart')
    const teeth = card.locator('.tooth-dual-view-wrapper')
    expect(await teeth.count()).toBeGreaterThan(0)
    const overflow = await chart.evaluate(el => el.scrollWidth - el.clientWidth)
    expect(overflow, 'the card chart scrolls sideways').toBeLessThanOrEqual(1)

    // The card fits the screen; its footer is in reach without scrolling.
    const box = await card.boundingBox()
    const viewport = page.viewportSize()!
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport.height + 1)
    await expect(page.getByTestId('tooth-diagnosis-accept')).toBeInViewport()
    await expect(page.getByTestId('tooth-diagnosis-cancel')).toBeInViewport()

    // Finger-sized controls everywhere but the dense chart.
    const undersized = await card.evaluate((root) => {
      const small: string[] = []
      for (const el of root.querySelectorAll('button')) {
        if (el.closest('[data-dense]')) continue
        const r = el.getBoundingClientRect()
        if (r.width === 0 || r.height === 0) continue
        if (r.width < 44 || r.height < 44) {
          small.push(`${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)} ${Math.round(r.width)}x${Math.round(r.height)}`)
        }
      }
      return small
    })
    expect(undersized).toEqual([])

    // A tap on another tooth of the card's chart picks it too.
    await expect(page.getByTestId('tooth-diagnosis-picked')).toContainText('1')
    await teeth.nth(3).locator('svg.lateral-view').tap()
    await expect(page.getByTestId('tooth-diagnosis-picked')).toContainText('2')
    await expect(page.getByTestId('tooth-diagnosis-title')).toContainText(',')

    // A finding pressed stays pending; Undo, Redo and Clear step through
    // what is pending; Cancel drops it.
    const pending = page.getByTestId('tooth-diagnosis-pending')
    await expect(page.getByTestId('tooth-diagnosis-undo')).toBeDisabled()
    await page.getByTestId('tooth-finding-diastema').tap()
    await expect(pending).toBeVisible()
    await page.getByTestId('tooth-diagnosis-undo').tap()
    await expect(pending).toBeHidden()
    await page.getByTestId('tooth-diagnosis-redo').tap()
    await expect(pending).toBeVisible()
    await page.getByTestId('tooth-finding-crowding').tap()
    await page.getByTestId('tooth-diagnosis-clear').tap()
    await expect(pending).toBeHidden()
    await expect(page.getByTestId('tooth-diagnosis-redo')).toBeDisabled()
    await page.getByTestId('tooth-diagnosis-undo').tap()
    await expect(pending).toBeVisible()
    await page.getByTestId('tooth-diagnosis-cancel').tap()
    await expect(card).toBeHidden()
    expect(await countTreatments(), 'cancel saved something').toBe(before)
  })

  /**
   * Reopened on a tooth already diagnosed, the card has nothing pending, so
   * *Deshacer* and *Rehacer* are rightly dead. *Vaciar* is the one that has
   * work to do there: it takes off what is charted, as one pending step.
   */
  test('empties a tooth already diagnosed, as a pending step', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, { headers: auth })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id
    expect(patientId, 'the seed has no patients').toBeTruthy()

    const treatmentsUrl = `${API_BASE}/api/v1/odontogram/patients/${patientId}/treatments?page_size=100`
    const treatmentIds = async () => {
      const res = await page.request.get(treatmentsUrl, { headers: auth })
      return ((await res.json()) as { data: { id: string }[] }).data.map(tr => tr.id)
    }
    const before = await treatmentIds()

    try {
      await page.goto(`/patients/${patientId}?tab=clinical&clinicalMode=diagnosis`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000
      })
      const firstTooth = page.locator('.odontogram-grid .tooth-dual-view-wrapper').first()
      await firstTooth.waitFor({ state: 'visible', timeout: 120_000 })
      const card = page.getByTestId('tooth-diagnosis-modal')
      const pending = page.getByTestId('tooth-diagnosis-pending')
      const clear = page.getByTestId('tooth-diagnosis-clear')

      // Chart something, so the reopened card has a diagnosis to empty.
      await firstTooth.locator('svg.lateral-view').tap()
      await expect(card).toBeVisible({ timeout: 30_000 })
      await expect(clear, 'a tooth with nothing on it has nothing to empty').toBeDisabled()
      await page.getByTestId('tooth-finding-diastema').tap()
      await page.getByTestId('tooth-diagnosis-accept').tap()
      await expect(card).toBeHidden({ timeout: 30_000 })
      await expect.poll(treatmentIds, { timeout: 20_000 }).toHaveLength(before.length + 1)

      // Reopened: nothing pending, so only *Vaciar* has anything to do.
      await firstTooth.locator('svg.lateral-view').tap()
      await expect(card).toBeVisible({ timeout: 30_000 })
      await expect(pending).toBeHidden()
      await expect(page.getByTestId('tooth-diagnosis-undo')).toBeDisabled()
      await expect(page.getByTestId('tooth-diagnosis-redo')).toBeDisabled()
      await expect(clear).toBeEnabled()

      await clear.tap()
      await expect(pending).toBeVisible()
      await expect(page.getByTestId('tooth-finding-diastema')).toHaveAttribute('data-active', 'false')

      // One step, undoable, and saved only on *Aceptar*.
      await page.getByTestId('tooth-diagnosis-undo').tap()
      await expect(pending).toBeHidden()
      await expect(page.getByTestId('tooth-finding-diastema')).toHaveAttribute('data-active', 'true')
      await page.getByTestId('tooth-diagnosis-cancel').tap()
      await expect(card).toBeHidden()
      expect(await treatmentIds(), 'emptying saved by itself').toHaveLength(before.length + 1)
    } finally {
      for (const id of (await treatmentIds()).filter(id => !before.includes(id))) {
        await page.request.delete(`${API_BASE}/api/v1/odontogram/treatments/${id}`, { headers: auth })
      }
    }
  })

  /**
   * The card's *Deshacer* only walks what is pending. Once saved, Ctrl+Z was
   * the only way back — and a tablet has no Ctrl+Z, which is what made the
   * clinic report undo as broken. The save's own toast offers it instead.
   */
  test('takes a saved diagnosis back off from its toast', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, { headers: auth })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id
    expect(patientId, 'the seed has no patients').toBeTruthy()

    const treatmentsUrl = `${API_BASE}/api/v1/odontogram/patients/${patientId}/treatments?page_size=100`
    const treatmentIds = async () => {
      const res = await page.request.get(treatmentsUrl, { headers: auth })
      return ((await res.json()) as { data: { id: string }[] }).data.map(tr => tr.id)
    }
    const before = await treatmentIds()

    try {
      await page.goto(`/patients/${patientId}?tab=clinical&clinicalMode=diagnosis`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000
      })
      const firstTooth = page.locator('.odontogram-grid .tooth-dual-view-wrapper').first()
      await firstTooth.waitFor({ state: 'visible', timeout: 120_000 })
      await firstTooth.locator('svg.lateral-view').tap()

      const card = page.getByTestId('tooth-diagnosis-modal')
      await expect(card).toBeVisible({ timeout: 30_000 })
      await page.getByTestId('tooth-finding-diastema').tap()
      await page.getByTestId('tooth-diagnosis-accept').tap()

      // The toast lives ~5 s: take hold of its button before anything else.
      const undo = page.getByRole('button', { name: /deshacer|undo/i }).last()
      await expect(undo).toBeVisible({ timeout: 30_000 })
      const size = (await undo.boundingBox())!
      expect(size.height, 'the toast undo is not finger-sized').toBeGreaterThanOrEqual(44)
      await undo.tap()

      await expect.poll(treatmentIds, { timeout: 20_000 }).toEqual(before)
    } finally {
      // Whatever failed, the demo patient keeps no work this test charted.
      for (const id of (await treatmentIds()).filter(id => !before.includes(id))) {
        await page.request.delete(`${API_BASE}/api/v1/odontogram/treatments/${id}`, { headers: auth })
      }
    }
  })
})
