import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * Completing an appointment that works on a plan with no signed informed
 * consent asks for the letter first. It asks, it does not refuse: the
 * visit can be completed without it.
 *
 * The plan and the appointment are the test's own; the appointment is
 * cancelled or completed by the end, the plan deleted.
 */
test.describe('agenda · consent before completing a visit', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 240_000 })

  const api = `${API_BASE}/api/v1`
  const PLANS = `${api}/treatment_plan/treatment-plans`
  const AGENDA = `${api}/agenda`

  test('finishing a visit asks for the plan\'s letter', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const get = async <T>(url: string) =>
      ((await (await page.request.get(url, { headers: auth })).json()) as { data: T }).data
    const active = (await get<{ name: string }[]>(`${api}/modules/-/active`)).map(m => m.name)
    test.skip(
      !['consents', 'professionals', 'treatment_plan', 'agenda'].every(m => active.includes(m)),
      'needs the agenda, plans, the Clinical record and Professionals'
    )

    const patientId = (await get<{ id: string }[]>(`${api}/patients?page_size=1`))[0]!.id
    const item = (await get<{ id: string, treatment_scope: string }[]>(`${api}/catalog/items?page_size=20`))
      .find(c => c.treatment_scope === 'tooth')!
    const professional = (await get<{ id: string }[]>(`${api}/professionals`))[0]!
    const cabinet = (await get<{ id: string }[]>(`${AGENDA}/cabinets`))[0]!

    const rule = `${api}/consents/settings`
    const ruleWasOn = (await get<{ require_informed_for_plan: boolean }>(rule)).require_informed_for_plan
    const setRule = (on: boolean) =>
      page.request.put(rule, { headers: auth, data: { require_informed_for_plan: on } })

    // A plan nobody signed a letter for. Still a draft: its treatments can
    // be booked, and that first visit is where the letter is usually missing.
    await setRule(true)
    const planId = ((await (await page.request.post(PLANS, {
      headers: auth, data: { patient_id: patientId, title: 'E2E consent at completion' }
    })).json()) as { data: { id: string } }).data.id
    let appointmentId: string | null = null
    let refusal = ''

    try {
      await page.request.post(`${PLANS}/${planId}/catalog-items`, {
        headers: auth,
        data: { lines: [{ catalog_item_id: item.id, tooth_numbers: [25], surfaces: [], phase: null, notes: null }] }
      })
      const plannedItemId = (await get<{ items: { id: string }[] }>(`${PLANS}/${planId}`)).items[0]!.id

      // Today on the board, in whichever late slot is free. The agenda
      // reads a stored time by its written parts, so the day is the
      // browser's calendar day and the hour is written as is.
      const today = await page.evaluate(() => {
        const now = new Date()
        const two = (n: number) => String(n).padStart(2, '0')
        return `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())}`
      })
      for (const hour of [21, 22, 20, 23]) {
        const start = new Date(`${today}T${hour}:00:00.000Z`)
        const made = await page.request.post(`${AGENDA}/appointments`, {
          headers: auth,
          data: {
            patient_id: patientId,
            professional_id: professional.id,
            cabinet_id: cabinet.id,
            start_time: start.toISOString(),
            end_time: new Date(start.getTime() + 30 * 60_000).toISOString(),
            planned_item_ids: [plannedItemId]
          }
        })
        if (made.ok()) {
          appointmentId = ((await made.json()) as { data: { id: string } }).data.id
          break
        }
        refusal = await made.text()
      }
      expect(appointmentId, `no free slot for the test appointment: ${refusal}`).not.toBeNull()
      for (const to of ['checked_in', 'in_treatment']) {
        const moved = await page.request.post(`${AGENDA}/appointments/${appointmentId}/transitions`, {
          headers: auth, data: { to_status: to }
        })
        expect(moved.ok(), await moved.text()).toBeTruthy()
      }

      await page.goto('/appointments', { waitUntil: 'domcontentloaded', timeout: 120_000 })
      await page.waitForSelector('html[data-ua]', { state: 'attached', timeout: 90_000 })
      await page.getByRole('tab', { name: 'Kanban' }).click({ timeout: 60_000 })

      const card = page.locator(`[data-appointment-id="${appointmentId}"]`).first()
      await expect(card).toBeVisible({ timeout: 60_000 })
      const finish = async () => {
        // The menu stays open behind the question, so backing out returns to it.
        const entry = page.getByRole('menuitem', { name: 'Finalizar cita' })
        if (!(await entry.isVisible())) await card.getByRole('button', { name: 'Marcar llegada' }).click()
        await entry.click()
      }

      // Asked first — and backing out leaves the visit where it was.
      await finish()
      await expect(page.getByText('La cita trabaja sobre un plan sin carta de consentimiento firmada'))
        .toBeVisible({ timeout: 30_000 })
      await expect(page.getByTestId('appointment-consent-write')).toHaveAttribute(
        'href', `/patients/${patientId}?tab=consents&plan=${planId}`
      )
      if (process.env.RECORD_SHOT) {
        await page.screenshot({ path: `${process.env.RECORD_SHOT}-prompt.png` })
      }
      await page.getByTestId('appointment-consent-prompt').getByRole('button', { name: 'Cancelar' }).click()
      expect((await get<{ status: string }>(`${AGENDA}/appointments/${appointmentId}`)).status).toBe('in_treatment')

      // Going on without the letter is allowed.
      await finish()
      await page.getByTestId('appointment-consent-proceed').click({ timeout: 30_000 })
      await expect.poll(
        async () => (await get<{ status: string }>(`${AGENDA}/appointments/${appointmentId}`)).status,
        { timeout: 60_000 }
      ).toBe('completed')
    } finally {
      if (appointmentId) {
        await page.request.post(`${AGENDA}/appointments/${appointmentId}/transitions`, {
          headers: auth, data: { to_status: 'cancelled' }
        })
      }
      await page.request.delete(`${PLANS}/${planId}`, { headers: auth })
      await setRule(ruleWasOn)
    }
  })
})
