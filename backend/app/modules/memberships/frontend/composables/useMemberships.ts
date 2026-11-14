import type { ApiResponse } from '~~/app/types'

/**
 * Membership plans and a patient's membership: its fees, the services
 * included and the discounts. Types live here, with the module that owns
 * them (ADR 0044).
 */

export type PlanPeriod = 'monthly' | 'annual'
export type BenefitKind = 'included' | 'discount'
export type PaymentMethod = 'cash' | 'card' | 'bank_transfer' | 'direct_debit' | 'insurance' | 'other'
export const PAYMENT_METHODS: PaymentMethod[] = ['cash', 'card', 'bank_transfer', 'direct_debit', 'insurance', 'other']

export interface MembershipBenefit {
  catalog_item_id: string
  kind: BenefitKind
  quantity: number | null
  discount_percent: string | null
  /** Absent while the Treatments app is off: the benefit stands, unnamed. */
  internal_code?: string | null
  names?: Record<string, string> | null
}

export interface MembershipPlan {
  id: string
  name: string
  description: string | null
  fee: string
  period: PlanPeriod
  general_discount_percent: string | null
  status: 'active' | 'archived'
  benefits: MembershipBenefit[]
}

export interface MembershipPlanInput {
  name: string
  description: string | null
  fee: string
  period: PlanPeriod
  general_discount_percent: string | null
  benefits: { catalog_item_id: string, kind: BenefitKind, quantity: number | null, discount_percent: string | null }[]
}

export interface MembershipTreatment {
  id: string
  internal_code: string
  names: Record<string, string>
}

export interface MembershipPeriod {
  id: string
  starts_on: string
  ends_on: string
  amount: string
  refunded_amount: string
  status: 'paid' | 'refunded'
  plan_name: string
  payment_id: string | null
}

export interface IncludedUsage {
  catalog_item_id: string
  quantity: number
  used: number
  internal_code?: string | null
  names?: Record<string, string> | null
}

export interface PatientMembership {
  id: string
  patient_id: string
  plan_id: string
  plan_name: string
  state: 'active' | 'expired' | 'cancelled'
  status: 'active' | 'cancelled'
  started_on: string
  paid_through: string | null
  covered_until: string | null
  cycle_start: string
  general_discount_percent: string | null
  included: IncludedUsage[]
  discounts: MembershipBenefit[]
  periods: MembershipPeriod[]
  payments_available: boolean
}

export interface FeePaymentInput {
  method: PaymentMethod
  payment_date: string
  reference: string | null
}

const BASE = '/api/v1/memberships'

export function useMemberships() {
  const api = useApi()

  async function listPlans(includeArchived = false): Promise<MembershipPlan[]> {
    const query = includeArchived ? '?include_archived=true' : ''
    return (await api.get<ApiResponse<MembershipPlan[]>>(`${BASE}/plans${query}`)).data
  }

  async function savePlan(input: MembershipPlanInput, id?: string): Promise<MembershipPlan> {
    const response = id
      ? await api.put<ApiResponse<MembershipPlan>>(`${BASE}/plans/${id}`, input)
      : await api.post<ApiResponse<MembershipPlan>>(`${BASE}/plans`, input)
    return response.data
  }

  async function setPlanArchived(id: string, archived: boolean): Promise<MembershipPlan> {
    const action = archived ? 'archive' : 'restore'
    return (await api.post<ApiResponse<MembershipPlan>>(`${BASE}/plans/${id}/${action}`)).data
  }

  async function listTreatments(): Promise<MembershipTreatment[]> {
    return (await api.get<ApiResponse<MembershipTreatment[]>>(`${BASE}/treatments`)).data
  }

  async function forPatient(patientId: string): Promise<PatientMembership | null> {
    const response = await api.get<ApiResponse<{ membership: PatientMembership | null }>>(
      `${BASE}/patients/${patientId}`
    )
    return response.data.membership
  }

  async function enroll(
    patientId: string,
    input: { plan_id: string, starts_on: string, payment: FeePaymentInput }
  ): Promise<PatientMembership> {
    return (await api.post<ApiResponse<PatientMembership>>(`${BASE}/patients/${patientId}`, input)).data
  }

  async function renew(membershipId: string, payment: FeePaymentInput): Promise<PatientMembership> {
    return (await api.post<ApiResponse<PatientMembership>>(`${BASE}/${membershipId}/periods`, { payment })).data
  }

  async function changePlan(membershipId: string, planId: string): Promise<PatientMembership> {
    return (await api.put<ApiResponse<PatientMembership>>(`${BASE}/${membershipId}/plan`, { plan_id: planId })).data
  }

  async function cancel(membershipId: string): Promise<PatientMembership> {
    return (await api.post<ApiResponse<PatientMembership>>(`${BASE}/${membershipId}/cancel`)).data
  }

  return { listPlans, savePlan, setPlanArchived, listTreatments, forPatient, enroll, renew, changePlan, cancel }
}

/** `code · name` of a catalogue treatment, in the reader's language. */
export function treatmentLabel(
  locale: string,
  code: string | null | undefined,
  names: Record<string, string> | null | undefined,
  fallback: string
): string {
  const name = names ? (names[locale] || names.es || names.en) : undefined
  if (!code && !name) return fallback
  return [code, name].filter(Boolean).join(' · ')
}
