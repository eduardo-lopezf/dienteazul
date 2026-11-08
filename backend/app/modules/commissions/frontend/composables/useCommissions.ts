import type { ApiResponse } from '~~/app/types'

/**
 * What a professional is paid: a general percentage and, optionally, a
 * different one for specific treatments of the catalogue.
 */

export type CommissionBasis = 'collected' | 'earned'

export interface CommissionRate {
  catalog_item_id: string
  percent: string
  /** Absent while the Treatments app is off: the rate stands, unnamed. */
  internal_code?: string | null
  names?: Record<string, string> | null
}

export interface CommissionAgreement {
  professional_id: string
  configured: boolean
  basis: CommissionBasis
  default_percent: string | null
  rates: CommissionRate[]
  notes: string | null
}

export interface CommissionTreatment {
  id: string
  internal_code: string
  names: Record<string, string>
}

export interface CommissionAgreementInput {
  basis: CommissionBasis
  default_percent: string | null
  rates: { catalog_item_id: string, percent: string }[]
  notes: string | null
}

const BASE = '/api/v1/commissions'

export function useCommissions() {
  const api = useApi()

  async function fetchAgreement(professionalId: string): Promise<CommissionAgreement> {
    const response = await api.get<ApiResponse<CommissionAgreement>>(
      `${BASE}/professionals/${professionalId}`
    )
    return response.data
  }

  async function saveAgreement(
    professionalId: string,
    input: CommissionAgreementInput
  ): Promise<CommissionAgreement> {
    const response = await api.put<ApiResponse<CommissionAgreement>>(
      `${BASE}/professionals/${professionalId}`,
      input
    )
    return response.data
  }

  async function fetchTreatments(): Promise<CommissionTreatment[]> {
    const response = await api.get<ApiResponse<CommissionTreatment[]>>(`${BASE}/treatments`)
    return response.data
  }

  return { fetchAgreement, saveAgreement, fetchTreatments }
}
