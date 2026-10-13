# 0052 — Browser sessions use a same-origin HttpOnly BFF

- **Status:** accepted
- **Date:** 2026-10-09
- **Deciders:** Eduardo
- **Tags:** security, auth, frontend, operations

## Context

The browser held both JWTs in JavaScript-readable cookies and sent bearer
headers directly to the API. Refresh was deduplicated within one tab, but
rotation spent each refresh token once. Two tabs could present the same
token at once, and the backend interpreted that replay as theft and revoked
the family. A seven-day token expiry also slid on every rotation, so a
continuously active family had no absolute end. Idle expiry was known only
to the browser.

The frontend also had authenticated file and stream calls outside
`useApi`, bypassing refresh recovery. A cookie-only frontend would not work
with separate frontend and backend origins without a server-side proxy.

## Decision

**The browser talks to the same-origin Nuxt BFF. Auth tokens are held only
in `HttpOnly` cookies; the backend remains the authority for session
validity.**

- The BFF proxies only `/api/v1/**` to its private, fixed backend origin.
  It sets `HttpOnly`, `SameSite=Lax` auth cookies, strips token fields from
  login/setup/refresh responses, and injects the access bearer only on the
  server. It keeps no process-local session state — amended by
  [ADR 0054](0054-the-bff-replays-one-rotation-per-refresh-token.md): it
  holds one rotation answer per refresh token, for ten seconds.
- Unsafe requests require an exact same-origin `Origin` and a matching
  readable CSRF cookie/header. Logout still requires the exact origin; it
  does not require the CSRF token so server-rendered idle termination can
  revoke a family before a CSRF cookie exists.
- `useApi` owns staff API calls, including binary responses and multipart
  uploads. A 401 triggers a refresh under the browser's cross-tab Web Lock;
  the lock holder probes `/auth/me` first to adopt a rotation another tab
  already completed. It retries the original request once. Activity and
  logout state are broadcast without credentials.
- Human interaction remains detected in the browser. At most once per
  30 seconds per tab, the client signals `/auth/activity`; background API
  traffic does not count as activity. The backend stores activity on the
  session family, rejects idle families after 60 minutes on refresh and
  authenticated requests, and does not allow activity to extend the
  family's absolute deadline. The signal is not proof of a human; it makes
  server enforcement authoritative over persisted activity rather than a
  client-editable timestamp.
- A family expires 30 days after login/setup, regardless of rotation. The
  existing seven-day refresh-token window remains a sliding upper bound for
  each token, clamped to the fixed family deadline. The database row lock
  serializes refresh-token spends across backend processes.
- Existing families receive a deadline 30 days after their earliest
  stored session row and a one-time idle grace starting at migration time.
  Family-less access tokens are accepted only for their original 15-minute
  transition window.
- Frontend deployments set the private `NUXT_API_BASE_URL_SERVER` and the
  public app origin used behind TLS-terminating proxies. The browser-facing
  app origin serves the BFF; a separate API hostname is no longer part of
  browser auth.

## Consequences

### Good

- XSS cannot read either JWT from cookies, and browser traffic does not
  expose bearer values in JavaScript headers.
- Refresh coordination works across tabs, while backend row locking still
  protects rotation across SSR requests and backend replicas.
- Both the 60-minute idle policy and 30-day family maximum are enforced
  using persisted server state.
- Files, streams and JSON share the same authenticated transport and
  refresh behavior.

### Bad / accepted trade-offs

- Authenticated API requests now read session-family state from the
  database; this is the cost of immediate logout, idle enforcement and
  absolute-lifetime enforcement.
- The browser can report activity only when it observes interaction. A
  lost activity request does not extend the server deadline, so an active
  user may need to sign in again after a sustained network failure.
- Browsers without Web Locks lack cross-tab mutual exclusion. They still
  use per-tab deduplication; backend replay detection remains the final
  safeguard and can require a new login if those tabs race.
- Any deployment that serves the frontend behind another origin must route
  its public app origin to Nuxt and configure the private backend URL for
  Nuxt. The standalone backend API hostname is not a browser fallback.

## References

- [ADR 0029 — Security invariants have chokepoints](0029-security-invariants-with-chokepoints.md)
- [ADR 0030 — Sessions end after an hour idle](0030-sessions-end-after-an-hour-idle.md)
- `backend/app/core/auth/sessions.py`
- `frontend/server/api/v1/[...path].ts`
- `frontend/app/composables/useApi.ts`