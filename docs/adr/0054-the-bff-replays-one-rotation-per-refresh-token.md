# 0054 — The BFF rotates a refresh token once and replays that answer

- **Status:** accepted
- **Date:** 2026-10-13
- **Deciders:** Eduardo
- **Tags:** security, auth, frontend

## Context

Rotation spends the token it is given, and `sessions.rotate` treats a
second presentation as theft: it revokes the whole family and records
`revoked_reason = 'reuse'`. There is no grace window, by design — with
two holders of one token there is no way to tell which one is the thief
([ADR 0052](0052-sessions-use-a-same-origin-http-only-bff.md)).

The client coordinates around that: an in-flight slot per tab and the
browser's Web Lock across tabs, with `/auth/me` probed first so a tab can
adopt a rotation another one already completed. None of it reaches a
**server render**. Until recently that did not show, because server-side
refresh was broken: `useRequestFetch` drops a `Headers` instance passed
alongside the headers it forwards, so the `origin` and `x-csrf-token` that
`bffFetch` exists to add went missing and our own BFF answered every SSR
refresh with `403`. Fixing that made two tabs two refreshes.

They do not even overlap, so collapsing concurrent calls is not enough.
Measured on a cold dev server: tab A refreshed and rotated, and tab B —
whose render had left with the cookie it held at click time — presented the
same token **4.3 s later**. Both tabs lost the session; two `auth_sessions`
rows carried `revoked_reason = 'reuse'`. Two tabs on a front-desk computer
are ordinary use, not theft.

## Decision

**One rotation per refresh token: the first caller goes to the backend, and
anyone presenting that same token within `REFRESH_REPLAY_MS` gets that
answer again.**

- The BFF keeps, per presented token, the in-flight promise and then the
  completed answer — status, headers and body — and serves it unchanged, so
  every tab ends up with the same rotated cookie pair and the family is
  rotated once. `refreshOnce` in `frontend/server/api/v1/[...path].ts`.
- Only a `200` is remembered. A refusal is the backend's answer to that
  caller and may not be the next one's.
- The window is 10 seconds: longer than the gap we measured, short enough
  to matter. Entries are pruned on each call.
- It is keyed by the exact token, so it only ever answers a caller that
  already holds the credential that was spent.
- The backend stays the authority. Nothing here weakens reuse detection
  for a token this process has not just rotated, and nothing extends a
  family's absolute deadline or its idle policy.
- This **amends ADR 0052**, which said the BFF keeps no process-local
  session state. It keeps this, and only this.

## Consequences

### Good

- Two tabs whose access token expired together keep the session, with no
  grace window in the backend and no weakening of rotation for any other
  client.
- The answer outlives the first call, which a lock around concurrent calls
  cannot do — and the gap that broke the session was 4.3 s, not 4 ms.
- Server renders are covered, where neither the Web Lock nor the per-tab
  slot exists.

### Bad / accepted trade-offs

- Inside the window a stolen refresh token presented to this same frontend
  process is answered instead of triggering revocation. It is 10 seconds
  long, it only replays a rotation this process just performed, and the
  thief must present that exact token.
- The frontend process now holds a rotated token pair in memory for those
  10 seconds.
- It is per process. With several frontend replicas
  ([ADR 0051](0051-a-backend-process-is-one-of-several.md)) two tabs served
  by different replicas can still collide and lose the family — rarer, and
  not solved here.

## Alternatives considered

- **Collapse concurrent calls only** — implemented first, and measured
  insufficient: the second refresh arrived 4.3 s after the first had
  finished, so there was nothing in flight to join.
- **A grace window in `sessions.rotate`** — moves a security decision into
  the authority, for every client including non-browser ones, and weakens
  detection everywhere to fix two tabs behind one BFF.
- **A shared store for the rotation answer (Redis)** — would cover
  replicas, at the price of a dependency holding live credentials at rest.
  Revisitable if replicas become the normal deployment; `RATE_LIMIT_STORAGE_URI`
  is the precedent for making it optional.
- **Let the family be revoked** — the status quo the e2e caught: opening a
  second tab ends the session and sends both to login.
- **Refresh on the client only** — a render whose access token had expired
  would have to bounce to login or wait for hydration, which is what the
  SSR refresh exists to avoid (ADR 0030, ADR 0052).

## How to verify the rule still holds

- `frontend/tests/e2e/auth-cross-tab.spec.ts:56` — two tabs follow a link
  with an expired access cookie; both must land on `/patients` and
  `/auth/me` must still answer `200`. Run it against a **cold** frontend
  (`docker compose restart frontend`): a warm dev server renders fast
  enough to hide the gap.
- No row gains `revoked_reason = 'reuse'` while that spec runs:
  `SELECT COUNT(*) FROM auth_sessions WHERE revoked_reason = 'reuse'`
  before and after.

## References

- `frontend/server/api/v1/[...path].ts` (`refreshOnce`, `REFRESH_REPLAY_MS`)
- `frontend/app/composables/useAuth.ts` (`bffFetch`, `refresh`)
- `backend/app/core/auth/sessions.py` (`rotate`)
- [ADR 0052 — Browser sessions use a same-origin HttpOnly BFF](0052-sessions-use-a-same-origin-http-only-bff.md)
- [ADR 0051 — A backend process is one of several](0051-a-backend-process-is-one-of-several.md)
