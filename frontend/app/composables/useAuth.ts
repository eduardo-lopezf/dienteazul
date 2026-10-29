import { appendResponseHeader, getRequestURL } from 'h3'
import type { User, LoginCredentials, MeResponse, ApiResponse } from '~/types'
import { loginLocation, reasonForCode, type SessionEndReason } from '~/utils/session'

interface RefreshSlot {
  inFlight?: Promise<boolean>
}

interface RefreshContext {
  _authRefreshSlot?: RefreshSlot
  _bffCookieOverrides?: Record<string, string>
}

export interface SessionEnd {
  returnTo?: string
  reason?: SessionEndReason
  /** The `request_id` of the refusal that ended it, for the login screen. */
  reference?: string
}

const LOGOUT_TIMEOUT_MS = 5_000
const clientRefreshSlot: RefreshSlot = {}
const CHANNEL_NAME = 'dienteazul:auth-session'
type SessionSignal = 'logout' | 'expired' | 'refreshed'
/** What a tab tells the others about a session that ended, beyond "it did". */
interface SessionEndSignal {
  signal?: SessionSignal
  sender?: string
  id?: string
  reason?: SessionEndReason
  reference?: string
}
const CLIENT_TAB_ID = import.meta.client ? crypto.randomUUID() : ''
let clientChannel: BroadcastChannel | null = null
let clientSignalListenerInstalled = false
let lastHandledSessionSignal = ''

function isAuthFailure(error: unknown): boolean {
  return (error as { statusCode?: number } | null)?.statusCode === 401
}

/**
 * What the backend said when it refused: the case, and the reference
 * that finds the line it logged (`app/core/auth/refusals.py`).
 *
 * The envelope travels through the BFF untouched, so both fields are on
 * the error's `data`; `x-request-id` is the fallback for a refusal that
 * never reached the app and so has no body — a gateway's, say.
 */
function refusalOf(error: unknown): { reason: SessionEndReason | null, reference?: string } {
  const failed = error as {
    data?: { code?: string, reference?: string }
    response?: { headers?: { get(name: string): string | null } }
  } | null
  return {
    reason: reasonForCode(failed?.data?.code),
    reference:
      failed?.data?.reference
      ?? failed?.response?.headers?.get('x-request-id')
      ?? undefined
  }
}

function cookieValue(name: string): string | null {
  if (import.meta.server) return null
  const escaped = name.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')
  return new RegExp(`(?:^|;\\s*)${escaped}=([^;]*)`).exec(document.cookie)?.[1] ?? null
}

function hasIncomingSessionCookie(event: ReturnType<typeof useRequestEvent>): boolean {
  const cookieHeader = event?.node.req.headers.cookie ?? ''
  return /(?:^|;\s*)(?:access_token|refresh_token)=/.test(cookieHeader)
}

