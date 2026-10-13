import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * The ASA physical status on the patient's summary: a clinician assesses,
 * the class shows on the card and — from III up — among the alerts of the
 * patient's header.
 *
 * An assessment is never deleted (ADR 0032): each run leaves one,
 * retracted, on the seeded patient.
 */
test.describe('ASA classification', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 180_000 })

  test('an assessment shows on the summary and raises an alert from class III', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`
    const patient = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!
    const asa = `${api}/patients_clinical/patients/${patient.id}/asa`
    const rationale = `E2E infarto hace 8 meses ${Date.now()}`

    try {
      await page.goto(`/patients/${patient.id}`)
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
      await page.getByTestId('asa-open').click({ timeout: 90_000 })

      // Nothing to save until a class is chosen.
      await expect(page.getByTestId('asa-save')).toBeDisabled()
      await page.getByTestId('asa-class-3').click()
      await page.getByTestId('asa-rationale').fill(rationale)
      if (process.env.RECORD_SHOT) {
        await page.addStyleTag({ content: '#nuxt-devtools-anchor, nuxt-devtools-frame { display: none !important; }' })
        await page.screenshot({ path: process.env.RECORD_SHOT })
      }
      await page.getByTestId('asa-save').click()

      await expect(page.getByTestId('asa-history')).toContainText(rationale, { timeout: 30_000 })
      await page.keyboard.press('Escape')
      await expect(page.getByTestId('asa-current')).toHaveText('ASA III')

      // Said where the allergies are said, once the header reads it again.
      await page.reload()
      await expect(page.getByText('ASA III').first()).toBeVisible({ timeout: 90_000 })
      const alerts = (await (await page.request.get(
        `${api}/patients_clinical/patients/${patient.id}/alerts`, { headers: auth }
      )).json()) as { data: { alerts: { type: string, title: string }[] } }
      expect(alerts.data.alerts.filter(a => a.type === 'asa').map(a => a.title)).toEqual(['ASA III'])

      // And said again where the appointment is booked, when the agenda is on.
      const active = ((await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()) as {
        data: { name: string }[]
      }).data
      if (active.some(m => m.name === 'agenda')) {
        await page.goto(`/appointments?patient_id=${patient.id}`)
        await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
        await page.getByRole('button', { name: /Nueva cita|New appointment/ }).first().click({ timeout: 60_000 })
        const notice = page.getByTestId('appointment-asa-notice')
        await expect(notice).toContainText('ASA III', { timeout: 60_000 })
        await expect(notice).toContainText(rationale)
        if (process.env.RECORD_SHOT) {
          await page.screenshot({ path: `${process.env.RECORD_SHOT}-booking.png` })
        }
      }

      // Reception reads the class alone: no reason, no assessor, no history.
      const reception = { authorization: `Bearer ${await tokenFor(page, 'receptionist')}` }
      const brief = await page.request.get(`${asa}/class`, { headers: reception })
      expect(brief.status()).toBe(200)
      const seen = (await brief.json()).data as Record<string, unknown>
      expect(seen.label).toBe('III')
      expect(Object.keys(seen).sort()).toEqual(['asa_class', 'is_emergency', 'label'])
      expect((await page.request.get(asa, { headers: reception })).status()).toBe(403)
    } finally {
      const status = (await (await page.request.get(asa, { headers: auth })).json()) as {
        data: { history: { id: string, rationale: string | null }[] }
      }
      for (const item of status.data.history.filter(a => a.rationale === rationale)) {
        await page.request.post(`${asa}/${item.id}/retract`, { headers: auth, data: { reason: 'E2E' } })
      }
    }
  })
})

test.describe('ASA classification · reception', () => {
  test.use({ role: 'receptionist' })
  test.describe.configure({ timeout: 180_000 })

  test('whoever books sees the class, not the clinical detail', async ({ loggedIn: page }) => {
    const admin = { authorization: `Bearer ${await tokenFor(page, 'admin')}` }
    const api = `${API_BASE}/api/v1`
    const active = ((await (await page.request.get(`${api}/modules/-/active`, { headers: admin })).json()) as {
      data: { name: string }[]
    }).data
    test.skip(!active.some(m => m.name === 'agenda'), 'the agenda is not enabled in this environment')

    const patient = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: admin })).json()) as {
      data: { id: string }[]
    }).data[0]!
    const asa = `${api}/patients_clinical/patients/${patient.id}/asa`
    const rationale = `E2E motivo reservado ${Date.now()}`
    const made = ((await (await page.request.post(asa, {
      headers: admin, data: { asa_class: 4, rationale }
    })).json()) as { data: { id: string } }).data

    try {
      await page.goto(`/appointments?patient_id=${patient.id}`)
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
      await page.getByRole('button', { name: /Nueva cita|New appointment/ }).first().click({ timeout: 60_000 })
      const notice = page.getByTestId('appointment-asa-notice')
      await expect(notice).toContainText('ASA IV', { timeout: 60_000 })
      // The class and what to do about it in the scheduling — nothing else:
      // not what the class means, not when or why it was assessed.
      await expect(notice).toContainText(/Conviene valorar con el clínico|Check with the clinician/)
      await expect(notice).not.toContainText(rationale)
      await expect(notice).not.toContainText(/Enfermedad sistémica|systemic disease/)
      await expect(notice).not.toContainText(/Valorado el|Assessed on/)
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-reception.png` })
      }
    } finally {
      await page.request.post(`${asa}/${made.id}/retract`, { headers: admin, data: { reason: 'E2E' } })
    }
  })
})
