/**
 * Pure session rules: where to send someone after login, and when an idle
 * session is over. Kept free of Nuxt so they can be tested on their own —
 * `useSessionActivity` and the auth middleware are the only callers.
 */

/**
 * Why a session ended, as shown on the login screen.
 *
 * Three cases, because they ask three different things of the person:
 * `idle` is "nobody was there" and waiting caused it; `revoked` is "it
 * was taken away" — a sign-out elsewhere, a password change, a token
 * replayed — and signing in again is the whole fix; `expired` is
 * everything else, which is also the only one that may be a defect.
 * The backend names the case it refused for (`app/core/auth/refusals.py`)
 * and `reasonForCode` maps it, so the wording is no longer guessed from
 * a cookie the browser wrote itself.
 */
export type SessionEndReason = 'idle' | 'expired' | 'revoked'

/**
 * The codes the backend refuses a session with, grouped by what they
 * mean to the person. Mirrors `IDLE_CODES` and `REVOKED_CODES` in
 * `backend/app/core/auth/refusals.py`; `tests/session-refusal-codes.test.ts`
 * reads that file and fails when the two drift.
 */
const IDLE_CODES = new Set([
  'auth.refresh.family_inactive',
  'auth.session.family_inactive',
  'auth.activity.family_inactive'
])

const REVOKED_CODES = new Set([
  'auth.refresh.reused',
  'auth.refresh.family_revoked',
  'auth.refresh.version_revoked',
  'auth.refresh.user_inactive',
  'auth.session.family_unknown'
])

/** The reason a refusal code stands for, or null when it names no case. */
export function reasonForCode(code: unknown): SessionEndReason | null {
  if (typeof code !== 'string' || !code) return null
  if (IDLE_CODES.has(code)) return 'idle'
  if (REVOKED_CODES.has(code)) return 'revoked'
  return 'expired'
}

const NEVER_RETURN_TO = new Set(['/login', '/setup'])

/**
 * The in-app path to resume after login, or null for the default.
 *
 * `redirect` arrives in the URL, so anyone can write it. Only a path
 * inside this app is honoured: an absolute or scheme-relative URL would
 * turn the login page into an open redirect, and a link sent by e-mail
 * would then log a user in and hand them to a lookalike. Backslashes and
 * control characters are refused too — browsers normalise `/\host` into
 * `//host`.
 */
export function safeRedirect(value: unknown): string | null {
  const raw = Array.isArray(value) ? value[0] : value
  if (typeof raw !== 'string' || !raw.startsWith('/')) return null
  if (raw.startsWith('//') || raw.includes('\\') || hasControlCharacter(raw)) return null

  const path = raw.split(/[?#]/)[0]!
  if (NEVER_RETURN_TO.has(path)) return null
  return raw
}

function hasControlCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    if (value.charCodeAt(i) < 0x20) return true
  }
  return false
}

/**
 * The login route, carrying where the user was, why they left, and the
 * reference of the refusal that ended it.
 *
 * `reference` is the backend's `request_id` for the refusal (ADR 0059):
 * it heads the log line the refusal wrote and is what finds it again in
 * the operator's `/ops/logs` (ADR 0060). Shown on the login screen so
 * the person who was thrown out can quote one string to whoever can
 * look, rather than "it happened around eleven".
 */
export function loginLocation(
  returnTo?: string | null,
  reason?: SessionEndReason,
  reference?: string | null
): { path: string, query: Record<string, string> } {
  const query: Record<string, string> = {}
  const redirect = safeRedirect(returnTo)
  // The dashboard is where login lands anyway; spelling it out only makes
  // the URL longer.
  if (redirect && redirect !== '/') query.redirect = redirect
  if (reason) query.reason = reason
  // Bounded and alphanumeric: it goes on screen, and it arrives in a URL
  // anybody can write.
  if (reference && /^[\w-]{1,64}$/.test(reference)) query.ref = reference
  return { path: '/login', query }
}

/**
 * Has the idle window passed since the last recorded activity?
 *
 * A session with no stamp at all predates this rule, and ending it would
 * log out every user on the deploy that ships it — so it is treated as
 * active and the next interaction stamps it.
 */
export function isIdleExpired(lastActivity: number | null, now: number, idleMs: number): boolean {
  if (lastActivity === null || !Number.isFinite(lastActivity)) return false
  return now - lastActivity >= idleMs
}
