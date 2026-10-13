import type { ApiResponse } from '~~/app/types'

/**
 * The health questionnaire a patient answers at a visit. Types live here,
 * with the module that owns them (ADR 0044).
 */
export interface QuestionAnswer {
  answer: boolean
  detail?: string | null
}

export interface HealthQuestionnaire {
  id: string
  patient_id: string
  taken_at: string
  chief_complaint: string | null
  blood_type: string | null
  declared_allergies: string | null
  answers: Record<string, QuestionAnswer>
  conditions: string[]
  drugs_detail: string | null
  other_conditions: string | null
  scan_document_id: string | null
  /** Set when the patient signed on screen. */
  signed_at: string | null
  signed_by_name: string | null
  signer_capacity: SignerCapacity | null
  signature_data: { png?: string } | null
  /** The regulation the form named when it was recorded. */
  regulation: string | null
}

export type SignerCapacity = 'patient' | 'guardian' | 'representative'
export const SIGNER_CAPACITIES: SignerCapacity[] = ['patient', 'guardian', 'representative']

/** The patient's signature, drawn on screen. */
export interface QuestionnaireSignature {
  png: string
  signed_by_name: string
  signer_capacity: SignerCapacity
}

type Declared = Omit<
  HealthQuestionnaire,
  'id' | 'patient_id' | 'taken_at' | 'signed_at' | 'signed_by_name' | 'signer_capacity' | 'signature_data' | 'regulation'
>
export type HealthQuestionnaireDraft = Partial<Declared> & { signature?: QuestionnaireSignature | null }

/** The questions, in the order they are asked. Mirrors `questionnaire.py`. */
export const QUESTIONS = [
  'medical_care_2y', 'hospitalized_5y', 'taking_medication', 'drug_food_allergy',
  'prior_surgery', 'anesthesia_reaction', 'major_bleeding',
  'problem_after_dental_treatment', 'weight_change_10kg', 'pregnant',
  'breastfeeding', 'contraceptive'
] as const

/** The conditions, in the blocks the paper form prints them in. */
export const CONDITION_GROUPS: string[][] = [
  [
    'hypotension', 'hypertension', 'heart_failure', 'angina', 'myocardial_infarction',
    'rheumatic_fever', 'tachycardia', 'bradycardia', 'pacemaker', 'arteriosclerosis',
    'atherosclerosis', 'headache', 'tinnitus', 'phosphenes', 'dizziness', 'fainting',
    'obesity', 'overweight', 'exertional_chest_pain', 'resting_chest_pain', 'heart_murmur',
    'evening_leg_edema', 'cyanosis', 'bruising', 'anemia', 'epistaxis', 'thrombosis',
    'transfusion', 'blood_donor', 'organ_donor', 'stroke', 'epigastric_pain'
  ],
  [
    'gastric_ulcer', 'reflux', 'gastritis', 'colitis', 'diabetes', 'sinusitis',
    'bronchitis', 'glaucoma', 'emphysema', 'tuberculosis', 'pharyngotonsillitis',
    'digestive_problems', 'hepatitis', 'gallbladder', 'cirrhosis', 'epilepsy',
    'hyperthyroidism', 'seizures', 'alcoholism', 'smoking', 'drugs', 'hypothyroidism',
    'goiter', 'asthma', 'gout'
  ],
  [
    'kidney_infection', 'kidney_stone', 'dialysis', 'prostate_problems', 'cancer',
    'chemotherapy', 'radiotherapy', 'bisphosphonates', 'std', 'hiv_aids'
  ]
]

export function useHealthQuestionnaires() {
  const api = useApi()
  const base = (patientId: string) => `/api/v1/patients_clinical/patients/${patientId}`

  async function list(patientId: string): Promise<HealthQuestionnaire[]> {
    return (await api.get<ApiResponse<HealthQuestionnaire[]>>(`${base(patientId)}/questionnaires`)).data
  }

  async function create(patientId: string, data: HealthQuestionnaireDraft): Promise<HealthQuestionnaire> {
    return (await api.post<ApiResponse<HealthQuestionnaire>>(`${base(patientId)}/questionnaires`, data)).data
  }

  async function retract(patientId: string, id: string, reason: string): Promise<void> {
    await api.post(`${base(patientId)}/questionnaires/${id}/retract`, { reason: reason || null })
  }

  /** File the scan of a sheet filled in by hand among the patient's documents. */
  async function uploadScan(patientId: string, file: File, title: string): Promise<string> {
    const form = new FormData()
    form.append('file', file)
    form.append('document_type', 'report')
    form.append('title', title.slice(0, 255))
    const response = await api.post<ApiResponse<{ id: string }>>(
      `/api/v1/media/patients/${patientId}/documents`, form
    )
    return response.data.id
  }

  /**
   * A tab opened *before* any await, so the popup blocker counts it as
   * part of the tap. Safari (iPad) drops a `window.open` made after a
   * network round-trip.
   */
  function reserveTab(): Window | null {
    return window.open('', '_blank')
  }

  async function openFile(path: string, filename: string, tab: Window | null): Promise<void> {
    let blob: Blob
    try {
      blob = await api.$api<Blob>(path, { responseType: 'blob' })
    } catch {
      tab?.close()
      throw new Error(`Failed to load ${path}`)
    }
    const url = URL.createObjectURL(blob)
    if (tab && !tab.closed) {
      tab.location.href = url
    } else {
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
    }
    // The tab needs the URL until it has read it.
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }

  /** The blank sheet, to fill in by hand. */
  function openBlankForm(patientId: string, locale: string, tab: Window | null): Promise<void> {
    return openFile(`${base(patientId)}/questionnaire-form?locale=${locale === 'en' ? 'en' : 'es'}`, 'cuestionario_de_salud.pdf', tab)
  }

  function openScan(documentId: string, tab: Window | null): Promise<void> {
    return openFile(`/api/v1/media/documents/${documentId}/download`, `cuestionario_${documentId.slice(0, 8)}`, tab)
  }

  return { list, create, retract, uploadScan, reserveTab, openBlankForm, openScan }
}