export function useAuth() {
  const config = useRuntimeConfig()
  const router = useRouter()
  const requestEvent = import.meta.server ? useRequestEvent() : null
  const requestFetch = import.meta.server ? useRequestFetch() : $fetch
  const csrfCookie = useCookie<string | null>('csrf_token')
  // Resolved here, in the composable's body: `refreshInsideLock` runs
  // inside a Web Lock callback, and a composable asked for there is
  // outside the Nuxt context it needs.
  const activity = useSessionActivity()

  /**
   * Why a session the server has just refused ended.
   *
   * The backend refuses an idle family on refresh (ADR 0030, ADR 0052),
   * and whichever call notices first ends up here — a background poll as
   * readily as the inactivity watch. Saying "expired" then puts the wrong
   * notice on the login screen, and which of the two wins is a race.
   *
   * So the refusal itself decides: it carries the case it was refused
   * for (ADR 0062). The local stamp is only the fallback, for a refusal
   * with no code — an older backend, or a failure that never reached
   * the app. Guessing from the stamp was how an hour of unsignalled
   * activity came out as "expired": the cookie was fresh precisely
   * because the browser had been writing it without the server's
   * agreement.
   */
  function endedReason(code?: SessionEndReason | null): SessionEndReason {
    return code ?? (activity.isExpired() ? 'idle' : 'expired')
  }

  const user = useState<User | null>('auth:user', () => null)
  const permissions = useState<string[]>('auth:permissions', () => [])
  const clinicTimezone = useState<string | null>('auth:clinic-timezone', () => null)
  // A new clinic whose holder has not been through the welcome yet (review
  // it, accept the privacy agreement). Only its administrators are taken.
  const onboardingPending = useState<boolean>('auth:onboarding-pending', () => false)
  const clinicDeactivated = useState<boolean>('auth:clinic-deactivated', () => false)
  const privacyRenewal = useState<boolean>('auth:privacy-renewal', () => false)
  const session = useState<boolean>('auth:session', () => import.meta.server && hasIncomingSessionCookie(requestEvent ?? undefined))
  /**
   * How the last session ended, for whoever shows the login screen.
   *
   * Needed because the two know different halves. Only the refusal
   * knows the case and the reference; only the route middleware
   * actually performs the redirect when the session is refused during a
   * server render — `goToLogin` is client-only, so without this the
   * middleware fell back to a flat "expired" and dropped the reference
   * on exactly the renders that have no other way to report one.
   */
  const sessionEnd = useState<SessionEnd | null>('auth:session-end', () => null)
  const lastSessionSignal = useState<string>('auth:last-session-signal', () => '')
  const isAuthenticated = computed(() => !!user.value && session.value)
  const hasStoredSession = computed(() => session.value)

  async function bffFetch<T>(path: string, options: Record<string, unknown> = {}): Promise<T> {
    const method = String(options.method ?? 'GET').toUpperCase()
    const headers = new Headers(options.headers as HeadersInit | undefined)
    if (import.meta.server && requestEvent && !headers.has('origin')) {
      headers.set('origin', String(config.public.appOrigin || getRequestURL(requestEvent).origin))
    }
    if (import.meta.server && requestEvent) {
      const overrides = (requestEvent.context as RefreshContext)._bffCookieOverrides ?? {}
      if (Object.keys(overrides).length) {
        const cookies = new Map((requestEvent.node.req.headers.cookie ?? '').split(';').filter(Boolean).map((part) => {
          const separator = part.indexOf('=')
          return [part.slice(0, separator).trim(), part.slice(separator + 1).trim()]
        }))
        for (const [name, value] of Object.entries(overrides)) cookies.set(name, value)
        headers.set('cookie', [...cookies].map(([name, value]) => `${name}=${value}`).join('; '))
      }
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      let csrf = import.meta.client ? cookieValue('csrf_token') : csrfCookie.value
      if (!csrf) {
        await bffFetch('/api/v1/auth/csrf')
        csrf = import.meta.client ? cookieValue('csrf_token') : csrfCookie.value
      }
      if (csrf) headers.set('x-csrf-token', decodeURIComponent(csrf))
    }
    const onResponse = ({ response }: { response: Response }) => {
      if (!import.meta.server || !requestEvent) return
      const cookies = response.headers.getSetCookie?.() ?? [response.headers.get('set-cookie')].filter((value): value is string => !!value)
      const context = requestEvent.context as RefreshContext
      context._bffCookieOverrides ??= {}
      for (const cookie of cookies) {
        appendResponseHeader(requestEvent, 'set-cookie', cookie)
        const [pair] = cookie.split(';', 1)
        const separator = pair?.indexOf('=') ?? -1
        if (separator < 1) continue
        const name = pair!.slice(0, separator)
        const value = pair!.slice(separator + 1)
        if (['access_token', 'refresh_token', 'csrf_token'].includes(name)) {
          context._bffCookieOverrides[name] = value
          if (name === 'csrf_token') csrfCookie.value = value
        }
      }
    }
    // A plain object, not the `Headers` instance: `useRequestFetch` keeps
    // the headers it forwards from the incoming request and drops a
    // `Headers` passed alongside them. What went missing were the two this
    // function exists to add — `origin` and `x-csrf-token` — so every
    // server-side refresh was rejected by our own BFF with a 403, and a
    // render whose access token had expired bounced to the login screen
    // instead of renewing the session.
    return await requestFetch(path, {
      ...options,
      headers: Object.fromEntries(headers),
      onResponse
    } as never) as T
  }

  function request<T>(path: string, options: Record<string, unknown> = {}): Promise<T> {
    return bffFetch<T>(path, options)
  }

  function refreshSlot(): RefreshSlot {
    if (import.meta.client) return clientRefreshSlot
    const context = requestEvent?.context as RefreshContext | undefined
    if (!context) return {}
    return (context._authRefreshSlot ??= {})
  }

  function clearSession(): void {
    session.value = false
    user.value = null
    permissions.value = []
    clinicTimezone.value = null
    onboardingPending.value = false
    clinicDeactivated.value = false
    privacyRenewal.value = false
  }

  function broadcast(signal: SessionSignal, end: Pick<SessionEnd, 'reason' | 'reference'> = {}): void {
    if (!import.meta.client) return
    const message: SessionEndSignal = { signal, sender: CLIENT_TAB_ID, id: crypto.randomUUID(), ...end }
    try {
      clientChannel ??= new BroadcastChannel(CHANNEL_NAME)
      clientChannel.postMessage(message)
    } catch {
      localStorage.setItem(CHANNEL_NAME, JSON.stringify(message))
      localStorage.removeItem(CHANNEL_NAME)
    }
  }

  async function fetchUserDirect(): Promise<void> {
    const response = await bffFetch<ApiResponse<MeResponse>>('/api/v1/auth/me')
    user.value = response.data.user
    permissions.value = response.data.permissions
    clinicTimezone.value = response.data.clinics[0]?.timezone ?? null
    const clinic = response.data.clinics[0]
    const admin = clinic?.role === 'admin'
    // Held at `/onboarding` either for the whole welcome or, when the
    // agreement it accepted is no longer the one in force, for that alone.
    onboardingPending.value = admin && (clinic?.onboarding_pending === true || clinic?.privacy_renewal === true)
    privacyRenewal.value = admin && clinic?.onboarding_pending !== true && clinic?.privacy_renewal === true
    clinicDeactivated.value = clinic?.deactivated === true
    session.value = true
  }

  async function goToLogin(end: SessionEnd): Promise<void> {
    if (!import.meta.client) return
    // Already there: say nothing and change nothing. Two things notice a
    // session ending — the inactivity watch and the first refused request
    // — and the second one arrives when the login screen is already up.
    // `end.returnTo` is then the current route, which is `/login` itself:
    // `safeRedirect` refuses it, so pushing again replaced a URL carrying
    // `redirect=/patients?page=1` with one carrying nothing, and signing
    // in landed on the dashboard instead of the page the session ended
    // on. It would also relabel an explicit logout as an expiry.
    if (router.currentRoute.value.path === '/login') return
    await router.push(loginLocation(end.returnTo, end.reason, end.reference))
  }

  async function endSession(end: SessionEnd = {}): Promise<void> {
    clearSession()
    sessionEnd.value = { reason: end.reason, reference: end.reference }
    // The other tabs are about to show the same screen; send them the
    // case and the reference too, so all of them say the same thing and
    // quote the same line of the log instead of each guessing.
    broadcast('expired', { reason: end.reason, reference: end.reference })
    await goToLogin(end)
  }

  async function refreshInsideLock(): Promise<boolean> {
    // A different tab may have rotated the shared cookies while this tab waited.
    try {
      await fetchUserDirect()
      return true
    } catch (error) {
      if (!isAuthFailure(error)) throw error
    }

    try {
      await bffFetch('/api/v1/auth/refresh', { method: 'POST', body: {} })
    } catch (error) {
      if (!isAuthFailure(error)) throw error
      const refusal = refusalOf(error)
      await endSession({
        returnTo: router.currentRoute.value.fullPath,
        reason: endedReason(refusal.reason),
        reference: refusal.reference
      })
      return false
    }

    try {
      await fetchUserDirect()
    } catch (error) {
      if (!isAuthFailure(error)) console.error('Session refreshed, but /auth/me failed:', error)
    }
    broadcast('refreshed')
    return true
  }

  async function refresh(): Promise<boolean> {
    const slot = refreshSlot()
    if (slot.inFlight) return slot.inFlight
    const run = async (): Promise<boolean> => {
      if (import.meta.client && navigator.locks) {
        return navigator.locks.request('dienteazul:auth-refresh', refreshInsideLock)
      }
      return refreshInsideLock()
    }
    const inFlight = run()
    slot.inFlight = inFlight
    try {
      return await inFlight
    } finally {
      if (slot.inFlight === inFlight) slot.inFlight = undefined
    }
  }

  async function login(credentials: LoginCredentials): Promise<void> {
    const formData = new URLSearchParams({ username: credentials.email, password: credentials.password })
    await bffFetch('/api/v1/auth/login', {
      method: 'POST',
      body: formData,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
    })
    session.value = true
    sessionEnd.value = null
    activity.touch()
    await fetchUserDirect()
    broadcast('refreshed')
  }

  /** Adopt cookies issued by first-run setup without signing in twice. */
  async function adoptSession(): Promise<void> {
    session.value = true
    await fetchUserDirect()
    broadcast('refreshed')
  }

  async function terminate(): Promise<void> {
    const hadSession = session.value
    clearSession()
    broadcast('logout')
    if (!hadSession) return
    const revocation = bffFetch('/api/v1/auth/logout', {
      method: 'POST',
      body: {},
      timeout: LOGOUT_TIMEOUT_MS
    }).catch(() => undefined)
    if (import.meta.server) await revocation
  }

  async function logout(end: SessionEnd = {}): Promise<void> {
    await terminate()
    await goToLogin(end)
  }

  async function fetchUser(): Promise<void> {
    if (!session.value) return
    try {
      await fetchUserDirect()
    } catch (error) {
      if (isAuthFailure(error)) await refresh()
      else {
        console.error('Failed to fetch user:', error)
        throw error
      }
    }
  }

  async function init(): Promise<void> {
    if (import.meta.server) {
      session.value ||= hasIncomingSessionCookie(requestEvent ?? undefined)
    }
    if (!session.value || user.value) return
    try {
      await refresh()
    } catch (error) {
      if (!isAuthFailure(error)) console.error('Failed to initialize session:', error)
    }
  }

  if (import.meta.client && !clientSignalListenerInstalled) {
    clientSignalListenerInstalled = true
    const receiveSignal = (data: SessionEndSignal) => {
      if (data?.sender === CLIENT_TAB_ID || (data?.id && (lastSessionSignal.value === data.id || lastHandledSessionSignal === data.id))) return
      if (data?.id) {
        lastSessionSignal.value = data.id
        lastHandledSessionSignal = data.id
      }
      if (data?.signal === 'logout' || data?.signal === 'expired') {
        clearSession()
        sessionEnd.value = data.signal === 'expired'
          ? { reason: endedReason(data.reason), reference: data.reference }
          : null
        void goToLogin(data.signal === 'expired'
          ? {
              returnTo: router.currentRoute.value.fullPath,
              reason: endedReason(data.reason),
              reference: data.reference
            }
          : {})
      }
      if (data?.signal === 'refreshed') {
        session.value = true
        void fetchUserDirect().catch(() => undefined)
      }
    }
    if (typeof BroadcastChannel !== 'undefined') {
      clientChannel ??= new BroadcastChannel(CHANNEL_NAME)
      clientChannel.onmessage = ({ data }: MessageEvent<SessionEndSignal>) => receiveSignal(data)
    } else {
      window.addEventListener('storage', (event) => {
        if (event.key !== CHANNEL_NAME || !event.newValue) return
        receiveSignal(JSON.parse(event.newValue) as SessionEndSignal)
      })
    }
  }

  return {
    user: readonly(user),
    sessionEnd: readonly(sessionEnd),
    permissions: readonly(permissions),
    clinicTimezone: readonly(clinicTimezone),
    onboardingPending: readonly(onboardingPending),
    clinicDeactivated: readonly(clinicDeactivated),
    privacyRenewal: readonly(privacyRenewal),
    request,
    isAuthenticated,
    hasStoredSession,
    login,
    logout,
    terminate,
    refresh,
    fetchUser,
    init,
    adoptSession
  }
}
