/**
 * The three queues a clinic works through.
 *
 * Each list is fetched on demand — opening the screen should not cost
 * three cross-module queries when the user only reads one tab.
 */
import type { ApiResponse } from '~~/app/types'

export type ActionableKey = 'owes_not_booked' | 'accepted_not_booked' | 'no_visit'

export interface ActionableRow {
  patient_id: string
  patient_name: string
  phone: string | null
  email: string | null
  /** Money owed, or the budget's total. Null on the no-visit list. */
  amount: string | null
  /** Days of debt, or days since the last visit. */
  days: number | null
  /** The budget number, on the accepted-not-booked list. */
  detail: string | null
}

export interface ActionableList {
  key: ActionableKey
  rows: ActionableRow[]
  /** The server capped the list; there are more behind it. */
  truncated: boolean
}

interface ListState {
  loading: boolean
  loaded: boolean
  error: boolean
  data: ActionableList | null
}

const PATHS: Record<ActionableKey, string> = {
  owes_not_booked: '/api/v1/reports/actionable/owes-not-booked',
  accepted_not_booked: '/api/v1/reports/actionable/accepted-not-booked',
  no_visit: '/api/v1/reports/actionable/no-visit'
}

function blank(): ListState {
  return { loading: false, loaded: false, error: false, data: null }
}

export function useActionableLists() {
  const api = useApi()

  const state = reactive<Record<ActionableKey, ListState>>({
    owes_not_booked: blank(),
    accepted_not_booked: blank(),
    no_visit: blank()
  })

  /** The debt threshold and the staleness window are the user's to set. */
  const minimum = ref(0)
  const months = ref(12)

  function query(key: ActionableKey): string {
    if (key === 'owes_not_booked') return `?minimum=${minimum.value}`
    if (key === 'no_visit') return `?months=${months.value}`
    return ''
  }

  async function load(key: ActionableKey, force = false): Promise<void> {
    const list = state[key]
    if (list.loading || (list.loaded && !force)) return
    list.loading = true
    list.error = false
    try {
      const response = await api.get<ApiResponse<ActionableList>>(`${PATHS[key]}${query(key)}`)
      list.data = response.data
      list.loaded = true
    } catch {
      list.error = true
    } finally {
      list.loading = false
    }
  }

  /** A changed filter invalidates only the list it belongs to. */
  function invalidate(key: ActionableKey): void {
    state[key] = blank()
  }

  return { state, minimum, months, load, invalidate }
}
