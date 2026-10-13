import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * The regulation the clinical record refers to: the clinic sets one line
 * (Settings → General → Normativa del expediente) and it shows where the
 * patient declares — the health questionnaire — and on the record. What
 * the clinic had is put back.
 */
test.describe('record regulation', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 180_000 })

  test('the clinic sets it and it shows on the questionnaire and the record', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`
    const url = `${api}/auth/clinic/settings/record-regulation`
    const before = (await (await page.request.get(url, { headers: auth })).json()).data as {
      text: string | null
      is_default: boolean
    }
    const patient = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!
    const own = `E2E norma ${Date.now()}`

    try {
      await page.goto('/settings/general/record-regulation')
      const input = page.getByTestId('record-regulation-input')
      await input.fill(own, { timeout: 90_000 })
      if (process.env.RECORD_SHOT) {
        await page.addStyleTag({ content: '#nuxt-devtools-anchor, nuxt-devtools-frame { display: none !important; }' })
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-settings.png` })
      }
      await page.getByTestId('record-regulation-save').click()
      await expect.poll(
        async () => (await (await page.request.get(url, { headers: auth })).json()).data.text,
        { timeout: 30_000 }
      ).toBe(own)

      // Where the patient declares.
      await page.goto(`/patients/${patient.id}?tab=questionnaire`)
      await page.getByTestId('questionnaire-new').click({ timeout: 90_000 })
      await expect(page.getByTestId('questionnaire-regulation')).toContainText(own, { timeout: 30_000 })
      if (process.env.RECORD_SHOT) {
        await page.getByTestId('questionnaire-regulation').scrollIntoViewIfNeeded()
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-questionnaire.png` })
      }
      await page.keyboard.press('Escape')

      // And on the record, when that App is on.
      const active = ((await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()) as {
        data: { name: string }[]
      }).data
      if (active.some(m => m.name === 'record')) {
        await page.goto(`/patients/${patient.id}?tab=record`)
        await expect(page.getByTestId('record-regulation-line')).toContainText(own, { timeout: 90_000 })
      }
    } finally {
      await page.request.put(url, { headers: auth, data: { text: before.is_default ? null : (before.text ?? '') } })
    }
  })
})
