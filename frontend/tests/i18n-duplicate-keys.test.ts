/**
 * A translation key may not be written twice in the same object.
 *
 * JSON does not complain: the last value wins and the earlier one is
 * unreachable, so the string a developer reads in the file is not the
 * string the user gets. `auth.sessionExpired` was declared twice — once
 * as the full sentence, once as a bare "Tu sesión ha expirado" — and the
 * login screen silently lost the half that tells the user they can carry
 * on where they left off. Nothing failed; the file simply meant
 * something other than it looked like it meant.
 *
 * `i18n-parity.test.ts` cannot catch this: it compares the locales after
 * parsing, by which point each duplicate has already collapsed to one
 * value — and they collapse the same way in both, so parity holds.
 *
 * So the raw text is scanned, which is the only place the duplicate
 * still exists.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const LOCALES = resolve(
  process.cwd(),
  process.cwd().endsWith('frontend') ? 'i18n/locales' : 'frontend/i18n/locales'
)

/**
 * Every key declared more than once within one object, as a dotted path.
 *
 * Strings are consumed whole, so a `{`, a `}` or a key-like substring
 * inside a translation cannot shift the nesting.
 */
function duplicatePaths(raw: string): string[] {
  const found: string[] = []
  const seen: Array<Map<string, number>> = [new Map()]
  const names: string[] = []
  let depth = 0

  for (let i = 0; i < raw.length; i++) {
    const char = raw[i]!

    if (char === '"') {
      let end = i + 1
      while (end < raw.length && !(raw[end] === '"' && raw[end - 1] !== '\\')) end++
      const text = raw.slice(i + 1, end)
      let after = end + 1
      while (after < raw.length && /\s/.test(raw[after]!)) after++
      // A string followed by a colon is a key; anything else is a value.
      if (raw[after] === ':') {
        const level = (seen[depth] ??= new Map())
        level.set(text, (level.get(text) ?? 0) + 1)
        if (level.get(text) === 2) found.push([...names.slice(1, depth), text].join('.'))
        names[depth] = text
      }
      i = end
      continue
    }

    if (char === '{') seen[++depth] = new Map()
    else if (char === '}') depth--
  }

  return found
}

describe('locale files', () => {
  const files = readdirSync(LOCALES).filter(name => name.endsWith('.json'))

  it('finds the locale files', () => {
    expect(files.length, `no .json under ${LOCALES}`).toBeGreaterThan(0)
  })

  it.each(files)('%s declares every key once', (name) => {
    const duplicates = duplicatePaths(readFileSync(resolve(LOCALES, name), 'utf8'))

    expect(
      duplicates,
      'a key written twice in the same object loses to the later one, so the string '
      + 'being read in the file is not the one the user sees'
    ).toEqual([])
  })
})
