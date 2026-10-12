/**
 * The privacy agreement has one version, named twice: the frontend shows
 * and sends it, the backend decides with it who is asked again. A change
 * of the text that updates only one of the two would either refuse every
 * acceptance or ask nobody.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { PRIVACY_AGREEMENT_VERSION } from '../app/config/privacyAgreement'

const backendFile = resolve(
  dirname(fileURLToPath(import.meta.url)),
  '..', '..', 'backend', 'app', 'core', 'auth', 'privacy_agreement.py'
)

describe('privacy agreement version', () => {
  it('is the same in the frontend and in the backend', () => {
    const source = readFileSync(backendFile, 'utf8')
    const backendVersion = /^PRIVACY_AGREEMENT_VERSION = "([^"]+)"$/m.exec(source)?.[1]
    expect(backendVersion).toBe(PRIVACY_AGREEMENT_VERSION)
  })
})
