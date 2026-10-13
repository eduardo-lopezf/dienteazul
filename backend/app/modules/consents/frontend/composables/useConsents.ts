import type { ApiResponse } from '~~/app/types'

/**
 * Consent letters and their templates.
 *
 * The types live here, with the module that owns them, and not in the
 * host's `types/index.ts` (ADR 0044).
 */
export type ConsentKind = 'informed' | 'data_use' | 'conformity'
export type ConsentStatus = 'draft' | 'signed' | 'declined' | 'revoked' | 'discarded'
export type SignerCapacity = 'patient' | 'guardian' | 'representative'
export type SignatureMethod = 'screen' | 'paper'

export interface ConsentTemplate {
  id: string
  kind: ConsentKind
  title: string
  body: string
  version: number
  is_active: boolean
  updated_at: string
}

export interface Consent {
  id: string
  patient_id: string
  kind: ConsentKind
  status: ConsentStatus
  title: string
  body: string
  template_id: string | null
  template_version: number | null
  procedure_label: string | null
  plan_id: string | null
  explained_by_professional_id: string | null
  explained_by_name: string | null
  explained_by_license: string | null
  signed_at: string | null
  signed_by_name: string | null
  signer_capacity: SignerCapacity | null
  signature_method: SignatureMethod | null
  /** `png` when drawn on screen; `document_id` — the scan — when signed on paper. */
  signature_data: { png?: string, document_id?: string } | null
  declined_at: string | null
  revoked_at: string | null
  status_note: string | null
  created_at: string
}

export interface ConsentDraft {
  kind: ConsentKind
  template_id?: string | null
  title?: string
  body?: string
  procedure_label?: string | null
  /** The treatment plan the letter is written for, when it is for one. */
  plan_id?: string | null
  explained_by_professional_id?: string | null
}

/** How the clinic uses consent letters. */
export interface ConsentSettings {
  /** A plan is not confirmed without a signed informed consent written for it. */
  require_informed_for_plan: boolean
}

const BASE = '/api/v1/consents'

export function useConsents() {
  const api = useApi()

  async function listTemplates(opts: { kind?: ConsentKind, includeInactive?: boolean } = {}): Promise<ConsentTemplate[]> {
    const params = new URLSearchParams()
    if (opts.kind) params.set('kind', opts.kind)
    if (opts.includeInactive) params.set('include_inactive', 'true')
    const query = params.toString()
    return (await api.get<ApiResponse<ConsentTemplate[]>>(`${BASE}/templates${query ? `?${query}` : ''}`)).data
  }

  async function createTemplate(data: Pick<ConsentTemplate, 'kind' | 'title' | 'body'>): Promise<ConsentTemplate> {
    return (await api.post<ApiResponse<ConsentTemplate>>(`${BASE}/templates`, data)).data
  }

  async function updateTemplate(id: string, data: Partial<Pick<ConsentTemplate, 'title' | 'body' | 'is_active'>>): Promise<ConsentTemplate> {
    return (await api.put<ApiResponse<ConsentTemplate>>(`${BASE}/templates/${id}`, data)).data
  }

  async function getSettings(): Promise<ConsentSettings> {
    return (await api.get<ApiResponse<ConsentSettings>>(`${BASE}/settings`)).data
  }

  async function saveSettings(settings: ConsentSettings): Promise<ConsentSettings> {
    return (await api.put<ApiResponse<ConsentSettings>>(`${BASE}/settings`, settings)).data
  }

  async function listForPatient(patientId: string): Promise<Consent[]> {
    return (await api.get<ApiResponse<Consent[]>>(`${BASE}/patients/${patientId}`)).data
  }

  async function create(patientId: string, data: ConsentDraft): Promise<Consent> {
    return (await api.post<ApiResponse<Consent>>(`${BASE}/patients/${patientId}`, data)).data
  }

  async function update(id: string, data: Partial<ConsentDraft>): Promise<Consent> {
    return (await api.put<ApiResponse<Consent>>(`${BASE}/${id}`, data)).data
  }

  async function sign(id: string, data: {
    signed_by_name: string
    signer_capacity: SignerCapacity
    method?: SignatureMethod
    signature_data?: { png: string }
    document_id?: string
  }): Promise<Consent> {
    return (await api.post<ApiResponse<Consent>>(`${BASE}/${id}/sign`, data)).data
  }

  /**
   * File the scan of a letter signed on paper among the patient's
   * documents (the Media module's API) and return its id.
   */
  async function uploadScan(patientId: string, file: File, title: string): Promise<string> {
    const form = new FormData()
    form.append('file', file)
    form.append('document_type', 'consent')
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

  /** Show a file in the reserved tab, or download it when there is none. */
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

  /** The letter as a sheet to print: a form to sign by hand while a draft. */
  function openPdf(id: string, locale: string, tab: Window | null): Promise<void> {
    return openFile(`${BASE}/${id}/pdf?locale=${locale === 'en' ? 'en' : 'es'}`, `consentimiento_${id.slice(0, 8)}.pdf`, tab)
  }

  /** The scan filed when the letter was signed on paper. */
  function openScan(documentId: string, tab: Window | null): Promise<void> {
    return openFile(`/api/v1/media/documents/${documentId}/download`, `consentimiento_${documentId.slice(0, 8)}`, tab)
  }

  async function act(id: string, action: 'decline' | 'revoke' | 'discard', note?: string): Promise<Consent> {
    return (await api.post<ApiResponse<Consent>>(`${BASE}/${id}/${action}`, action === 'discard' ? undefined : { note: note || null })).data
  }

  return {
    getSettings,
    saveSettings,
    listTemplates, createTemplate, updateTemplate, listForPatient, create, update, sign, act, uploadScan, reserveTab, openPdf, openScan }
}
