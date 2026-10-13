import type { ApiResponse, Appointment } from '~~/app/types'

export interface PlanLackingConsent {
  plan_id: string
  plan_number: string | null
}

interface CompletionCheck {
  plans_lacking_consent: PlanLackingConsent[]
}

interface Pending {
  appointment: Appointment
  plans: PlanLackingConsent[]
}

/** The answer the open question is waiting for. Client-only, one at a time. */
let answer: ((go: boolean) => void) | null = null

/**
 * What is asked before an appointment is marked as completed.
 *
 * Any code that transitions an appointment to ``completed`` awaits
 * ``confirm(appointment)`` first and goes on only when it resolves true.
 * Today it asks one thing: the visit works on a plan whose informed
 * consent the clinic requires and nobody has signed. Going on without it
 * is the clinic's call — this asks, it never refuses. The question itself
 * is rendered once by ``CompletionCheckHost.vue``.
 *
 * Same two call-sites as ``useCompletionFollowup``.
 */
export function useCompletionCheck() {
  const api = useApi()
  const pending = useState<Pending | null>('agenda:completion-check:pending', () => null)

  async function confirm(appointment: Appointment): Promise<boolean> {
    let plans: PlanLackingConsent[] = []
    try {
      const response = await api.get<ApiResponse<CompletionCheck>>(
        `/api/v1/agenda/appointments/${appointment.id}/completion-check`
      )
      plans = response.data.plans_lacking_consent
    } catch {
      // The visit is completed without the question rather than held by it.
    }
    if (!plans.length) return true
    answer?.(false)
    pending.value = { appointment, plans }
    return new Promise<boolean>((resolve) => {
      answer = resolve
    })
  }

  function reply(go: boolean) {
    pending.value = null
    answer?.(go)
    answer = null
  }

  return { pending, confirm, reply }
}
