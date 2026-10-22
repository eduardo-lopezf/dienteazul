import type { ApiResponse, PaginatedResponse } from '~/types'

/** The error envelope every failure from this API carries. */
interface ErrorEnvelope {
  message?: string
  code?: string | null
  category?: string | null
  reference?: string | null
  fields?: Record<string, string>
}

/** What `useApi` hangs off a thrown error, for callers that want it. */
export interface ApiFailure {
  code: string | null
  category: string | null
  /** The request id. What a user quotes and an operator greps for. */
  reference: string | null
  fields: Record<string, string>
}

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

interface UseApiOptions {
  method?: HttpMethod
  // Accept any plain object so callers can pass a typed domain payload
  // (e.g. ``BudgetCreate``) without an ``as unknown as Record<…>`` cast.
  // ``$fetch`` serializes via JSON.stringify, which handles any object.
  body?: object | null
  headers?: Record<string, string>
  skipAuth?: boolean
  // Query-string params appended to the path. Undefined/null values are
  // skipped. Provided because $fetch's own ``query`` was not wired here,
  // so callers that passed ``{ params: … }`` had it silently dropped
  // (e.g. the Veri*Factu queue tabs all rendered the same list).
  query?: Record<string, string | number | boolean | undefined | null>
  // Optional AbortSignal so callers can cancel in-flight requests
  // (debounced lookups, component unmount, etc.).
  signal?: AbortSignal
  responseType?: 'blob' | 'arrayBuffer' | 'text' | 'stream'
}

function _withQuery(path: string, query?: UseApiOptions['query']): string {
  if (!query) return path
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) qs.set(k, String(v))
  }
  const s = qs.toString()
  if (!s) return path
  return path.includes('?') ? `${path}&${s}` : `${path}?${s}`
}

/**
 * The message with the reference after it, when there is one.
 *
 * Kept on one line so it survives a toast that does not wrap, and
 * prefixed with a word rather than shown bare: an unexplained hex string
 * next to an error reads as part of the failure.
 */
function withReference(message: string, reference: string | null): string {
  return reference ? `${message} (ref. ${reference})` : message
}

