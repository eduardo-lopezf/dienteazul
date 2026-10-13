import { API_BASE, expect, test, tokenFor } from './_fixtures'

/**
 * Settings → General → Membretes: the clinic's letterhead and one per
 * professional, set up in the Workspace so they stay reachable whatever
 * optional App is switched off. What the test saves is put back.
 */
const ONE_PIXEL_PNG
  = '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    + '0000000d49444154789c6360000002000001e221bc330000000049454e44ae426082'

test.describe('settings · letterheads', () => {
  test.use({ role: 'admin' })
  test.describe.configure({ timeout: 180_000 })

  test('the clinic and a professional get their letterhead from the Workspace', async ({ loggedIn: page }) => {
    const auth = { authorization: `Bearer ${await tokenFor(page)}` }
    const api = `${API_BASE}/api/v1`
    const letterheads = `${api}/auth/clinic/settings/letterheads`
    type Stored = { professional_id: string | null, heading: string | null, subheading: string | null, show_address: boolean, show_contact: boolean, has_logo: boolean }
    const stored = (await (await page.request.get(letterheads, { headers: auth })).json()).data as Stored[]
    const clinicBefore = stored.find(item => item.professional_id === null)
    const active = ((await (await page.request.get(`${api}/modules/-/active`, { headers: auth })).json()) as {
      data: { name: string }[]
    }).data
    // The directory is the Professionals App's; without it only the clinic's is offered.
    const doctor = active.some(m => m.name === 'professionals')
      ? ((await (await page.request.get(`${api}/professionals`, { headers: auth })).json()) as {
          data: { id: string }[]
        }).data.find(pro => !stored.some(item => item.professional_id === pro.id))
      : undefined

    try {
      // Reached from the Workspace App's own page.
      await page.goto('/settings/apps/workspace')
      await page.getByTestId('workspace-letterheads').click({ timeout: 90_000 })
      await expect(page).toHaveURL(/\/settings\/general\/letterheads/)

      // The clinic's letterhead: a heading, saved with the card's own button.
      const clinicCard = page.getByTestId('letterhead-clinic')
      await clinicCard.getByTestId('letterhead-heading').fill('Dent+Art', { timeout: 60_000 })
      await clinicCard.getByTestId('letterhead-save').click()
      await expect.poll(async () => {
        const now = (await (await page.request.get(letterheads, { headers: auth })).json()).data as Stored[]
        return now.find(item => item.professional_id === null)?.heading
      }, { timeout: 30_000 }).toBe('Dent+Art')
      // A logo, saved as it is chosen — never over one the clinic already had.
      if (!clinicBefore?.has_logo) {
        await clinicCard.getByTestId('letterhead-logo-input').setInputFiles({
          name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from(ONE_PIXEL_PNG, 'hex')
        })
        await expect(clinicCard.getByTestId('letterhead-logo')).toBeVisible({ timeout: 30_000 })
      }

      // A doctor gets their own, offered with their name and licence.
      if (doctor) {
        await page.getByTestId('letterhead-add-select').click()
        await page.getByRole('option').first().click()
        await page.getByTestId('letterhead-add').click()
        // The card just added is the last one that is not the clinic's.
        const card = page.locator('[data-testid^="letterhead-"]:not([data-testid="letterhead-clinic"])')
          .filter({ has: page.getByTestId('letterhead-save') }).last()
        await card.getByTestId('letterhead-save').click()
        await expect.poll(async () => {
          const now = (await (await page.request.get(letterheads, { headers: auth })).json()).data as Stored[]
          return now.filter(item => item.professional_id !== null).length
        }, { timeout: 30_000 }).toBe(stored.filter(item => item.professional_id !== null).length + 1)
      }
      if (process.env.RECORD_SHOT) {
        await page.addStyleTag({ content: '#nuxt-devtools-anchor, nuxt-devtools-frame { display: none !important; }' })
        await page.screenshot({ path: process.env.RECORD_SHOT, fullPage: true })
      }
    } finally {
      // Letterheads the test created are removed; the clinic's is put back.
      const now = (await (await page.request.get(letterheads, { headers: auth })).json()).data as Stored[]
      for (const item of now) {
        if (item.professional_id && !stored.some(s => s.professional_id === item.professional_id)) {
          await page.request.delete(`${letterheads}/${item.professional_id}`, { headers: auth })
        }
      }
      if (clinicBefore) {
        await page.request.put(`${letterheads}/clinic`, {
          headers: auth,
          data: {
            heading: clinicBefore.heading,
            subheading: clinicBefore.subheading,
            show_address: clinicBefore.show_address,
            show_contact: clinicBefore.show_contact
          }
        })
        if (!clinicBefore.has_logo) await page.request.delete(`${letterheads}/clinic/logo`, { headers: auth })
      } else {
        await page.request.delete(`${letterheads}/clinic`, { headers: auth })
      }
    }
  })
})
