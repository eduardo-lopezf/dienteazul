import {
  createError,
  deleteCookie,
  getCookie,
  getHeader,
  getRequestURL,
  getRouterParam,
  getRequestHeaders,
  readRawBody,
  sendStream,
  setCookie,
  setResponseStatus
} from 'h3'
import { randomBytes } from 'node:crypto'
import { Readable } from 'node:stream'

const TOKEN_MAX_AGE = 60 * 60 * 24 * 30
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'
])

function cookieOptions(secure: boolean) {
  return { httpOnly: true, secure, sameSite: 'lax' as const, path: '/', maxAge: TOKEN_MAX_AGE }
}

function setAuthCookies(event: Parameters<typeof setCookie>[0], access: string, refresh: string, secure: boolean) {
  const options = cookieOptions(secure)
  setCookie(event, 'access_token', access, options)
  setCookie(event, 'refresh_token', refresh, options)
}

function clearAuthCookies(event: Parameters<typeof deleteCookie>[0], secure: boolean) {
  const options = { httpOnly: true, secure, sameSite: 'lax' as const, path: '/' }
  deleteCookie(event, 'access_token', options)
  deleteCookie(event, 'refresh_token', options)
}

function safePath(event: Parameters<typeof getRouterParam>[0]): string {
  const path = getRouterParam(event, 'path') ?? ''
  // One trailing slash is part of a route, not an empty segment: FastAPI
  // tells `recalls/` (the list, `@router.get("/")`) from `recalls`, so it
  // is kept on the way up. Empty segments elsewhere, `.` and `..` are not.
  // The router param loses it, so it is read off the request's own path.
  const trailingSlash = getRequestURL(event).pathname.endsWith('/')
  const segments = path.replace(/\/$/, '').split('/')
  if (!path || segments.some(part => !part || part === '.' || part === '..' || !/^[\w.~%-]+$/.test(part))) {
    throw createError({ statusCode: 404, statusMessage: 'Not found' })
  }
  return segments.join('/') + (trailingSlash ? '/' : '')
}

function safeUpstreamHeaders(event: Parameters<typeof getRequestHeaders>[0], accessToken?: string): Headers {
  const headers = new Headers()
  for (const [name, value] of Object.entries(getRequestHeaders(event))) {
    const lower = name.toLowerCase()
    if (HOP_BY_HOP.has(lower) || lower === 'authorization' || lower === 'cookie' || lower === 'x-csrf-token') continue
    if (value !== undefined) headers.set(name, value)
  }
  if (accessToken) headers.set('authorization', `Bearer ${accessToken}`)
  return headers
}

function forwardPublicBudgetCookie(event: Parameters<typeof getRequestHeaders>[0], apiPath: string, headers: Headers): void {
  const match = /^budget\/public\/budgets\/([0-9a-f-]{36})(?:\/|$)/i.exec(apiPath)
  if (!match) return
  const wanted = `bdg_session_${match[1]}`
  const pair = (getHeader(event, 'cookie') ?? '').split(';').map(value => value.trim())
    .find(value => value.startsWith(`${wanted}=`))
  if (pair) headers.set('cookie', pair)
}

function copyResponseHeaders(event: Parameters<typeof setResponseStatus>[0], response: Response): void {
  for (const [name, value] of response.headers) {
    const lower = name.toLowerCase()
    if (HOP_BY_HOP.has(lower) || lower === 'set-cookie') continue
    // Fetch transparently decodes compressed bodies; forwarding these headers
    // would describe bytes that are no longer on the stream.
    if (lower === 'content-encoding' || lower === 'content-length') continue
    event.node.res.setHeader(name, value)
  }
}

function appendSetCookies(event: Parameters<typeof setCookie>[0], response: Response): void {
  for (const cookie of response.headers.getSetCookie()) {
    event.node.res.appendHeader('set-cookie', cookie)
  }
}

/**
 * One rotation per token, replayed to whoever arrives with the spent one.
 *
 * Rotation spends the token it is given and treats a second presentation as
 * theft: `sessions.rotate` revokes the family, with no grace window. The
 * client honours that with an in-flight slot, but two tabs are two server
 * renders and nothing on this side serialized them.
 *
 * They do not even overlap. Measured on a cold dev server: tab A refreshed
 * and rotated, and tab B — whose render had left with the cookie it held at
 * click time — presented the same token **4.3 s later**. Both tabs lost the
 * session (`revoked_reason = reuse`). So collapsing concurrent calls is not
 * enough; the answer has to outlive the first one.
 *
 * The first caller goes to the backend. Anyone presenting that same token
 * while the entry lives gets the same rotated pair, so every tab ends up
 * with the same cookies and the family is rotated once.
 *
 * What this costs, stated plainly: inside the window a stolen token is
 * answered instead of triggering revocation. It is `REFRESH_REPLAY_MS`
 * long, it lives in one process, and it only ever replays to a caller that
 * already holds that exact token. Past the window, and for every token this
 * process has not just rotated, reuse detection is untouched — including in
 * another frontend replica, which shares none of this (ADR 0051).
 */
