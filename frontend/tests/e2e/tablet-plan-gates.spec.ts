import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * What a treatment offers depends on where the plan is, not on whether a
 * budget exists.
 *
 * A draft is a proposal: its treatments can be edited and removed, and
 * completing or charging one asks to confirm the whole plan first —
 * confirming is what produces the budget. A plan in progress is the
 * opposite: completing and charging are the daily acts, and editing or
 * removing asks to reopen the plan, which cancels that budget.
 *
 * Run on tablet because this is where the plan is worked: the dialog is
 * the only way in on a touch screen.
 *
 * The plan is built and deleted by the test, and what it completed is
 * reopened first, so nothing of it stays visible on the patient. The rows
 * themselves are soft-deleted, as any deleted plan's are.
 */
test.describe('plan gates by status', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 240_000 })

  const PLANS = `${API_BASE}/api/v1/treatment_plan/treatment-plans`

  test('a draft edits and asks to confirm; in progress asks to reopen', async ({
    loggedIn: page
  }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }

    const patients = await page.request.get(`${API_BASE}/api/v1/patients?page_size=1`, {
      headers: auth
    })
    const patientId = ((await patients.json()) as { data: { id: string }[] }).data[0]?.id
    expect(patientId, 'the seed has no patients').toBeTruthy()

    const catalog = await page.request.get(`${API_BASE}/api/v1/catalog/items?page_size=20`, {
      headers: auth
    })
    const item = ((await catalog.json()) as { data: { id: string, treatment_scope: string }[] })
      .data.find(c => c.treatment_scope === 'tooth')
    expect(item, 'the seed has no per-tooth catalog item').toBeTruthy()

    const created = await page.request.post(PLANS, {
      headers: auth,
      data: { patient_id: patientId, title: 'E2E plan gates' }
    })
    const planId = ((await created.json()) as { data: { id: string } }).data.id

    // This is about the plan's own gates. The clinic's rule that a plan
    // waits for a signed informed consent has its own spec
    // (`plan-consent-required.spec.ts`); switched off here, put back after.
    const consentRule = `${API_BASE}/api/v1/consents/settings`
    const ruleBefore = await page.request.get(consentRule, { headers: auth })
    const ruleWasOn = ruleBefore.ok()
      && ((await ruleBefore.json()) as { data: { require_informed_for_plan: boolean } }).data.require_informed_for_plan
    if (ruleWasOn) {
      await page.request.put(consentRule, { headers: auth, data: { require_informed_for_plan: false } })
    }

    try {
      const lines = [24, 25].map(tooth => ({
        catalog_item_id: item!.id,
        tooth_numbers: [tooth],
        surfaces: [],
        phase: null,
        notes: null
      }))
      const added = await page.request.post(`${PLANS}/${planId}/catalog-items`, {
        headers: auth,
        data: { lines }
      })
      expect(added.status(), await added.text()).toBe(201)

      await page.goto(`/treatments/plans/${planId}`, {
        waitUntil: 'domcontentloaded',
        timeout: 120_000
      })
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })

      // --- Draft: the treatment can be removed from its own dialog, and
      //     completing it asks for the plan first.
      await page.locator('.plan-item').first().click({ timeout: 60_000 })
      const dialog = page.locator('[role=dialog]')
      await expect(dialog.getByRole('button', { name: 'Eliminar tratamiento' })).toBeVisible()
      await dialog.getByRole('button', { name: 'Marcar como completado' }).click()

      await expect(
        page.getByText('Para completar o cobrar un tratamiento, primero hay que confirmar')
      ).toBeVisible({ timeout: 30_000 })

      // Cancelling leaves the plan exactly where it was.
      await page.getByRole('button', { name: 'Cancelar' }).click()
      let state = await page.request.get(`${PLANS}/${planId}`, { headers: auth })
      expect(((await state.json()) as { data: { status: string } }).data.status).toBe('draft')

      // --- Confirming carries out what was asked, and mints the budget.
      await page.locator('.plan-item').first().click()
      await dialog.getByRole('button', { name: 'Marcar como completado' }).click()
      await page.getByRole('button', { name: 'Confirmar plan' }).last().click()
      // The toast and the charge prompt both say it; either proves the write.
      await expect(page.getByText('Tratamiento completado').first()).toBeVisible({
        timeout: 60_000
      })

      state = await page.request.get(`${PLANS}/${planId}`, { headers: auth })
      const confirmed = ((await state.json()) as {
        data: { status: string, budget_id: string | null }
      }).data
      expect(['pending', 'active']).toContain(confirmed.status)
      expect(confirmed.budget_id, 'confirming must produce the budget').toBeTruthy()

      // The charge prompt follows a completion; leave it pending.
      await page.getByRole('button', { name: 'Dejar pendiente' }).click({ timeout: 30_000 })

      // --- In progress: editing asks to reopen, and reopening cancels the
      //     budget the patient may have seen.
      await page.locator('.plan-item').first().click()
      await dialog.getByRole('button', { name: 'Editar o eliminar' }).click()
      await expect(page.getByText('Esto cancelará el presupuesto vigente')).toBeVisible({
        timeout: 30_000
      })
      await page.getByRole('button', { name: 'Reabrir', exact: true }).click()

      await expect
        .poll(async () => {
          const after = await page.request.get(`${PLANS}/${planId}`, { headers: auth })
          return ((await after.json()) as { data: { status: string } }).data.status
        }, { timeout: 60_000 })
        .toBe('draft')

      const budget = await page.request.get(
        `${API_BASE}/api/v1/budget/budgets/${confirmed.budget_id}`,
        { headers: auth }
      )
      expect(((await budget.json()) as { data: { status: string } }).data.status).toBe('cancelled')
    } finally {
      // Deleting a plan does not undo what it completed: the treatment
      // stays `performed` on the patient's chart and its earned entry
      // stays in the ledger. Reopen what this test completed first, so
      // the delete takes the treatments with it.
      const plan = await page.request.get(`${PLANS}/${planId}`, { headers: auth })
      const items = plan.ok()
        ? ((await plan.json()) as { data: { items: { id: string, status: string }[] } }).data.items
        : []
      for (const done of items.filter(i => i.status === 'completed')) {
        await page.request.patch(`${PLANS}/${planId}/items/${done.id}/reopen`, { headers: auth })
      }
      await page.request.delete(`${PLANS}/${planId}`, { headers: auth })
      if (ruleWasOn) {
        await page.request.put(consentRule, { headers: auth, data: { require_informed_for_plan: true } })
      }
    }
  })
})
