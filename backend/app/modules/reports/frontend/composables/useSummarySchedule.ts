/**
 * The clinic's standing order for its one-page summary.
 *
 * Read and written through `reports.summary.write` — the answer carries
 * the staff addresses that receive it, so looking is as privileged as
 * changing.
 */
import type { ApiResponse } from '~~/app/types'

export type Cadence = 'weekly' | 'monthly'

export interface SummarySchedule {
  is_active: boolean
  cadence: Cadence
  recipients: string[]
  /** The period end of the last send that reached somebody. */
  last_sent_for: string | null
}

const PATH = '/api/v1/reports/summary/schedule'

export function useSummarySchedule() {
  const api = useApi()

  const schedule = ref<SummarySchedule | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  async function load(): Promise<void> {
    loading.value = true
    try {
      const response = await api.get<ApiResponse<SummarySchedule>>(PATH)
      schedule.value = response.data
    } finally {
      loading.value = false
    }
  }

  /**
   * Save, and take the server's answer as the truth: it normalises the
   * cadence and drops blank rows, so echoing the local draft back would
   * show the user something the clinic does not actually have.
   */
  async function save(draft: Omit<SummarySchedule, 'last_sent_for'>): Promise<SummarySchedule> {
    saving.value = true
    try {
      const response = await api.put<ApiResponse<SummarySchedule>>(PATH, draft)
      schedule.value = response.data
      return response.data
    } finally {
      saving.value = false
    }
  }

  return { schedule, loading, saving, load, save }
}
