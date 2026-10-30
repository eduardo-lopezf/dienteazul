/**
 * The month's goals, beside what the clinic actually got.
 *
 * The grain is the month, so the card asks for **the month the panel's
 * period ends in**: look at September and you see September's goals,
 * look at the last twelve months and you see this month's. Any other
 * rule would have to explain itself every time the period changed.
 */
import type { ApiResponse } from '~~/app/types'

export interface Attainment {
  target: string | null
  actual: string
  /** Percentage of the goal reached, or null when no goal was set. */
  ratio: number | null
}

export interface MonthlyTargets {
  month: string
  collected: Attainment
  production: Attainment
  new_patients: Attainment
}

export interface TargetDraft {
  collected_target: number | null
  production_target: number | null
  new_patients_target: number | null
}

const PATH = '/api/v1/reports/targets'

export function useMonthlyTargets() {
  const api = useApi()

  const targets = ref<MonthlyTargets | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const failed = ref(false)

  async function load(month: string): Promise<void> {
    loading.value = true
    failed.value = false
    try {
      const response = await api.get<ApiResponse<MonthlyTargets>>(`${PATH}?month=${month}`)
      targets.value = response.data
    } catch {
      failed.value = true
    } finally {
      loading.value = false
    }
  }

  async function save(month: string, draft: TargetDraft): Promise<void> {
    saving.value = true
    try {
      const response = await api.put<ApiResponse<MonthlyTargets>>(`${PATH}?month=${month}`, draft)
      targets.value = response.data
    } finally {
      saving.value = false
    }
  }

  return { targets, loading, saving, failed, load, save }
}

/**
 * How much of the month has gone, as a percentage.
 *
 * A goal half reached on the 5th and the same goal half reached on the
 * 28th are opposite news, and a bar that only knows the goal cannot tell
 * them apart. For a month already over this is 100.
 */
export function monthElapsedPct(month: string, now = new Date()): number {
  const first = new Date(`${month}T00:00:00`)
  const days = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate()
  const sameMonth
    = now.getFullYear() === first.getFullYear() && now.getMonth() === first.getMonth()
  if (!sameMonth) return now > first ? 100 : 0
  return Math.round((now.getDate() / days) * 100)
}
