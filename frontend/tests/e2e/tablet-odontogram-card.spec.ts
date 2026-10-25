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
 * Nothing is saved: the test presses a finding and cancels, and checks
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

    // A finding pressed stays pending; Cancel drops it.
    await page.getByTestId('tooth-finding-diastema').tap()
    await expect(page.getByTestId('tooth-diagnosis-pending')).toBeVisible()
    await page.getByTestId('tooth-diagnosis-cancel').tap()
    await expect(card).toBeHidden()
    expect(await countTreatments(), 'cancel saved something').toBe(before)
  })
})
