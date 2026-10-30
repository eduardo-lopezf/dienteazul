import { API_BASE, countUndersizedTargets, expect, test, tokenFor } from './_fixtures'

/**
 * The surface picker and the eruption card, the two screens the tooth
 * diagnosis card hands off to. Both leave the card, so a sweep of the page
 * behind it never reached them, and a caries — the most charted diagnosis
 * there is — goes through the first one every time.
 */
test.describe('what the diagnosis card hands off to, on a tablet', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 240_000 })

  async function openCard(page: import('@playwright/test').Page, patientId: string) {
    await page.goto(`/patients/${patientId}?tab=clinical&clinicalMode=diagnosis`, {
      waitUntil: 'domcontentloaded',
      timeout: 120_000
    })
    const firstTooth = page.locator('.odontogram-grid .tooth-dual-view-wrapper').first()
    await firstTooth.waitFor({ state: 'visible', timeout: 120_000 })
    await firstTooth.locator('svg.lateral-view').tap()
    await expect(page.getByTestId('tooth-diagnosis-modal')).toBeVisible({ timeout: 30_000 })
  }

  test('picks surfaces by touch, on the tooth and on the letters', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, { headers: auth })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id
    expect(patientId, 'the seed has no patients').toBeTruthy()

    const treatmentsUrl = `${API_BASE}/api/v1/odontogram/patients/${patientId}/treatments?page_size=100`
    const treatments = async () => {
      const res = await page.request.get(treatmentsUrl, { headers: auth })
      return (await res.json()) as {
        data: { id: string, clinical_type: string, teeth?: { surfaces?: string[] }[] }[]
      }
    }
    const before = (await treatments()).data.map(t => t.id)

    try {
      await openCard(page, patientId)
      await page.getByTestId('tooth-finding-caries').tap()

      const picker = page.getByTestId('surface-selector')
      await expect(picker, 'caries did not reach the surface picker').toBeVisible({ timeout: 30_000 })
      // Polled, not measured once: a modal opens with a scale animation,
      // and a box read mid-flight is 0.3 % short of what it settles at —
      // enough to report a 44 px control as 43.9.
      await expect
        .poll(() => countUndersizedTargets(page, '[data-testid="surface-selector"]'), { timeout: 10_000 })
        .toEqual([])

      // The drawing is the primary target, so every surface on it has to be
      // finger-sized: one tooth at 160 px leaves the narrow bands at 46 px.
      // The letters below are the second way, not the rescue for a miss.
      const surfaces = page.getByTestId('surface-tooth-views').locator('.surface-path')
      await expect(surfaces).toHaveCount(5)
      const tooSmall = await surfaces.evaluateAll(nodes => nodes
        .map((el) => {
          const r = el.getBoundingClientRect()
          return { s: el.getAttribute('data-surface'), w: Math.round(r.width), h: Math.round(r.height) }
        })
        .filter(m => m.w < 44 || m.h < 44))
      expect(tooSmall, 'surfaces a finger cannot hit on the drawing').toEqual([])

      // A finger taps a point, not an element: the letter is drawn over
      // the middle of its own surface, so the tap has to pick O either way.
      const o = (await page.locator('[data-surface="O"]').boundingBox())!
      await page.touchscreen.tap(o.x + o.width / 2, o.y + o.height / 2)
      await expect(page.getByTestId('surface-btn-O')).toHaveAttribute('data-active', 'true')
      await page.getByTestId('surface-btn-M').tap()
      await expect(page.getByTestId('surface-btn-M')).toHaveAttribute('data-active', 'true')

      await page.getByTestId('surface-confirm').tap()
      await expect(picker).toBeHidden({ timeout: 30_000 })

      await expect.poll(async () => {
        const charted = (await treatments()).data.filter(t => !before.includes(t.id))
        return charted.map(t => `${t.clinical_type}:${[...(t.teeth?.[0]?.surfaces ?? [])].sort().join('')}`)
      }, { timeout: 20_000 }).toEqual(['caries:MO'])
    } finally {
      for (const t of (await treatments()).data.filter(t => !before.includes(t.id))) {
        await page.request.delete(`${API_BASE}/api/v1/odontogram/treatments/${t.id}`, { headers: auth })
      }
    }
  })

  test('opens the eruption card in reach, and leaves nothing behind', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, { headers: auth })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id

    await openCard(page, patientId)
    await page.getByTestId('tooth-diagnosis-eruption').tap()

    const eruption = page.getByTestId('tooth-eruption-modal')
    await expect(eruption).toBeVisible({ timeout: 30_000 })
    await expect
      .poll(() => countUndersizedTargets(page, '[data-testid="tooth-eruption-modal"]'), { timeout: 10_000 })
      .toEqual([])

    const box = (await eruption.boundingBox())!
    expect(box.y + box.height, 'the eruption card runs off the screen')
      .toBeLessThanOrEqual(page.viewportSize()!.height + 1)
    await expect(page.getByTestId('tooth-eruption-save')).toBeInViewport()

    await page.keyboard.press('Escape')
    await expect(eruption).toBeHidden()
  })
})