type RefreshSnapshot = {
  status: number
  statusText: string
  headers: [string, string][]
  body: string
}

/** Long enough for a slow render to follow a fast one; short enough to matter. */
const REFRESH_REPLAY_MS = 10_000

const refreshesInFlight = new Map<string, Promise<RefreshSnapshot>>()
const refreshReplay = new Map<string, { at: number, snapshot: RefreshSnapshot }>()

function refreshOnce(token: string, send: () => Promise<Response>): Promise<RefreshSnapshot> {
  const now = Date.now()
  for (const [spent, entry] of refreshReplay) {
    if (now - entry.at > REFRESH_REPLAY_MS) refreshReplay.delete(spent)
  }
  const replayed = refreshReplay.get(token)
  if (replayed) return Promise.resolve(replayed.snapshot)
  const pending = refreshesInFlight.get(token)
  if (pending) return pending

  const attempt = (async (): Promise<RefreshSnapshot> => {
    const response = await send()
    const snapshot: RefreshSnapshot = {
      status: response.status,
      statusText: response.statusText,
      headers: [...response.headers] as [string, string][],
      body: await response.text()
    }
    // Only a rotation is worth repeating. A refusal is the backend's answer
    // to this caller and may not be the next one's.
    if (snapshot.status === 200) refreshReplay.set(token, { at: Date.now(), snapshot })
    return snapshot
  })()
  refreshesInFlight.set(token, attempt)
  void attempt.catch(() => undefined).finally(() => refreshesInFlight.delete(token))
  return attempt
}

async function tokenResponse(
  event: Parameters<typeof setCookie>[0],
  response: Response,
  secure: boolean
): Promise<Response> {
  const type = response.headers.get('content-type') ?? ''
  if (!type.includes('application/json')) return response
  const data = await response.clone().json().catch(() => null) as Record<string, unknown> | null
  if (!data) return response
  const access = typeof data.access_token === 'string' ? data.access_token : ''
  const refresh = typeof data.refresh_token === 'string' ? data.refresh_token : ''
  if (access && refresh) setAuthCookies(event, access, refresh, secure)
  const sanitized = { ...data }
  delete sanitized.access_token
  delete sanitized.refresh_token
  const headers = new Headers(response.headers)
  headers.delete('content-length')
  headers.delete('content-encoding')
  headers.delete('set-cookie')
  return new Response(JSON.stringify(sanitized), {
    status: response.status,
    statusText: response.statusText,
    headers
  })
}

/**
 * The control plane's endpoint (`/api/v1/ops`, ADR 0049 rule 4), relayed
 * as it came. It is authorised by a short-lived token the operator's panel
 * signs with the secret it shares with the backend, never by a browser
 * session: its `Authorization` header is kept, no session cookie is
 * attached, and there is no CSRF check — that guards the cookies, which
 * this path does not read. It lets a deployment that publishes only the
 * frontend be administered at that same address.
 */
async function relayOps(event: Parameters<typeof getRouterParam>[0], backend: string) {
  const apiPath = safePath(event)
  const url = new URL(`${backend.replace(/\/$/, '')}/api/v1/${apiPath}${getRequestURL(event).search}`)
  const headers = new Headers()
  for (const [name, value] of Object.entries(getRequestHeaders(event))) {
    const lower = name.toLowerCase()
    if (HOP_BY_HOP.has(lower) || lower === 'cookie' || lower === 'x-csrf-token') continue
    if (value !== undefined) headers.set(name, value)
  }
  const method = event.method.toUpperCase()
  // Streamed, not read whole: a copy of a deployment travels this way.
  const body = ['GET', 'HEAD'].includes(method) ? undefined : Readable.toWeb(event.node.req) as ReadableStream<Uint8Array>
  const response = await fetch(url, {
    method,
    headers,
    body,
    redirect: 'manual',
    ...(body ? { duplex: 'half' } : {})
  } as RequestInit & { duplex?: 'half' })
  setResponseStatus(event, response.status, response.statusText)
  copyResponseHeaders(event, response)
  if (method === 'HEAD' || response.status === 204 || response.status === 304) return null
  if (response.body) return sendStream(event, response.body)
  return null
}

