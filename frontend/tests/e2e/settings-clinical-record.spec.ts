import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * Settings → Apps: every App shows the icon that stands for it, and the
 * Clinical record App opens its own page — how the clinic lays its record
 * out. The format is put back as it was.
 */
test.describe('settings · clinical record', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 180_000 })

  test('every App has an icon, and the clinical record is configured from its card', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`

    await page.goto('/settings/apps')
    await expect(page.getByTestId('app-card-agenda')).toBeVisible({ timeout: 60_000 })
    const cards = await page.locator('[data-testid^="app-card-"]').count()
    expect(await page.locator('[data-testid^="app-icon-"]').count()).toBe(cards)
    if (process.env.RECORD_SHOT) {
      await page.screenshot({ path: `${process.env.RECORD_SHOT}-apps.png`, fullPage: true })
    }

    const active = await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()
    test.skip(
      !(active.data as { name: string }[]).some(m => m.name === 'record'),
      'the record module is not enabled in this environment'
    )
    const before = (await (await page.request.get(`${api}/record/format`, { headers: auth })).json()).data
    const patient = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!

    try {
      await page.getByTestId('app-configure-clinical_record').click()
      await expect(page).toHaveURL(/\/settings\/apps\/clinical-record/)

      // Hide a section and skip a point; nothing is saved until asked.
      const save = page.getByTestId('record-format-save')
      await expect(save).toBeDisabled({ timeout: 60_000 })

      // The letterhead and the regulation are the Workspace's; the page says where.
      await expect(page.getByTestId('record-format-letterhead-link').getByRole('link').first())
        .toHaveAttribute('href', '/settings/general/letterheads')
      await expect(page.getByTestId('record-format-regulation-link'))
        .toHaveAttribute('href', '/settings/general/record-regulation')

      await page.getByTestId('record-format-section-periodontogram.chartings').getByRole('switch').click()
      await page.getByTestId('record-format-requirement-prognosis').click()
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-format.png`, fullPage: true })
      }
      await save.click()
      await expect(save).toBeDisabled({ timeout: 30_000 })
      // The button is also disabled while it saves: wait for what was saved.
      await expect.poll(
        async () => (await (await page.request.get(`${api}/record/format`, { headers: auth })).json()).data.hidden_sections,
        { timeout: 30_000 }
      ).toContain('periodontogram.chartings')

      // The patient's record follows the clinic's format.
      await page.goto(`/patients/${patient.id}?tab=record`)
      await expect(page.getByTestId('record-coverage')).toBeVisible({ timeout: 60_000 })
      await expect(page.getByTestId('record-coverage-prognosis')).toHaveCount(0)
      await page.getByText(/Ocultar secciones vacías|Hide empty sections/).click()
      await expect(page.getByTestId('record-section-periodontogram.chartings')).toHaveCount(0)
      await expect(page.getByTestId('record-section-patients.identification')).toBeVisible()
    } finally {
      await page.request.put(`${api}/record/format`, {
        headers: auth,
        data: {
          hidden_sections: before.hidden_sections,
          section_order: before.section_order,
          disabled_requirements: before.disabled_requirements
        }
      })
    }
  })
})