export function useApi() {
  const auth = useAuth()
  const { t } = useI18n()
  const toast = useToast()

  async function $api<T>(
    path: string,
    options: UseApiOptions = {}
  ): Promise<T> {
    const { skipAuth, method, body, headers: optionHeaders, signal, query, responseType } = options

    const headers: Record<string, string> = {
      ...(optionHeaders || {})
    }

    const url = _withQuery(path, query)

    try {
      return await auth.request<T>(url, {
        timeout: 10000, // 10 seconds
        method,
        body,
        headers,
        signal,
        responseType
      })
    } catch (error: unknown) {
      const fetchError = error as {
        name?: string
        statusCode?: number
        data?: ErrorEnvelope
        response?: { headers?: { get(name: string): string | null } }
      }

      // Put what the backend said about this failure on the error itself,
      // so a caller can branch on the case (`code`) or show the reference
      // without re-reading the envelope. See `app/core/errors.py`.
      const failure: ApiFailure = {
        code: fetchError.data?.code ?? null,
        category: fetchError.data?.category ?? null,
        // The body carries it; the header is the fallback for a failure
        // that never reached the app — a gateway's 502, say.
        reference:
          fetchError.data?.reference
          ?? fetchError.response?.headers?.get('x-request-id')
          ?? null,
        fields: fetchError.data?.fields ?? {}
      }
      Object.assign(error as object, { failure })

      // Caller-initiated cancellation: don't toast, just rethrow so the
      // caller can no-op. AbortController is used by orchestrators
      // (e.g. dashboard) to cancel stale parallel fetches.
      if (fetchError.name === 'AbortError' || signal?.aborted) {
        throw error
      }

      // Handle specific error codes
      if (fetchError.statusCode === 401 && !skipAuth) {
        // Refresh uses a cross-tab lock and first probes /auth/me, so a tab
        // arriving after another tab rotated the cookie adopts that session
        // rather than presenting a spent refresh token.
        let refreshed: boolean
        try {
          refreshed = await auth.refresh()
        } catch {
          // A transport failure is not proof that the session ended.
          throw error
        }
        if (refreshed) {
          return await auth.request<T>(url, {
            timeout: 10000,
            method,
            body,
            headers,
            signal,
            responseType
          })
        } else {
          throw error
        }
      }

      if (fetchError.statusCode === 403) {
        // An account still on the password it was created with is refused
        // everything until it sets its own. The middleware normally sends
        // it to the change-password screen before any request is made;
        // this is the net under it — whatever let the app load, the first
        // refusal takes the user there instead of showing "access denied"
        // on every screen with no way forward.
        if (fetchError.data?.message === 'Password change required') {
          await navigateTo('/change-password')
          throw error
        }
        // What the account's tier allows was reached: say that, wherever
        // the user or the file was being added from.
        const limitReached = {
          'User limit reached': 'settings.workspace.limits.userLimitReached',
          'Storage limit reached': 'settings.workspace.limits.storageLimitReached'
        }[fetchError.data?.message ?? '']
        // The same net under the welcome of a new clinic: the backend
        // holds it until its holder accepts the privacy agreement.
        if (fetchError.data?.message === 'Onboarding required') {
          await navigateTo('/onboarding')
          throw error
        }
        toast.add({
          title: t('common.error'),
          description: limitReached ? t(limitReached) : t('common.forbidden', 'Acceso denegado'),
          color: 'error'
        })
        throw error
      }

      if (fetchError.statusCode === 404) {
        throw error
      }

      if (fetchError.statusCode === 409) {
        // Conflict - let the caller handle it
        throw error
      }

      if (fetchError.statusCode === 422) {
        // Validation error - let the caller handle it
        throw error
      }

      if (fetchError.statusCode && fetchError.statusCode >= 500) {
        // The reference is the whole point of showing anything here: the
        // message is deliberately vague (it could quote patient data), so
        // what the person needs is the string that leads whoever looks
        // straight to this request's log lines and its `ServerError` row.
        toast.add({
          title: t('common.error'),
          description: withReference(t('common.serverError'), failure.reference),
          color: 'error'
        })
        throw error
      }

      // Network error
      if (!fetchError.statusCode) {
        toast.add({
          title: t('common.error'),
          description: t('common.networkError'),
          color: 'error'
        })
      }

      throw error
    }
  }

  // Convenience methods
  async function get<T>(path: string, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'GET' })
  }

  async function post<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'POST', body })
  }

  async function put<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'PUT', body })
  }

  async function patch<T>(path: string, body?: object | null, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'PATCH', body })
  }

  async function del<T>(path: string, options: Omit<UseApiOptions, 'method' | 'body'> = {}): Promise<T> {
    return $api<T>(path, { ...options, method: 'DELETE' })
  }

  async function requestResponse(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers)
    const method = (init.method ?? 'GET').toUpperCase()
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const csrf = import.meta.client
        ? /(?:^|;\s*)csrf_token=([^;]*)/.exec(document.cookie)?.[1]
        : useCookie<string | null>('csrf_token').value
      if (csrf) headers.set('x-csrf-token', decodeURIComponent(csrf))
    }
    const send = () => fetch(path, { ...init, headers, credentials: 'same-origin' })
    const response = await send()
    const body = init.body
    const replayable = body === undefined || typeof body === 'string' || body instanceof FormData
      || body instanceof Blob || body instanceof URLSearchParams || body instanceof ArrayBuffer
      || ArrayBuffer.isView(body)
    if (response.status === 401 && replayable) {
      let refreshed: boolean
      try {
        refreshed = await auth.refresh()
      } catch {
        return response
      }
      if (refreshed) return await send()
    }
    return response
  }

  return {
    $api,
    get,
    post,
    put,
    patch,
    del,
    requestResponse
  }
}

// Type helpers for API responses
export type { ApiResponse, PaginatedResponse }
