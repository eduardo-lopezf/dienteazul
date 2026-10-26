import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * The health questionnaire a patient answers at a visit, and the plan's
 * diagnosis and prognosis: what a paper clinical history carries that the
 * record now asks for.
 *
 * A questionnaire is never deleted (ADR 0032): each run leaves one,
 * retracted, on the seeded patient.
 */
test.describe('clinical history', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 180_000 })

  test('a health questionnaire is answered on screen and reaches the record', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`
    const patient = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!
    const questionnaires = `${api}/patients_clinical/patients/${patient.id}/questionnaires`
    const complaint = `E2E dolor en molar ${Date.now()}`

    // The blank sheet, to fill in by hand.
    const sheet = await page.request.get(
      `${api}/patients_clinical/patients/${patient.id}/questionnaire-form`, { headers: auth }
    )
    expect(sheet.headers()['content-type']).toBe('application/pdf')

    try {
      await page.goto(`/patients/${patient.id}?tab=questionnaire`)
      await page.getByTestId('questionnaire-new').click({ timeout: 60_000 })

      // An empty questionnaire says nothing.
      await expect(page.getByTestId('questionnaire-save')).toBeDisabled()
      await page.getByTestId('questionnaire-chief-complaint').fill(complaint)
      await page.getByTestId('question-taking_medication').getByText(/^(Sí|Yes)$/).click()
      await page.getByTestId('question-taking_medication').getByRole('textbox').fill('Losartán 50 mg')
      await page.getByTestId('condition-hypertension').click()
      if (process.env.RECORD_SHOT) {
        await page.getByTestId('questionnaire-form').screenshot({ path: process.env.RECORD_SHOT })
      }
      // Answered, and still not saved: on screen the patient signs it.
      await expect(page.getByTestId('questionnaire-save')).toBeDisabled()
      // Their name is offered, and a drawing with no name under it is not
      // a signature either.
      const pad = page.getByTestId('questionnaire-signature-pad')
      await pad.scrollIntoViewIfNeeded()
      const box = (await pad.boundingBox())!
      await page.mouse.move(box.x + 30, box.y + 40)
      await page.mouse.down()
      await page.mouse.move(box.x + 140, box.y + 90, { steps: 6 })
      await page.mouse.move(box.x + 220, box.y + 50, { steps: 6 })
      await page.mouse.up()
      const signer = page.getByTestId('questionnaire-signer-name')
      await expect(signer).not.toHaveValue('')
      const offered = await signer.inputValue()
      await signer.fill('')
      await expect(page.getByTestId('questionnaire-save')).toBeDisabled()
      await signer.fill(offered)
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-signature.png` })
      }
      await page.getByTestId('questionnaire-save').click()

      const row = page.getByTestId('questionnaire-row').filter({ hasText: complaint })
      await expect(row).toBeVisible({ timeout: 30_000 })
      await expect(row.getByTestId('questionnaire-signed')).toBeVisible()
      // "Ver" opens the same form, read-only, with what was answered.
      await row.getByTestId('questionnaire-view-open').click()
      const view = page.getByTestId('questionnaire-view')
      await expect(view.getByTestId('questionnaire-chief-complaint')).toHaveValue(complaint)
      await expect(view.getByTestId('questionnaire-signature-shown')).toContainText(offered)
      await expect(page.getByTestId('questionnaire-save')).toHaveCount(0)
      await page.getByTestId('questionnaire-view-close').click()
      await expect(view).toBeHidden()
      const saved = ((await (await page.request.get(questionnaires, { headers: auth })).json()) as {
        data: { chief_complaint: string | null, signed_by_name: string | null, signature_data: { png?: string } | null }[]
      }).data.find(q => q.chief_complaint === complaint)!
      expect(saved.signed_by_name).toBe(offered)
      expect(saved.signature_data?.png).toMatch(/^data:image\/png;base64,/)

      const active = await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()
      if ((active.data as { name: string }[]).some(m => m.name === 'record')) {
        await page.goto(`/patients/${patient.id}?tab=record`)
        await expect(page.getByTestId('record-section-patients_clinical.health_questionnaires'))
          .toContainText(complaint, { timeout: 60_000 })
        await expect(page.getByTestId('record-coverage-chief_complaint')).toHaveAttribute('data-met', 'true')
      }
    } finally {
      const made = ((await (await page.request.get(questionnaires, { headers: auth })).json()) as {
        data: { id: string, chief_complaint: string | null }[]
      }).data.find(q => q.chief_complaint === complaint)
      if (made) {
        await page.request.post(`${questionnaires}/${made.id}/retract`, {
          headers: auth, data: { reason: 'Prueba e2e' }
        })
      }
    }
  })

  test('a plan states its diagnosis and prognosis, and they can be refined', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`
    const plans = ((await (await page.request.get(`${api}/treatment_plan/treatment-plans?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data
    test.skip(plans.length === 0, 'no treatment plan in this environment')
    const planUrl = `${api}/treatment_plan/treatment-plans/${plans[0]!.id}`
    const before = (await (await page.request.get(planUrl, { headers: auth })).json()).data as {
      diagnosis_notes: string | null
      prognosis: string | null
      prognosis_notes: string | null
    }
    const reason = `E2E ${Date.now()}`

    try {
      await page.goto(`/treatments/plans/${plans[0]!.id}`)
      await page.getByTestId('plan-diagnosis-edit').click({ timeout: 60_000 })
      const form = page.getByTestId('plan-diagnosis-form')
      await form.getByTestId('plan-prognosis-select').click()
      await page.getByRole('option', { name: /Reservado|Guarded/ }).click()
      await form.getByPlaceholder(/Por qué|Why/).fill(reason)
      await page.getByTestId('plan-diagnosis-save').click()

      await expect(page.getByTestId('plan-prognosis-shown')).toContainText(reason, { timeout: 30_000 })
    } finally {
      // Put back what the plan said, where it said something.
      await page.request.put(planUrl, {
        headers: auth,
        data: {
          diagnosis_notes: before.diagnosis_notes ?? undefined,
          prognosis: before.prognosis ?? undefined,
          prognosis_notes: before.prognosis_notes ?? undefined
        }
      })
    }
  })
})
