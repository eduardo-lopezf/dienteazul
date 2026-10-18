/**
 * What is assigned to each professional of the clinic.
 *
 * The server asks every running App that assigns work (`ProfessionalWorkload`
 * contract): the agenda its appointments, treatment plans their plans and
 * treatments. A figure whose App is off is simply absent — never a zero
 * that would read as "nothing assigned".
 */
export interface ProfessionalWorkload {
  professional_id: string
  /** Distinct patients with an appointment or plan of theirs. */
  patients: number
  counts: Partial<Record<
    'appointments' | 'appointments_upcoming' | 'plans_in_progress'
    | 'treatments_pending' | 'treatments_completed',
    number
  >>
}

export function useProfessionalWorkload() {
  const api = useApi()
  const byId = ref<Record<string, ProfessionalWorkload>>({})

  async function load(): Promise<void> {
    try {
      const response = await api.get<{ data: ProfessionalWorkload[] }>('/api/v1/professionals/workload')
      byId.value = Object.fromEntries(response.data.map(w => [w.professional_id, w]))
    } catch {
      // The directory reads fine without its figures.
      byId.value = {}
    }
  }

  return { byId, load }
}
