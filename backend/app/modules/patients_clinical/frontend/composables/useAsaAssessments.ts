import type { ApiResponse } from '~~/app/types'

/**
 * The ASA physical status of a patient: a clinician's judgement on a given
 * day, appended and never edited. Types live here, with the module that
 * owns them (ADR 0044).
 */
export interface AsaAssessment {
  id: string
  patient_id: string
  assessed_at: string
  /** 1–4. */
  asa_class: number
  is_emergency: boolean
  /** `III`, `IIE`: the class as it is written. */
  label: string
  rationale: string | null
  retracted_at: string | null
  assessed_by_name: string | null
}

export interface AsaStatus {
  /** The newest assessment not retracted; null when nobody assessed the patient. */
  current: AsaAssessment | null
  history: AsaAssessment[]
}

/** The current class alone — what whoever books the patient may see. */
export interface AsaClass {
  asa_class: number | null
  label: string | null
  is_emergency: boolean
}

export interface AsaAssessmentDraft {
  asa_class: number
  is_emergency: boolean
  rationale: string | null
}

/** I–IV: the classes a dental practice treats. V and VI are not offered. */
export const ASA_CLASSES = [1, 2, 3, 4] as const
export const ASA_NUMERALS: Record<number, string> = { 1: 'I', 2: 'II', 3: 'III', 4: 'IV' }

export function useAsaAssessments() {
  const api = useApi()
  const base = (patientId: string) => `/api/v1/patients_clinical/patients/${patientId}/asa`

  async function status(patientId: string): Promise<AsaStatus> {
    return (await api.get<ApiResponse<AsaStatus>>(base(patientId))).data
  }

  async function currentClass(patientId: string): Promise<AsaClass> {
    return (await api.get<ApiResponse<AsaClass>>(`${base(patientId)}/class`)).data
  }

  async function assess(patientId: string, draft: AsaAssessmentDraft): Promise<AsaAssessment> {
    return (await api.post<ApiResponse<AsaAssessment>>(base(patientId), draft)).data
  }

  async function retract(patientId: string, id: string, reason: string): Promise<void> {
    await api.post(`${base(patientId)}/${id}/retract`, { reason: reason || null })
  }

  return { status, currentClass, assess, retract }
}
