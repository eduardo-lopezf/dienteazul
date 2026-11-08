import type { ApiResponse } from '~~/app/types'

/**
 * Settling with an associate dentist.
 *
 * Two totals travel together everywhere in here — what was earned and what
 * has been collected — because paying a percentage of the first without
 * seeing the second is how a clinic hands out money it has not received.
 */

export type CommissionBasis = 'collected' | 'earned'

export interface ProfessionalBrief {
  id: string
  first_name: string
  last_name: string
}

export interface Commission {
  id: string
  professional_id: string
  basis: CommissionBasis
  percent: string
  notes: string | null
  professional: ProfessionalBrief | null
}

export interface LiquidationLine {
  treatment_id: string
  description: string | null
  performed_at: string
  earned: string
  collected: string
  catalog_item_id?: string | null
  /** Null when nothing was agreed for it, and on older settlements. */
  percent?: string | null
  share?: string | null
}

export interface LiquidationPreview {
  professional_id: string
  professional: ProfessionalBrief | null
  date_from: string
  date_to: string
  currency: string
  basis: CommissionBasis
  percent: string
  earned_total: string
  collected_total: string
  base_amount: string
  amount_due: string
  lines: LiquidationLine[]
  /** No arrangement recorded yet: the work is real, the share is not. */
  missing_commission: boolean
  /** Set when this exact period already carries an issued settlement. */
  issued_id: string | null
  /** `commissions`: per-treatment rates set on the professional's card. */
  rates_source: 'commissions' | 'liquidations'
}

export type PayoutMethod = 'cash' | 'transfer' | 'other'

export interface Liquidation extends Omit<LiquidationPreview, 'missing_commission' | 'issued_id' | 'rates_source'> {
  id: string
  notes: string | null
  issued_at: string
  issued_by: string
  issuer: { id: string, first_name: string, last_name: string } | null
  paid_at: string | null
  payment_method: PayoutMethod | null
  payer: { id: string, first_name: string, last_name: string } | null
  /** The till movement the payout wrote — only ever set for a cash payout. */
  cash_movement_id: string | null
}

const BASE = '/api/v1/liquidations'

export function useLiquidations() {
  const api = useApi()

  const commissions = ref<Commission[]>([])
  const preview = ref<LiquidationPreview | null>(null)
  const issued = ref<Liquidation[]>([])
  const loading = ref(false)

  async function fetchCommissions(): Promise<void> {
    try {
      const response = await api.get<ApiResponse<Commission[]>>(`${BASE}/commissions`)
      commissions.value = response.data
    } catch {
      commissions.value = []
    }
  }

  async function saveCommission(
    professionalId: string,
    basis: CommissionBasis,
    percent: string
  ): Promise<void> {
    await api.put(`${BASE}/commissions/${professionalId}`, { basis, percent })
  }

  async function fetchPreview(
    professionalId: string,
    dateFrom: string,
    dateTo: string
  ): Promise<void> {
    loading.value = true
    try {
      const response = await api.get<ApiResponse<LiquidationPreview>>(
        `${BASE}/preview?professional_id=${professionalId}&date_from=${dateFrom}&date_to=${dateTo}`
      )
      preview.value = response.data
    } catch {
      preview.value = null
    } finally {
      loading.value = false
    }
  }

  async function fetchIssued(dateFrom: string, dateTo: string): Promise<void> {
    try {
      const response = await api.get<ApiResponse<Liquidation[]>>(
        `${BASE}?date_from=${dateFrom}&date_to=${dateTo}`
      )
      issued.value = response.data
    } catch {
      issued.value = []
    }
  }

  async function issue(
    professionalId: string,
    dateFrom: string,
    dateTo: string,
    notes?: string | null
  ): Promise<void> {
    await api.post(BASE, {
      professional_id: professionalId,
      date_from: dateFrom,
      date_to: dateTo,
      notes: notes || null
    })
  }

  async function pay(
    id: string,
    method: PayoutMethod,
    businessDate?: string | null
  ): Promise<void> {
    await api.post(`${BASE}/${id}/pay`, {
      method,
      business_date: businessDate || null
    })
  }

  async function unpay(id: string): Promise<void> {
    await api.post(`${BASE}/${id}/unpay`, {})
  }

  return {
    commissions,
    preview,
    issued,
    loading,
    fetchCommissions,
    saveCommission,
    fetchPreview,
    fetchIssued,
    issue,
    pay,
    unpay
  }
}