export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig(event)
  if ((getRouterParam(event, 'path') ?? '').startsWith('ops/')) {
    return relayOps(event, String(config.apiBaseUrlServer || ''))
  }
  const secure = process.env.NODE_ENV === 'production'
  let csrf = getCookie(event, 'csrf_token')
  if (!csrf) {
    csrf = randomBytes(32).toString('base64url')
    setCookie(event, 'csrf_token', csrf, {
      httpOnly: false,
      secure,
      sameSite: 'lax',
      path: '/',
      maxAge: TOKEN_MAX_AGE
    })
  }
  const csrfToken = csrf

  const method = event.method.toUpperCase()
  const unsafe = !['GET', 'HEAD', 'OPTIONS'].includes(method)
  if (unsafe) {
    const origin = getHeader(event, 'origin')
    let expectedOrigin = getRequestURL(event).origin
    if (config.public.appOrigin) {
      try {
        expectedOrigin = new URL(String(config.public.appOrigin)).origin
      } catch {
        throw createError({ statusCode: 500, statusMessage: 'Invalid application origin configuration' })
      }
    }
    const headerToken = getHeader(event, 'x-csrf-token')
    const logoutRequest = getRouterParam(event, 'path') === 'auth/logout'
    if (!origin || origin !== expectedOrigin || (!logoutRequest && (!csrfToken || !headerToken || headerToken !== csrfToken))) {
      throw createError({ statusCode: 403, statusMessage: 'CSRF validation failed' })
    }
  }

  const apiPath = safePath(event)
  if (apiPath === 'auth/csrf' && method === 'GET') {
    setResponseStatus(event, 204)
    return null
  }
  const backend = String(config.apiBaseUrlServer || '').replace(/\/$/, '')
  let backendUrl: URL
  try {
    backendUrl = new URL(`${backend}/api/v1/${apiPath}${getRequestURL(event).search}`)
  } catch {
    throw createError({ statusCode: 500, statusMessage: 'Backend API is not configured' })
  }
  if (!['http:', 'https:'].includes(backendUrl.protocol)) {
    throw createError({ statusCode: 500, statusMessage: 'Invalid backend API configuration' })
  }

  const accessToken = getCookie(event, 'access_token')
  const refreshToken = getCookie(event, 'refresh_token')
  const authLoginOrSetup = apiPath === 'auth/login' || apiPath === 'auth/setup'
  const authRefresh = apiPath === 'auth/refresh'
  const authLogout = apiPath === 'auth/logout'
  let body: Buffer | ReadableStream<Uint8Array> | undefined
  let replayableBody = true
  if (!['GET', 'HEAD'].includes(method)) {
    const contentLength = Number(getHeader(event, 'content-length') ?? 0)
    if (contentLength > 2 * 1024 * 1024 || !!getHeader(event, 'transfer-encoding')) {
      body = Readable.toWeb(event.node.req) as ReadableStream<Uint8Array>
      replayableBody = false
    } else {
      body = await readRawBody(event, false) as Buffer | undefined
    }
  }
  if (authRefresh) body = Buffer.from(JSON.stringify({ refresh_token: refreshToken ?? '' }))
  if (authLogout) body = Buffer.from(JSON.stringify({ refresh_token: refreshToken ?? '' }))

  const headers = safeUpstreamHeaders(event, authLoginOrSetup || authRefresh || authLogout ? undefined : accessToken)
  forwardPublicBudgetCookie(event, apiPath, headers)
  if (authRefresh || authLogout) headers.set('content-type', 'application/json')

  const send = (requestBody: Buffer | ReadableStream<Uint8Array> | undefined, requestHeaders: Headers, url = backendUrl) =>
    fetch(url, {
      method,
      headers: requestHeaders,
      body: requestBody as BodyInit | undefined,
      redirect: 'manual',
      ...(replayableBody ? {} : { duplex: 'half' })
    } as RequestInit & { duplex?: 'half' })

  let response: Response
  if (authRefresh && refreshToken) {
    const snapshot = await refreshOnce(refreshToken, () => send(body, headers))
    response = new Response(snapshot.body || null, {
      status: snapshot.status,
      statusText: snapshot.statusText,
      headers: new Headers(snapshot.headers)
    })
  } else {
    response = await send(body, headers)
  }

  if (authRefresh && response.status === 401) clearAuthCookies(event, secure)
  if (authLogout) clearAuthCookies(event, secure)
  if (authLoginOrSetup && !response.ok) clearAuthCookies(event, secure)

  if (authLoginOrSetup || authRefresh) response = await tokenResponse(event, response, secure)
  appendSetCookies(event, response)
  setResponseStatus(event, response.status, response.statusText)
  copyResponseHeaders(event, response)

  if (method === 'HEAD' || response.status === 204 || response.status === 304) return null
  if (response.body) return sendStream(event, response.body)
  return null
})
