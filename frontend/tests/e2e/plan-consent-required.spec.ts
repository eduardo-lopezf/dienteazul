import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * A treatment plan waits for the patient's informed consent: confirming
 * one without it says what is missing and leads to the patient's
 * consents, where the letter is written for that plan.
 *
 * The plan is deleted by the test. The letter it signs stays on the
 * seeded patient, revoked — a signed consent is never deleted (ADR 0045).
 */
test.describe('plan · informed consent', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 240_000 })

  const api = `${API_BASE}/api/v1`
  const PLANS = `${api}/treatment_plan/treatment-plans`

  test('a plan waits for its consent, and work done without it is flagged', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const active = ((await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()) as {
      data: { name: string }[]
    }).data.map(m => m.name)
    test.skip(
      !active.includes('consents') || !active.includes('professionals'),
      'the rule needs the Clinical record and Professionals Apps'
    )

    const patientId = ((await (await page.request.get(`${api}/patients?page_size=1`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!.id
    const item = ((await (await page.request.get(`${api}/catalog/items?page_size=20`, { headers: auth })).json()) as {
      data: { id: string, treatment_scope: string }[]
    }).data.find(c => c.treatment_scope === 'tooth')!
    const professional = ((await (await page.request.get(`${api}/professionals`, { headers: auth })).json()) as {
      data: { id: string }[]
    }).data[0]!

    const rule = `${api}/consents/settings`
    const ruleWasOn = ((await (await page.request.get(rule, { headers: auth })).json()) as {
      data: { require_informed_for_plan: boolean }
    }).data.require_informed_for_plan
    await page.request.put(rule, { headers: auth, data: { require_informed_for_plan: true } })

    const planId = ((await (await page.request.post(PLANS, {
      headers: auth, data: { patient_id: patientId, title: 'E2E consent required' }
    })).json()) as { data: { id: string } }).data.id
    let consentId: string | null = null

    try {
      await page.request.post(`${PLANS}/${planId}/catalog-items`, {
        headers: auth,
        data: { lines: [{ catalog_item_id: item.id, tooth_numbers: [24], surfaces: [], phase: null, notes: null }] }
      })

      await page.goto(`/treatments/plans/${planId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
      await page.getByRole('button', { name: /^Confirmar plan$/ }).first().click({ timeout: 60_000 })
      await page.getByRole('button', { name: /^Confirmar plan$/ }).last().click()

      // Refused, saying what is missing — and the plan stays a draft.
      await expect(page.getByText('Falta el consentimiento informado').first()).toBeVisible({ timeout: 30_000 })
      const state = ((await (await page.request.get(`${PLANS}/${planId}`, { headers: auth })).json()) as {
        data: { status: string }
      }).data.status
      expect(state).toBe('draft')
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-refused.png` })
      }

      // The way out is one click: the patient's consents, for this plan.
      await page.getByRole('button', { name: 'Crear la carta' }).click()
      await expect(page).toHaveURL(new RegExp(`/patients/${patientId}\\?tab=consents&plan=${planId}`))
      await expect(page.getByTestId('consent-for-plan')).toContainText('queda ligada al plan', { timeout: 60_000 })

      // The letter is written and signed (through the API: the form and
      // the signature have their own spec).
      const consent = ((await (await page.request.post(`${api}/consents/patients/${patientId}`, {
        headers: auth,
        data: {
          kind: 'informed',
          title: 'E2E consentimiento del plan',
          body: 'Riesgos y alternativas explicados.',
          plan_id: planId,
          explained_by_professional_id: professional.id
        }
      })).json()) as { data: { id: string } }).data
      consentId = consent.id
      const signed = await page.request.post(`${api}/consents/${consent.id}/sign`, {
        headers: auth,
        data: {
          signed_by_name: 'E2E',
          signer_capacity: 'patient',
          signature_data: { png: 'data:image/png;base64,AAAA' }
        }
      })
      expect(signed.ok(), await signed.text()).toBeTruthy()

      await page.reload()
      await expect(page.getByTestId('consent-for-plan')).toContainText('ya está firmado', { timeout: 60_000 })
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-signed.png` })
      }
      await page.getByRole('link', { name: 'Volver al plan' }).click()
      await expect(page).toHaveURL(new RegExp(`/treatments/plans/${planId}`))

      // Now it goes through.
      const confirmed = await page.request.post(`${PLANS}/${planId}/confirm`, { headers: auth })
      expect(confirmed.status(), await confirmed.text()).toBe(200)

      // --- The patient takes the consent back with the plan under way.
      //     Performing a treatment asks for the letter first; going on
      //     without it is allowed, and the plan says so in red.
      await page.request.post(`${api}/consents/${consent.id}/revoke`, { headers: auth, data: { note: 'Prueba e2e' } })
      await page.reload()
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
      await expect(page.getByTestId('plan-consent-missing')).toHaveCount(0)

      await page.locator('.plan-item').first().click({ timeout: 60_000 })
      await page.locator('[role=dialog]').getByRole('button', { name: 'Marcar como completado' }).click()
      await expect(page.getByText('Este plan no tiene carta de consentimiento firmada')).toBeVisible({ timeout: 30_000 })
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-prompt.png` })
      }
      await page.getByTestId('plan-consent-proceed').click()

      await expect.poll(async () => {
        const now = (await (await page.request.get(`${PLANS}/${planId}`, { headers: auth })).json()) as {
          data: { items: { status: string }[], informed_consent_missing: boolean }
        }
        return [now.data.items[0]!.status, now.data.informed_consent_missing]
      }, { timeout: 60_000 }).toEqual(['completed', true])

      // The charge prompt follows a completion; leave it pending.
      await page.getByRole('button', { name: 'Dejar pendiente' }).click({ timeout: 30_000 }).catch(() => {})
      await expect(page.getByTestId('plan-consent-missing')).toContainText('Falta la carta de consentimiento informado', { timeout: 60_000 })
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-missing.png`, fullPage: true })
      }
    } finally {
      // What the test completed is reopened first, so the delete takes it along.
      const left = await page.request.get(`${PLANS}/${planId}`, { headers: auth })
      const items = left.ok()
        ? ((await left.json()) as { data: { items: { id: string, status: string }[] } }).data.items
        : []
      for (const done of items.filter(i => i.status === 'completed')) {
        await page.request.patch(`${PLANS}/${planId}/items/${done.id}/reopen`, { headers: auth })
      }
      await page.request.post(`${PLANS}/${planId}/reopen`, { headers: auth })
      await page.request.delete(`${PLANS}/${planId}`, { headers: auth })
      if (consentId) {
        await page.request.post(`${api}/consents/${consentId}/revoke`, { headers: auth, data: { note: 'Prueba e2e' } })
      }
      await page.request.put(rule, { headers: auth, data: { require_informed_for_plan: ruleWasOn } })
    }
  })
})
