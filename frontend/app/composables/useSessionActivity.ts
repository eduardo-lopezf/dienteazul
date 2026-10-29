/**
 * useSessionActivity — when did a person last touch the app?
 *
 * A session ends after `sessionIdleMinutes` without interaction (ADR 0030).
 * Only the browser can answer "is anybody there": the API sees requests,
 * and background fetches are not a person. So the rule is enforced here,
 * and the server is told when it fires — idle expiry is a real logout, not
 * a cookie the browser forgets.
 *
 * The last interaction is a **cookie**, not localStorage, for two reasons:
 * every tab reads the same one, so activity in any tab keeps all of them
 * alive; and the server reads it too, so a tab reopened the next morning
 * is redirected to login before a single patient is rendered.
 *
 * The cookie is written **after** the signal is accepted (ADR 0062).
 * `last_activity_at` on the session family is the clock that decides,
 * and this signal is the only thing that moves it — so stamping first
 * and dropping the failures let the browser believe a session was
 * younger than the server did, for good, and an hour later the user was
 * thrown out mid-task over a signal nobody had noticed going missing.
 *
 * The stamp is written in **server time**. The server compares it with its
 * own clock, and a browser whose clock runs an hour slow would otherwise be
 * logged out on every page load. The offset comes from the server's clock
 * at render time, which travels in the payload.
 */
import { STORAGE_KEYS } from '~/constants/storage'
import { isIdleExpired } from '~/utils/session'

const COOKIE = STORAGE_KEYS.LAST_ACTIVITY
const COOKIE_MAX_AGE = 60 * 60 * 24 * 30 // fixed maximum session-family lifetime
const COOKIE_PATTERN = new RegExp(
  `(?:^|;\\s*)${COOKIE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}=(\\d+)`
)

/** How often an open page asks whether the window has passed. */
const CHECK_EVERY_MS = 15_000
/** Interactions closer together than this are the same interaction. */
const HANDLE_EVERY_MS = 30_000

const ACTIVITY_EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll'] as const

// Client-only module state: one watch per page, one clock offset per load.
let clockOffset: number | null = null
let lastHandled = 0
// The teardown of whatever is watching right now, so a second `start`
// replaces it instead of being turned away. See `start`.
let stopCurrent: (() => void) | null = null

export function useSessionActivity() {
  const config = useRuntimeConfig()
  const idleMs = Number(config.public.sessionIdleMinutes) * 60_000

  // Set during SSR and hydrated on the client; the difference between it
  // and the browser's clock on first use is the offset. Every route runs
  // the auth middleware, which calls this, so the value always exists.
  const serverNow = useState<number>('session:server-now', () => Date.now())
  const serverCookie = import.meta.server ? useCookie<string | null>(COOKIE) : null

  /** Now, on the server's clock. */
  function now(): number {
    if (import.meta.server) return Date.now()
    clockOffset ??= serverNow.value - Date.now()
    return Date.now() + clockOffset
  }

  function lastActivity(): number | null {
    if (import.meta.server) {
      const value = Number(serverCookie!.value)
      return Number.isFinite(value) && value > 0 ? value : null
    }
    // Straight from `document.cookie` rather than a `useCookie` ref: a ref
    // is a snapshot per composable instance, and another tab's activity
    // would never reach it.
    const match = COOKIE_PATTERN.exec(document.cookie)
    return match ? Number(match[1]) : null
  }

  /** Record an interaction. Client only; the server never stamps. */
  function touch(): void {
    if (import.meta.server) return
    const secure = location.protocol === 'https:' ? '; Secure' : ''
    document.cookie = `${COOKIE}=${now()}; Path=/; Max-Age=${COOKIE_MAX_AGE}; SameSite=Lax${secure}`
  }

  function isExpired(): boolean {
    return isIdleExpired(lastActivity(), now(), idleMs)
  }

  /**
   * Watch this page and call `onExpire` once when the window passes.
   * Returns the function that stops watching.
   */
  function start(onExpire: () => unknown): () => void {
    if (import.meta.server) return () => {}
    // Replace whatever is watching rather than stand down. The guard
    // this had — bail out if a watch exists — assumed the old layout
    // always unmounts before the new one mounts. When the order went the
    // other way the new instance got an inert stopper and the old
    // instance's `onBeforeUnmount` took the real watch down with it:
    // from then on that tab neither stamped nor signalled activity, and
    // the session family died under somebody still working (ADR 0062).
    stopCurrent?.()
    let expired = false
    const sessionAuthenticated = useState<boolean>('auth:session', () => false)
    const api = useApi()

    // A session from before this rule has no stamp. Adopt it now, or a
    // screen left open without being touched would never expire.
    if (lastActivity() === null) touch()

    function check(): void {
      if (expired || !isExpired()) return
      expired = true
      stop()
      void onExpire()
    }

    /**
     * Signal the interaction, and stamp the cookie once it landed.
     *
     * The stamp used to go first, unconditionally, with the signal fired
     * and forgotten after it. `last_activity_at` on the family is the
     * only clock the backend honours and `/auth/activity` is the only
     * thing that moves it, so every dropped signal pushed the browser's
     * idea of the session ahead of the server's — and an hour after the
     * drift began the user was thrown out mid-task, told the session had
     * *expired* (the cookie was fresh, so the inactivity wording was
     * ruled out) with nothing logged anywhere. Confirming first keeps
     * the two clocks within one round-trip of each other, and the
     * retry is the next interaction, 30 s away at most.
     */
    async function signal(): Promise<void> {
      if (!sessionAuthenticated.value) return
      try {
        await api.post('/api/v1/auth/activity', null)
        touch()
      } catch {
        // Left unstamped on purpose: if the backend did not take the
        // signal, this tab must not believe the session is younger than
        // the server does. A refusal that means the session is over has
        // already been turned into a logout by `useApi`'s refresh path,
        // which knows the code it was refused with.
      }
    }

    function onActivity(): void {
      const t = now()
      if (t - lastHandled < HANDLE_EVERY_MS) return
      lastHandled = t
      // Check before stamping. Timers do not run while a laptop sleeps, so
      // the first sign of life after three hours is usually a mouse
      // movement — and stamping it would quietly renew a session that had
      // already ended.
      if (isExpired()) return check()
      // No session to extend: nothing to confirm against, so the stamp
      // is this tab's own (the login screen, a public budget page).
      if (!sessionAuthenticated.value) return touch()
      void signal()
    }

    function onVisible(): void {
      if (document.visibilityState === 'visible') check()
    }

    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true, capture: true })
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', check)
    const timer = window.setInterval(check, CHECK_EVERY_MS)

    function stop(): void {
      for (const event of ACTIVITY_EVENTS) {
        window.removeEventListener(event, onActivity, { capture: true })
      }
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', check)
      window.clearInterval(timer)
      // Only if this watch is still the live one: a layout instance that
      // unmounts after its replacement started must take its own
      // listeners away and leave the replacement alone.
      if (stopCurrent === stop) stopCurrent = null
    }

    stopCurrent = stop
    return stop
  }

  return { touch, isExpired, start }
}
