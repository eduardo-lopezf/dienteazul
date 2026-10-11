import { API_BASE, ROLES, expect, test, tokenFor } from './_fixtures'

/**
 * A doctor sets up their own letterhead (Settings → Mi membrete): the head
 * of the documents that answer to them. Theirs and nobody else's
 * (ADR 0046). What the test saves it removes.
 *
 * The seed links the dentist's account to their directory profile. A
 * database seeded before it did has no such link, so the test states it
 * as an admin when it is missing, and takes it back.
 */
test.describe('my letterhead', () => {
  test.use({ role: 'dentist' })
  test.describe.configure({ timeout: 180_000 })

  test('a dentist saves their own letterhead and cannot touch the clinic\'s', async ({ loggedIn: page }) => {
    // The dentist's own token, named explicitly: `tokenFor` signs in as the
    // role it is given and defaults to **admin**, so the bare call asked for
    // an admin and this test then linked the dentist's directory profile to
    // the admin's account. The page, in the dentist's session, was right to
    // say they are not a professional.
    const auth = { authorization: `Bearer ${await tokenFor(page, 'dentist')}` }
    const letterheads = `${API_BASE}/api/v1/auth/clinic/settings/letterheads`

    const active = await (await page.request.get(`${API_BASE}/api/v1/modules/-/active`, { headers: auth })).json()
    test.skip(
      !(active.data as { name: string }[]).some(m => m.name === 'record'),
      'the record module is not enabled in this environment'
    )
    type Mine = {
      professional_id: string | null
      letterhead: { heading: string | null, subheading: string | null, show_address: boolean, show_contact: boolean } | null
    }
    const readMine = async () =>
      (await (await page.request.get(`${letterheads}/mine`, { headers: auth })).json()).data as Mine
    const before = await readMine()

    // An admin says which professional this account is, when nobody has.
    const login = await page.request.post(`${API_BASE}/api/v1/auth/login`, {
      data: new URLSearchParams({ username: ROLES.admin, password: 'demo1234' }).toString(),
      headers: { 'content-type': 'application/x-www-form-urlencoded' }
    })
    const admin = { authorization: `Bearer ${(await login.json()).access_token}` }
    const me = (await (await page.request.get(`${API_BASE}/api/v1/auth/me`, { headers: auth })).json()).data.user as { id: string }
    const profile = ((await (await page.request.get(`${API_BASE}/api/v1/professionals?page_size=100`, { headers: admin })).json()) as {
      data: { id: string, email: string | null }[]
    }).data.find(pro => pro.email === ROLES.dentist)
    test.skip(!before.professional_id && !profile, 'no directory profile for the seeded dentist')
    const linkedHere = !before.professional_id
    if (linkedHere) {
      const linked = await page.request.put(`${API_BASE}/api/v1/professionals/${profile!.id}`, {
        headers: admin, data: { user_id: me.id }
      })
      expect(linked.ok()).toBeTruthy()
    }
    const mine = await readMine()
    expect(mine.professional_id).toBeTruthy()

    try {
      await page.goto('/settings/account/my-letterhead')
      const card = page.getByTestId(`letterhead-${mine.professional_id}`)
      await expect(card).toBeVisible({ timeout: 60_000 })
      await card.getByTestId('letterhead-heading').fill('E2E Consultorio propio')
      if (process.env.RECORD_SHOT) {
        await page.getByTestId('my-letterhead').screenshot({ path: process.env.RECORD_SHOT })
      }
      await card.getByTestId('letterhead-save').click()

      await expect.poll(async () =>
        (await (await page.request.get(`${letterheads}/mine`, { headers: auth })).json()).data.letterhead?.heading,
      { timeout: 30_000 }).toBe('E2E Consultorio propio')

      // The clinic's is not theirs to change.
      const refused = await page.request.put(`${letterheads}/clinic`, { headers: auth, data: { heading: 'x' } })
      expect(refused.status()).toBe(403)
    } finally {
      if (mine.letterhead) {
        await page.request.put(`${letterheads}/${mine.professional_id}`, { headers: auth, data: mine.letterhead })
      } else {
        await page.request.delete(`${letterheads}/${mine.professional_id}`, { headers: auth })
      }
      if (linkedHere) {
        await page.request.put(`${API_BASE}/api/v1/professionals/${profile!.id}`, {
          headers: admin, data: { user_id: null }
        })
      }
    }
  })
})
