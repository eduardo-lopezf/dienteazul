import { loginLocation, safeRedirect } from '~/utils/session'

const SETUP_PATH = '/setup'
const CHANGE_PASSWORD_PATH = '/change-password'
const ONBOARDING_PATH = '/onboarding'

// Module-level cache. The system can only flip from uninitialized → initialized
// (never back), so once we've seen `true` we stop asking the backend.
let systemInitialized: boolean | null = null

async function isSystemInitialized(): Promise<boolean> {
  if (systemInitialized === true) return true
  try {
    const res = await useApi().get<{ data: { initialized: boolean } }>('/api/v1/auth/setup/status')
    systemInitialized = res.data.initialized
  } catch {
    // Backend unreachable: don't trap the user on /setup — assume initialized
    // so they land on /login and hit the normal error path there.
    systemInitialized = true
  }
  return systemInitialized
}

export default defineNuxtRouteMiddleware(async (to) => {
  const auth = useAuth()
  const activity = useSessionActivity()

  // ``/p/budget/<token>`` is the patient-facing budget view (ADR 0006),
  // authorized server-side via a token-scoped 2FA cookie; let it render.
  const publicRoutes = ['/login', SETUP_PATH, '/p/budget']
  const isPublicRoute = publicRoutes.some(route => to.path === route || to.path.startsWith(route + '/'))

  // An idle session ends here, before `init()`: that would refresh the
  // tokens — spending one — for a session this is about to end. On the
  // server this is what keeps a tab reopened the next morning from
  // rendering a single patient before it is sent to login (ADR 0030).
  if (auth.hasStoredSession.value && activity.isExpired()) {
    await auth.terminate()
    if (isPublicRoute) return
    return navigateTo(loginLocation(to.fullPath, 'idle'))
  }

  // Captured before `init()` clears a refused session, so the login screen
  // can say the session ended rather than greet a stranger.
  const hadSession = auth.hasStoredSession.value

  // Initialize auth state (fetch user if token exists) - works on server and client
  await auth.init()

  if (auth.isAuthenticated.value) {
    // An account still on a password somebody else set goes nowhere else:
    // the backend refuses it everything but this (`must_change_password`).
    if (auth.user.value?.must_change_password) {
      return to.path === CHANGE_PASSWORD_PATH ? undefined : navigateTo(CHANGE_PASSWORD_PATH)
    }
    // The change-password screen itself is open to anyone signed in: it
    // must never bounce a user the backend is still holding to it.
    if (to.path === CHANGE_PASSWORD_PATH) return
    // The holder of a new clinic goes through the welcome before anything
    // else: review the clinic, then accept the privacy agreement.
    if (auth.onboardingPending.value) {
      return to.path === ONBOARDING_PATH ? undefined : navigateTo(ONBOARDING_PATH)
    }
    if (to.path === ONBOARDING_PATH) return navigateTo('/')
    // Authenticated users skip both the login page and the first-run wizard.
    // An open login tab that finds a session resumes where it was pointed.
    if (to.path === '/login' || to.path === SETUP_PATH) {
      return navigateTo(safeRedirect(to.query.redirect) ?? '/')
    }
    return
  }

  // Unauthenticated. A fresh system has no account yet → first-run wizard.
  if (!(await isSystemInitialized())) {
    return to.path === SETUP_PATH ? undefined : navigateTo(SETUP_PATH)
  }

  // System already initialized: the wizard is closed.
  if (to.path === SETUP_PATH) return navigateTo('/login')

  // Carry the destination, so a bookmark or a link opened without a session
  // lands there after login instead of on the dashboard.
  if (!isPublicRoute) {
    return navigateTo(loginLocation(to.fullPath, hadSession ? 'expired' : undefined))
  }
})
