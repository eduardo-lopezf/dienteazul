import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { isIdleExpired, loginLocation, reasonForCode, safeRedirect } from '~/utils/session'

describe('safeRedirect', () => {
  it('keeps a path inside the app, query and hash included', () => {
    expect(safeRedirect('/patients/123?tab=clinical#notes')).toBe('/patients/123?tab=clinical#notes')
  })

  it('takes the first value when the query repeats the key', () => {
    expect(safeRedirect(['/appointments', '/patients'])).toBe('/appointments')
  })

  // The login page must not become an open redirect: a link someone was
  // sent by e-mail would otherwise log them in and hand them to a lookalike.
  it.each([
    ['an absolute URL', 'https://evil.example/phish'],
    ['a scheme-relative URL', '//evil.example/phish'],
    ['a backslash browsers turn into one', '/\\evil.example'],
    ['a javascript: URL', 'javascript:alert(1)'],
    ['a relative path', 'patients'],
    ['a control character', '/patients\n//evil.example'],
    ['an empty string', ''],
    ['a non-string', 42],
    ['nothing', undefined]
  ])('refuses %s', (_label, value) => {
    expect(safeRedirect(value)).toBeNull()
  })

  it.each(['/login', '/login?redirect=/patients', '/setup'])(
    'refuses to send a user back to %s',
    (value) => {
      expect(safeRedirect(value)).toBeNull()
    }
  )
})

describe('loginLocation', () => {
  it('carries where the user was and why they left', () => {
    expect(loginLocation('/patients?page=2', 'idle')).toEqual({
      path: '/login',
      query: { redirect: '/patients?page=2', reason: 'idle' }
    })
  })

  it('leaves the home page implicit', () => {
    expect(loginLocation('/')).toEqual({ path: '/login', query: {} })
  })

  it('drops a destination it would refuse to follow', () => {
    expect(loginLocation('https://evil.example', 'expired')).toEqual({
      path: '/login',
      query: { reason: 'expired' }
    })
  })

  // The reference is what ties the notice the user reads to the line the
  // refusal wrote in the operator's log (ADR 0059, ADR 0060).
  it('carries the reference of the refusal that ended the session', () => {
    expect(loginLocation('/patients', 'revoked', 'a1b2c3d4e5f60718')).toEqual({
      path: '/login',
      query: { redirect: '/patients', reason: 'revoked', ref: 'a1b2c3d4e5f60718' }
    })
  })

  // It arrives in a URL anybody can write, and it goes on screen.
  it.each(['<script>', 'a'.repeat(65), 'with space', ''])(
    'refuses %s as a reference',
    (value) => {
      expect(loginLocation('/patients', 'expired', value).query.ref).toBeUndefined()
    }
  )
})

/**
 * The wording the user gets is the backend's own verdict now, so the two
 * halves of the table have to stay in step. This reads the Python the
 * codes are defined in rather than restating them: a code added on one
 * side and not the other is exactly the drift that made the login screen
 * guess in the first place (ADR 0062).
 */
describe('reasonForCode', () => {
  // Resolved from the working directory rather than `import.meta.url`:
  // under the `nuxt` environment that is not a file URL.
  const REFUSALS = 'backend/app/core/auth/refusals.py'
  const path = [resolve(process.cwd(), '..', REFUSALS), resolve(process.cwd(), REFUSALS)]
    .find(existsSync)
  it('finds the backend file the codes are defined in', () => {
    expect(path, `${REFUSALS} not found from ${process.cwd()}`).toBeTruthy()
  })
  const refusals = path ? readFileSync(path, 'utf8') : ''

  function codesOf(group: 'IDLE_CODES' | 'REVOKED_CODES' | 'EXPIRED_CODES'): string[] {
    const constants = Object.fromEntries(
      [...refusals.matchAll(/^([A-Z_]+) = "([\w.]+)"$/gm)].map(m => [m[1]!, m[2]!])
    )
    const block = new RegExp(`${group}: frozenset\\[str\\] = frozenset\\(([\\s\\S]*?)\\)\\n`)
      .exec(refusals)
    expect(block, `${group} not found in refusals.py`).toBeTruthy()
    const names = [...block![1]!.matchAll(/\b([A-Z][A-Z_]+)\b/g)].map(m => m[1]!)
    expect(names.length).toBeGreaterThan(0)
    return names.map((name) => {
      expect(constants[name], `${name} is not a code constant`).toBeTruthy()
      return constants[name]!
    })
  }

  it('says inactivity for every code the backend groups as idle', () => {
    for (const code of codesOf('IDLE_CODES')) expect(reasonForCode(code)).toBe('idle')
  })

  it('says revoked for every code the backend groups as revoked', () => {
    for (const code of codesOf('REVOKED_CODES')) expect(reasonForCode(code)).toBe('revoked')
  })

  it('says caducada for every code the backend groups as expired', () => {
    for (const code of codesOf('EXPIRED_CODES')) expect(reasonForCode(code)).toBe('expired')
  })

  // Not a licence to leave one unclassified: the backend's own
  // `test_session_refusal_contract.py` fails on a code that is in no
  // group. This is what the user gets meanwhile.
  it('falls back to expired for a code it has never seen', () => {
    expect(reasonForCode('auth.refresh.something_new')).toBe('expired')
  })

  // No code at all is an older backend, or a failure that never reached
  // the app: the caller keeps its own guess rather than inventing one.
  it.each([undefined, null, '', 42])('names no case for %s', (value) => {
    expect(reasonForCode(value)).toBeNull()
  })
})

describe('isIdleExpired', () => {
  const HOUR = 60 * 60 * 1000

  it('expires once the idle window has fully passed', () => {
    expect(isIdleExpired(0, HOUR, HOUR)).toBe(true)
  })

  it('does not expire a minute early', () => {
    expect(isIdleExpired(0, HOUR - 60_000, HOUR)).toBe(false)
  })

  // A session with no stamp predates this feature. Ending it would log
  // every user out on the deploy that ships it.
  it('does not expire a session that was never stamped', () => {
    expect(isIdleExpired(null, 10 * HOUR, HOUR)).toBe(false)
  })

  it('does not expire on activity stamped ahead of the clock', () => {
    expect(isIdleExpired(2 * HOUR, HOUR, HOUR)).toBe(false)
  })
})
