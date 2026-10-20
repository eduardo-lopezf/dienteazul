// User types
export interface User {
  id: string
  email: string
  first_name: string
  last_name: string
  professional_id?: string
  is_active: boolean
  /** Still on a password somebody else set: the app holds the account on
   * the change-password screen until it has its own. */
  must_change_password?: boolean
  created_at: string
  updated_at: string
}

export interface ClinicMembership {
  id: string
  user_id: string
  clinic_id: string
  role: 'admin' | 'dentist' | 'hygienist' | 'assistant' | 'receptionist'
}

export interface Cabinet {
  id: string
  clinic_id: string
  name: string
  color: string
  display_order?: number
  is_active?: boolean
}

export interface CabinetCreate {
  name: string
  color: string
  display_order?: number
  is_active?: boolean
}

export interface CabinetUpdate {
  name?: string
  color?: string
  display_order?: number
  is_active?: boolean
}

export interface ClinicAddress {
  street?: string
  city?: string
  postal_code?: string
  country?: string
}

export interface ClinicUpdate {
  name?: string
  tax_id?: string
  legal_name?: string
  address?: ClinicAddress
  phone?: string
  email?: string
  timezone?: string
  currency?: string
}

export interface Clinic {
  id: string
  name: string
  tax_id: string
  legal_name?: string | null
  address?: Record<string, string>
  phone?: string
  email?: string
  timezone: string
  currency: string
  account_tier: string
  settings: {
    slot_duration_min?: number
  }
  cabinets: Cabinet[]
  created_at: string
  updated_at: string
}

// First-run wizard. `available_account_tiers` is what this deployment's
// custody mode may create — `basic` and `medium` are sold managed only —
// so the wizard offers a choice the backend will accept.
export interface SetupStatus {
  initialized: boolean
  custody_mode: string
  available_account_tiers: string[]
}

// Auth types
export interface LoginCredentials {
  email: string
  password: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface AuthResponse extends AuthTokens {
  user: User
  clinics: Array<{ id: string, name: string, role: string }>
}

export interface MeResponse {
  user: User
  clinics: Array<{ id: string, name: string, role: string, timezone: string, onboarding_pending?: boolean, privacy_renewal?: boolean, deactivated?: boolean }>
  permissions: string[]
}

export type UserRole = 'admin' | 'dentist' | 'hygienist' | 'assistant' | 'receptionist'

// Clinic directory profile. Only dentists and hygienists are schedulable.
export interface Professional {
  id: string
  first_name: string
  last_name: string
  full_name: string
  professional_type: 'dentist' | 'hygienist' | 'collaborator'
  /** Disciplines from the clinic's specialty catalog; a professional may practise several. */
  specialties: SpecialtyBrief[]
  license_number: string | null
  email: string | null
  phone: string | null
  photo_url: string | null
  notes: string | null
  is_active: boolean
  /** The account this person signs in with, stated by an admin. Null when the
   *  directory profile has none — a collaborator without product access. It is
   *  what makes a clinical entry attributable to a professional. */
  user_id: string | null
  /** Hint only: the email matches an account with access here. Never the
   *  source of attribution — a shared address would name the wrong person. */
  has_system_access: boolean
}

export interface UserCreate {
  email: string
  password: string
  first_name: string
  last_name: string
  role: UserRole
  clinic_id?: string
}

export interface UserUpdate {
  first_name?: string
  last_name?: string
  email?: string
  role?: UserRole
  is_active?: boolean
}

// Patient types
export interface PatientBillingAddress {
  street?: string
  city?: string
  postal_code?: string
  province?: string
  country?: string
}

export interface Patient {
  id: string
  clinic_id: string
  first_name: string
  last_name: string
  phone?: string
  email?: string
  date_of_birth?: string
  notes?: string
  status: 'active' | 'archived'
  do_not_contact: boolean
  // Billing fields
  billing_name?: string
  billing_tax_id?: string
  billing_address?: PatientBillingAddress
  billing_email?: string
  has_complete_billing_info: boolean
  created_at: string
  updated_at: string
}

/**
 * A monetary value as it crosses the wire.
 *
 * The API serialises `Decimal` as a JSON **string** (`"410.00"`) — as it
 * should, since binary floats cannot hold money exactly and this is a
 * fiscal product. Declaring these fields `number` was a lie the consumers
 * survived only by calling `Number()` at each use, and it made
 * `a.total + b.total` compile into `"410.00410.00"`.
 *
 * The union keeps display code (`${amount}`) and locally computed numbers
 * working while making arithmetic on two of them a type error: convert
 * explicitly with `Number()` first.
 */
export type Money = string | number

export interface PatientCreate {
  first_name: string
  last_name: string
  phone?: string
  email?: string
  date_of_birth?: string
  notes?: string
  do_not_contact?: boolean
  // Billing fields
  billing_name?: string
  billing_tax_id?: string
  billing_address?: PatientBillingAddress
  billing_email?: string
}

/**
 * Update payload. `null` is meaningful here in a way it is not on create:
 * the backend's `str | None` fields read it as "clear this value", while
 * omitting the key leaves the value untouched. Deriving this from
 * `Partial<PatientCreate>` lost that distinction, so every clear-a-field
 * call in the UI was a type error the build never reported.
 */
export interface PatientUpdate {
  first_name?: string
  last_name?: string
  phone?: string | null
  email?: string | null
  date_of_birth?: string | null
  notes?: string | null
  status?: 'active' | 'archived'
  do_not_contact?: boolean
  billing_name?: string | null
  billing_tax_id?: string | null
  billing_address?: PatientBillingAddress | null
  billing_email?: string | null
}

// Appointment treatment brief (from planned treatment item)
export interface AppointmentTreatmentBrief {
  id: string
  planned_item_id: string
  planned_item_status: 'pending' | 'completed' | 'cancelled'
  catalog_item_id?: string
  internal_code: string
  names: Record<string, string>
  default_price?: Money
  default_duration_minutes?: number
  // Dental context
  tooth_number?: number
  surfaces?: string[]
  is_global: boolean
  // Plan info
  plan_id?: string
  plan_number?: string
  // Completion tracking
  completed_in_appointment: boolean
}

// Appointment types
export type AppointmentStatus
  = | 'scheduled'
    | 'confirmed'
    | 'checked_in'
    | 'in_treatment'
    | 'completed'
    | 'cancelled'
    | 'no_show'

export interface AppointmentStatusEvent {
  id: string
  from_status: AppointmentStatus | null
  to_status: AppointmentStatus
  changed_at: string
  changed_by: string | null
  changed_by_name: string | null
  note: string | null
}

export interface AppointmentCabinetEvent {
  id: string
  from_cabinet_id: string | null
  from_cabinet_name: string | null
  to_cabinet_id: string | null
  to_cabinet_name: string | null
  changed_at: string
  changed_by: string | null
  changed_by_name: string | null
  note: string | null
}

export interface Appointment {
  id: string
  clinic_id: string
  patient_id?: string
  // Null when nobody is assigned: the Professionals App is optional
  // (ADR 0037), and so is the link while it is switched off.
  professional_id: string | null
  // What the appointment is called when there is no patient to name it by.
  title?: string | null
  // Cabinet is optional now (#51): a booked appointment may exist without
  // a cabinet decision until the patient arrives.
  cabinet: string | null
  cabinet_id: string | null
  cabinet_assigned_at: string | null
  cabinet_assigned_by: string | null
  start_time: string
  end_time: string
  treatment_type?: string // Legacy field
  treatments?: AppointmentTreatmentBrief[] // New: treatments from catalog
  status: AppointmentStatus
  current_status_since: string
  color?: string
  created_at: string
  updated_at: string
  patient?: Patient
  professional?: User
  // Populated only on GET /appointments/{id} and after POST transitions.
  history?: AppointmentStatusEvent[] | null
  cabinet_history?: AppointmentCabinetEvent[] | null
}

export interface AppointmentCreate {
  patient_id?: string
  professional_id?: string
  title?: string
  cabinet?: string | null
  cabinet_id?: string | null
  start_time: string
  end_time: string
  treatment_type?: string // Legacy field
  planned_item_ids?: string[] // List of PlannedTreatmentItem IDs
  color?: string
}

export interface AppointmentUpdate extends Partial<AppointmentCreate> {
  status?: Appointment['status']
}

// API and module-registry types live in their own files for clarity.
// The barrel re-export below preserves the existing import surface.
export * from './api'
export * from './module'

// User list response (for admin)
export interface UserWithRole extends User {
  role?: UserRole
}

// Odontogram types (matches backend ToothCondition enum).
export type ToothCondition
  = | 'healthy'
    | 'caries'
    | 'filling'
    | 'crown'
    | 'missing'
    | 'root_canal'
    | 'implant'
    | 'extraction_indicated'
    | 'sealant'
    | 'fracture'

export type Surface = 'M' | 'D' | 'O' | 'V' | 'L'
export type ToothType = 'permanent' | 'deciduous'

export interface SurfaceConditions {
  M: ToothCondition
  D: ToothCondition
  O: ToothCondition
  V: ToothCondition
  L: ToothCondition
}

export interface ToothRecord {
  id: string
  patient_id: string
  tooth_number: number
  tooth_type: ToothType
  general_condition: ToothCondition
  surfaces: SurfaceConditions
  notes?: string
  // Positional markers
  is_displaced?: boolean
  is_rotated?: boolean
  displacement_notes?: string
  created_at: string
  updated_at: string
}

export interface OdontogramData {
  patient_id: string
  teeth: ToothRecord[]
  treatments?: Treatment[]
  condition_colors: Record<ToothCondition, string>
  available_conditions: ToothCondition[]
  surfaces: Surface[]
}

export interface SurfaceUpdate {
  surface: Surface
  condition: ToothCondition
}

export interface ToothRecordUpdate {
  general_condition?: ToothCondition
  surface_updates?: SurfaceUpdate[]
  notes?: string
  is_displaced?: boolean
  is_rotated?: boolean
}

export interface BulkToothUpdate {
  tooth_number: number
  general_condition?: ToothCondition
  surface_updates?: SurfaceUpdate[]
  notes?: string
}

export interface OdontogramHistoryEntry {
  id: string
  tooth_number: number
  change_type: string
  surface?: Surface
  old_condition?: ToothCondition
  new_condition?: ToothCondition
  notes?: string
  changed_by: string
  changed_by_name?: string
  changed_at: string
}

// Treatment taxonomy (header + children model, aligned with backend).
// Backend stores 'planned' | 'performed'; the frontend preserves the clinical
// vocabulary 'existing' | 'planned'. useTreatments maps between the two at the
// API boundary.
export type TreatmentStatus = 'existing' | 'planned'
export type TreatmentCategory = 'surface' | 'whole_tooth'
// Mirrors the catalog's category keys — a mapping's `clinical_category`
// picks the tab of the odontogram bar, and the tab is labelled from the
// catalog category of the same key.
export type TreatmentClinicalCategory
  = 'diagnostico' | 'restauradora' | 'cirugia' | 'endodoncia' | 'ortodoncia'
    | 'preventivo' | 'periodoncia' | 'protesis' | 'estetica' | 'pediatrica'
export type VisualizationLayer = 'pulp_fill' | 'occlusal_surface' | 'lateral_icon' | 'cenital_pattern'

/** Clinical type (visualization key). Not a billable concept — pricing is in the catalog. */
export type ClinicalType
  // Diagnóstico
  = | 'pulpitis'
    | 'caries'
    | 'incipient_caries'
    | 'pigmentation'
    | 'fracture'
    | 'missing'
    | 'periapical_small'
    | 'periapical_medium'
    | 'periapical_large'
    | 'rotated'
    | 'displaced'
    | 'unerupted'
    // Restauradora
    | 'filling_composite'
    | 'filling_amalgam'
    | 'filling_temporary'
    | 'sealant'
    | 'veneer'
    | 'inlay'
    | 'overlay'
    | 'crown'
    | 'crown_on_implant'
    | 'provisional_crown_on_implant'
    | 'bridge'
    | 'splint'
    // Cirugía
    | 'extraction'
    | 'implant'
    | 'apicoectomy'
    | 'biopsy_soft_tissue'
    | 'biopsy_hard_tissue'
    // Endodoncia
    | 'root_canal_full'
    | 'root_canal_two_thirds'
    | 'root_canal_half'
    | 'post'
    | 'root_canal_overfill'
    // Ortodoncia
    | 'bracket'
    | 'tube'
    | 'band'
    | 'attachment'
    | 'retainer'
    // Esquelético — actúa sobre el esqueleto facial, no sobre un diente.
    // Llegan a la UI como ítems de catálogo global_mouth / global_arch, así
    // que no aparecen en TREATMENT_CATEGORIES ni pintan nada en el diagrama.
    | 'osteotomy_lefort1'
    | 'osteotomy_sagittal_ramus'
    | 'genioplasty'
    | 'osteosynthesis'
    | 'osteosynthesis_removal'
    // Proceso — la visita en sí, no trabajo sobre una estructura. Igual que
    // los esqueléticos: llegan como ítems global_mouth y no pintan nada.
    | 'consultation'
    | 'checkup'
    | 'imaging'
    | 'hygiene'
    // A billable act the chart does not draw: a denture, a graft, an
    // occlusal adjustment. Assigned automatically to a catalog item that
    // has no odontogram mapping.
    | 'procedure'

/** @deprecated — kept for gradual migration; prefer ClinicalType. */
export type TreatmentType = ClinicalType

/** Nested per-tooth member of a Treatment. */
export interface TreatmentTooth {
  id: string
  tooth_record_id: string
  tooth_number: number
  role: 'pillar' | 'pontic' | null
  surfaces: Surface[] | null
}

/** Catalog item embedded in Treatment responses. */
export interface TreatmentCatalogItemBrief {
  id: string
  internal_code: string
  names: Record<string, string>
  default_price?: string | null
}

/** Treatment = one clinical act. Bridges, splints and multiple-veneers/crowns are
 *  a single Treatment with several TreatmentTooth entries. Globals have empty teeth. */
export interface Treatment {
  id: string
  clinical_type: ClinicalType
  scope: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  arch?: 'upper' | 'lower' | null
  status: TreatmentStatus
  catalog_item_id?: string | null
  catalog_item?: TreatmentCatalogItemBrief | null
  teeth: TreatmentTooth[]
  recorded_at: string
  performed_at?: string | null
  performed_by?: string | null
  performed_by_name?: string | null
  price_snapshot?: string | null
  duration_snapshot?: number | null
  vat_rate_snapshot?: string | null
  budget_item_id?: string | null
  notes?: string | null
  source_module: string
  created_at: string
  updated_at: string
}

/** Scope of a Treatment (how it relates to teeth). Derived when omitted for
 *  tooth/multi_tooth; globals must be passed explicitly. */
export type TreatmentScope = 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'

export type Arch = 'upper' | 'lower'

export interface TreatmentToothInput {
  tooth_number: number
  role?: 'pillar' | 'pontic' | null
  surfaces?: Surface[]
}

/** Payload for POST /patients/{id}/treatments. */
export interface TreatmentCreate {
  catalog_item_id?: string
  clinical_type?: ClinicalType
  scope?: TreatmentScope
  arch?: Arch
  tooth_numbers?: number[]
  teeth?: TreatmentToothInput[]
  surfaces?: Surface[]
  status?: TreatmentStatus
  notes?: string
  budget_item_id?: string
  source_module?: string
}

/** PUT /treatments/{id} — header-level edits only. */
export interface TreatmentUpdate {
  status?: TreatmentStatus
  notes?: string
}

/** UI config for the multi-tooth picker (bridges, splints, multiple veneers/crowns). */
export type TreatmentGroupMode = 'bridge' | 'uniform'

export interface MultiToothTreatmentConfig {
  key: string
  labelKey: string
  mode: TreatmentGroupMode
  selectionMode: 'range' | 'free'
  minTeeth: number
  maxTeeth: number
  requiresSameArch: boolean
  /** Clinical category this multi-tooth treatment belongs to in the TreatmentBar. */
  category: 'restauradora' | 'cirugia' | 'endodoncia' | 'ortodoncia'
}

/** Per-tooth flattened view over a Treatment. Backwards-compatible with the old
 *  ToothTreatment-oriented components (treatment_type + surfaces at top level). */
export interface ToothTreatmentView {
  id: string
  treatment_id: string
  tooth_number: number
  treatment_type: ClinicalType
  clinical_type: ClinicalType
  surfaces: Surface[] | null
  role: 'pillar' | 'pontic' | null
  status: TreatmentStatus
  recorded_at: string
  performed_at?: string | null
  performed_by?: string | null
  performed_by_name?: string | null
  notes?: string | null
  price_snapshot?: string | null
  catalog_item_id?: string | null
  catalog_item?: TreatmentCatalogItemBrief | null
  source_module: string
  created_at: string
  updated_at: string
  is_multi: boolean
  teeth_count: number
}

export interface ToothRecordWithTreatments extends ToothRecord {
  treatments: Treatment[]
  is_displaced: boolean
  is_rotated: boolean
  displacement_notes?: string
}

// ============================================================================
// VAT Type Types
// ============================================================================

export interface VatType {
  id: string
  clinic_id: string
  names: Record<string, string>
  rate: Money
  is_default: boolean
  is_active: boolean
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface VatTypeCreate {
  names: Record<string, string>
  rate: Money
  is_default?: boolean
}

export interface VatTypeUpdate {
  names?: Record<string, string>
  rate?: Money
  is_default?: boolean
  is_active?: boolean
}

export interface VatTypeBrief {
  id: string
  names: Record<string, string>
  rate: Money
  is_default: boolean
  is_active: boolean
  is_system: boolean
}

// ============================================================================
// Specialty Types
// ============================================================================

export interface Specialty {
  id: string
  clinic_id: string
  /** Stable key of a seeded specialty (`cirugia`, `endodoncia`…); null when the
   *  clinic created it. Match on this, never on the display name. */
  key?: string | null
  names: Record<string, string>
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SpecialtyCreate {
  names: Record<string, string>
  /** Stable key, only when picked from `GET /specialties/suggestions`. */
  key?: string
}

/** A recognised discipline the clinic has not added yet. */
export interface SpecialtySuggestion {
  key: string
  names: Record<string, string>
}

export interface SpecialtyUpdate {
  names?: Record<string, string>
  is_active?: boolean
}

/** Specialty as embedded in a catalog item response. */
/** Stage of care; mirrors TREATMENT_PHASES in the backend catalog models. */
export type TreatmentPhase
  = | 'diagnostico'
    | 'urgencia'
    | 'preventivo'
    | 'estabilizacion'
    | 'rehabilitacion'
    | 'estetica'
    | 'mantenimiento'

export interface SpecialtyBrief {
  id: string
  names: Record<string, string>
  is_active: boolean
}

// ============================================================================
// Catalog Types
// ============================================================================

export interface TreatmentCatalogCategory {
  id: string
  clinic_id: string
  parent_id?: string
  key: string
  names: Record<string, string>
  descriptions?: Record<string, string>
  display_order: number
  icon?: string
  is_active: boolean
  is_system: boolean
  created_at: string
  updated_at: string
}

export interface TreatmentCatalogCategoryCreate {
  key: string
  names: Record<string, string>
  descriptions?: Record<string, string>
  parent_id?: string
  display_order?: number
  icon?: string
}

export interface TreatmentCatalogCategoryUpdate {
  key?: string
  names?: Record<string, string>
  descriptions?: Record<string, string>
  parent_id?: string
  display_order?: number
  icon?: string
  is_active?: boolean
}

export interface OdontogramMapping {
  id: string
  odontogram_treatment_type: string
  /** Layer objects, not rule names — the API rejects strings with a 422. */
  visualization_rules: VisualizationRuleLayer[]
  visualization_config: Record<string, unknown>
  clinical_category: string
}

export interface OdontogramMappingCreate {
  odontogram_treatment_type: string
  visualization_rules: VisualizationRuleLayer[]
  visualization_config: Record<string, unknown>
  clinical_category: string
}

/** Strategy used by the backend to compute Treatment.price_snapshot from a catalog item. */
export type PricingStrategy = 'flat' | 'per_tooth' | 'per_surface' | 'per_role'

export interface CatalogItemSession {
  id: string
  sequence: number
  labels: Record<string, string>
  default_price: Money
}

export interface CatalogItemSessionInput {
  sequence?: number
  labels: Record<string, string>
  default_price: Money
}

export interface TreatmentCatalogItem {
  id: string
  clinic_id: string
  category_id: string
  internal_code: string
  names: Record<string, string>
  descriptions?: Record<string, string>
  // Pricing
  default_price?: Money
  cost_price?: Money
  pricing_strategy?: PricingStrategy
  pricing_config?: Record<string, number> | null
  surface_prices?: Record<string, number> | null
  // Scheduling
  default_duration_minutes?: number
  requires_appointment: boolean
  // Tax - references VatType
  vat_type_id?: string
  vat_type?: VatTypeBrief
  /** Stage of care this treatment usually belongs to. */
  default_phase?: TreatmentPhase | null
  // Treatment characteristics
  treatment_scope: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  is_diagnostic: boolean
  requires_surfaces: boolean
  // Material
  material_notes?: string
  // Status
  is_active: boolean
  /** Listed on the clinical /treatments page. Independent of is_active. */
  is_visible?: boolean
  is_system: boolean
  deleted_at?: string
  // Timestamps
  created_at: string
  updated_at: string
  // Related
  category?: TreatmentCatalogCategory
  odontogram_mapping?: OdontogramMapping
  sessions?: CatalogItemSession[]
  specialties?: SpecialtyBrief[]
  /** Search hits only: the one discipline the treatment is shown under. */
  specialty?: SpecialtyBrief | null
}

export interface TreatmentCatalogItemCreate {
  internal_code: string
  category_id: string
  names: Record<string, string>
  descriptions?: Record<string, string>
  // Pricing
  default_price?: Money
  cost_price?: Money
  pricing_strategy?: PricingStrategy
  pricing_config?: Record<string, number> | null
  surface_prices?: Record<string, number> | null
  // Scheduling
  default_duration_minutes?: number
  requires_appointment?: boolean
  // Tax - references VatType (uses clinic default if not provided)
  vat_type_id?: string
  // Treatment characteristics
  treatment_scope?: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  is_diagnostic?: boolean
  requires_surfaces?: boolean
  // Material
  material_notes?: string
  // Odontogram mapping
  odontogram_mapping?: OdontogramMappingCreate
  // Session template (multi-session billing)
  sessions?: CatalogItemSessionInput[]
  /** Listed on the clinical /treatments page. Defaults to true. */
  is_visible?: boolean
  /** Stage of care this treatment usually belongs to. */
  default_phase?: TreatmentPhase | null
  /** Disciplines that perform it. Replaces the assignment when present. */
  specialty_ids?: string[]
}

export interface TreatmentCatalogItemUpdate {
  internal_code?: string
  category_id?: string
  names?: Record<string, string>
  descriptions?: Record<string, string>
  default_price?: Money
  cost_price?: Money
  pricing_strategy?: PricingStrategy
  pricing_config?: Record<string, number> | null
  surface_prices?: Record<string, number> | null
  default_duration_minutes?: number
  requires_appointment?: boolean
  vat_type_id?: string
  treatment_scope?: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  is_diagnostic?: boolean
  requires_surfaces?: boolean
  material_notes?: string
  is_active?: boolean
  /** Listed on the clinical /treatments page. Independent of is_active. */
  is_visible?: boolean
  odontogram_mapping?: OdontogramMappingCreate
  sessions?: CatalogItemSessionInput[]
  /** Stage of care this treatment usually belongs to. */
  default_phase?: TreatmentPhase | null
  /** Disciplines that perform it. Replaces the assignment when present. */
  specialty_ids?: string[]
}

/** Layered visualization rule. Each layer renders on top of the previous. */
export interface VisualizationRuleLayer {
  layer: VisualizationLayer
  icon?: string
  pattern?: string
  color?: string
  kind?: string
  extent?: string
}

export interface OdontogramTreatment {
  id: string
  internal_code: string
  names: Record<string, string>
  default_price?: string | null
  treatment_scope: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  requires_surfaces: boolean
  is_diagnostic: boolean
  // Pricing
  pricing_strategy: PricingStrategy
  pricing_config?: Record<string, number> | null
  surface_prices?: Record<string, number> | null
  // Odontogram specific
  odontogram_treatment_type: ClinicalType
  visualization_rules: VisualizationRuleLayer[]
  visualization_config: Record<string, unknown>
  clinical_category: string
  // Category info
  category_key: string
  category_names: Record<string, string>
}

// ============================================================================
// Budget Types (Simplified)
// ============================================================================

export type BudgetStatus
  = | 'draft' // Initial state, editable
    | 'sent' // Sent to patient, awaiting response
    | 'accepted' // Patient accepted, ready for treatment/invoicing
    | 'completed' // All work done
    | 'rejected' // Patient rejected (terminal)
    | 'expired' // Validity period passed (terminal)
    | 'cancelled' // Cancelled before acceptance (terminal)

export type DiscountType = 'percentage' | 'absolute'

export type SignatureType = 'full_acceptance' | 'rejection'

export type SignatureMethod = 'click_accept' | 'drawn' | 'external_provider'

export type RelationshipToPatient = 'patient' | 'guardian' | 'representative'

// Brief types for nested responses
export interface PatientBrief {
  id: string
  first_name: string
  last_name: string
  phone?: string
  email?: string
}

export interface UserBrief {
  id: string
  first_name: string
  last_name: string
}

export interface CatalogItemBrief {
  id: string
  internal_code: string
  names: Record<string, string>
  default_price?: Money
  default_duration_minutes?: number
  is_active?: boolean
}

// Budget Item
export interface BudgetItem {
  id: string
  budget_id: string
  catalog_item_id: string
  // Pricing
  unit_price: Money
  quantity: number
  // Line discount
  discount_type?: DiscountType
  discount_value?: Money
  // VAT
  vat_type_id?: string
  vat_rate: number
  // Calculated totals
  line_subtotal: Money
  line_discount: Money
  line_tax: Money
  line_total: Money
  // Dental specifics
  tooth_number?: number
  surfaces?: string[]
  // Odontogram integration
  treatment_id?: string
  // Invoice tracking
  invoiced_quantity: number
  // Display
  display_order: number
  notes?: string
  // Timestamps
  created_at: string
  updated_at: string
  // Related
  catalog_item?: CatalogItemBrief
  vat_type?: VatTypeBrief
}

export interface BudgetItemCreate {
  catalog_item_id: string
  quantity?: number
  unit_price?: Money
  discount_type?: DiscountType
  discount_value?: Money
  tooth_number?: number
  surfaces?: string[]
  treatment_id?: string
  display_order?: number
  notes?: string
}

export interface BudgetItemUpdate {
  quantity?: number
  unit_price?: Money
  discount_type?: DiscountType
  discount_value?: Money
  tooth_number?: number
  surfaces?: string[]
  display_order?: number
  notes?: string
}

// Budget Signature
export interface BudgetSignature {
  id: string
  budget_id: string
  signature_type: SignatureType
  signed_items?: string[]
  signed_by_name: string
  signed_by_email?: string
  relationship_to_patient: RelationshipToPatient
  signature_method: SignatureMethod
  signature_data?: Record<string, unknown>
  ip_address?: string
  signed_at: string
  external_signature_id?: string
  external_provider?: string
  document_hash?: string
  created_at: string
}

export interface SignatureCreate {
  signed_by_name: string
  signed_by_email?: string
  relationship_to_patient?: RelationshipToPatient
  signature_data?: Record<string, unknown>
}

// Budget History
export interface BudgetHistoryEntry {
  id: string
  budget_id: string
  action: string
  changed_by: string
  changed_at: string
  previous_state?: Record<string, unknown>
  new_state?: Record<string, unknown>
  notes?: string
  user?: UserBrief
}

// Budget
export interface Budget {
  id: string
  clinic_id: string
  patient_id: string
  // Identification
  budget_number: string
  version: number
  parent_budget_id?: string
  // Status
  status: BudgetStatus
  // Validity
  valid_from: string
  valid_until?: string
  // Assignments
  created_by: string
  assigned_professional_id?: string
  // Global discount
  global_discount_type?: DiscountType
  global_discount_value?: Money
  // Totals
  subtotal: Money
  total_discount: Money
  total_tax: Money
  total: Money
  // Notes
  internal_notes?: string
  patient_notes?: string
  // Insurance
  insurance_estimate?: Money
  // Public link token (ADR 0006). Present on every budget; reception
  // shares ``${origin}/p/budget/${public_token}`` with the patient.
  public_token?: string
  // Timestamps
  created_at: string
  updated_at: string
  deleted_at?: string
  // Related
  patient?: PatientBrief
  creator?: UserBrief
  assigned_professional?: UserBrief
}

export interface BudgetDetail extends Budget {
  items: BudgetItem[]
  signatures: BudgetSignature[]
  treatment_plan?: TreatmentPlanBrief
}

export interface BudgetListItem {
  id: string
  budget_number: string
  version: number
  status: BudgetStatus
  valid_from: string
  valid_until?: string
  total: Money
  created_at: string
  patient?: PatientBrief
  creator?: UserBrief
}

export interface BudgetCreate {
  patient_id: string
  valid_from?: string
  valid_until?: string
  assigned_professional_id?: string
  global_discount_type?: DiscountType
  global_discount_value?: Money
  internal_notes?: string
  patient_notes?: string
  items?: BudgetItemCreate[]
}

export interface BudgetUpdate {
  valid_from?: string
  valid_until?: string
  assigned_professional_id?: string
  global_discount_type?: DiscountType
  global_discount_value?: Money
  internal_notes?: string
  patient_notes?: string
}

// Workflow
export interface BudgetSendRequest {
  send_email?: boolean
  custom_message?: string
}

export interface BudgetAcceptRequest {
  signature: SignatureCreate
}

export interface BudgetRejectRequest {
  reason?: string
  signature?: SignatureCreate
}

export interface BudgetSendRequest {
  send_email?: boolean
  custom_message?: string
}

export interface BudgetCancelRequest {
  reason?: string
}

// Versions
export interface BudgetVersion {
  id: string
  version: number
  status: BudgetStatus
  total: Money
  created_at: string
  is_current: boolean
}

export interface BudgetVersionList {
  budget_number: string
  versions: BudgetVersion[]
  current_version: number
}

// ============================================================================
// Notification Types
// ============================================================================

export interface EmailTemplate {
  id: string
  clinic_id?: string
  template_key: string
  locale: string
  subject: string
  body_html: string
  body_text?: string
  variables?: Record<string, unknown>
  description?: string
  is_system: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface EmailTemplateCreate {
  template_key: string
  locale?: string
  subject: string
  body_html: string
  body_text?: string
  variables?: Record<string, unknown>
  description?: string
  is_active?: boolean
}

export interface EmailTemplateUpdate {
  subject?: string
  body_html?: string
  body_text?: string
  variables?: Record<string, unknown>
  description?: string
  is_active?: boolean
}

export interface NotificationPreference {
  id: string
  clinic_id: string
  patient_id?: string
  user_id?: string
  email_enabled: boolean
  whatsapp_enabled: boolean
  preferences: Record<string, boolean>
  preferred_locale: string
  created_at: string
  updated_at: string
}

export interface NotificationPreferenceUpdate {
  email_enabled?: boolean
  whatsapp_enabled?: boolean
  preferences?: Record<string, boolean>
  preferred_locale?: string
}

export interface NotificationTypeSettings {
  auto_send: boolean
  enabled: boolean
  hours_before?: number
  channels?: string[]
}

export interface ClinicNotificationSettings {
  id: string
  clinic_id: string
  settings: Record<string, NotificationTypeSettings>
  created_at: string
  updated_at: string
}

export interface ClinicNotificationSettingsUpdate {
  settings: Record<string, Partial<NotificationTypeSettings>>
}

export interface EmailLog {
  id: string
  clinic_id: string
  channel: string
  to_address: string
  patient_id?: string
  template_key: string
  subject?: string
  status: 'queued' | 'sending' | 'sent' | 'failed' | 'skipped' | 'delivered' | 'read'
  attempts: number
  provider?: string
  provider_message_id?: string
  error_message?: string
  created_at: string
  sent_at?: string
  delivered_at?: string
  triggered_by_event?: string
}

export interface ManualSendRequest {
  notification_type: string
  patient_id?: string
  appointment_id?: string
  budget_id?: string
  custom_context?: Record<string, unknown>
}

export interface ManualSendResponse {
  success: boolean
  message: string
  log_id?: string
}

export interface TestEmailRequest {
  to_email: string
}

export interface TestEmailResponse {
  success: boolean
  message: string
  provider: string
}

// SMTP Settings types
export type SmtpProvider = 'smtp' | 'console' | 'disabled'

export interface SmtpSettings {
  provider: SmtpProvider
  host: string | null
  port: number | null
  username: string | null
  has_password: boolean
  use_tls: boolean
  use_ssl: boolean
  from_email: string | null
  from_name: string | null
  is_active: boolean
  is_verified: boolean
  last_verified_at: string | null
}

export interface SmtpSettingsUpdate {
  provider?: SmtpProvider
  host?: string
  port?: number
  username?: string
  password?: string
  use_tls?: boolean
  use_ssl?: boolean
  from_email?: string
  from_name?: string
}

export interface SmtpTestRequest {
  host: string
  port: number
  username?: string
  password?: string
  use_tls: boolean
  use_ssl: boolean
  from_email: string
  to_email: string
}

// ============================================================================
// Billing Types
// ============================================================================

export type InvoiceStatus = 'draft' | 'issued' | 'partial' | 'paid' | 'cancelled' | 'voided'

export type PaymentMethod = 'cash' | 'card' | 'bank_transfer' | 'direct_debit' | 'insurance' | 'other'

// ============================================================================
// Payments module (issue #53). Patient-centric Payment, allocations,
// refunds, ledger, reports. See ADR 0010.
// ============================================================================

export type AllocationTarget = 'budget' | 'on_account'
export type RefundReason = 'duplicate' | 'overpaid' | 'treatment_cancelled' | 'dispute' | 'other'

export interface PaymentAllocation {
  id: string
  target_type: AllocationTarget
  target_id?: string
  amount: Money
  created_at: string
  created_by: string
  method?: PaymentMethod
}

export interface PaymentAllocationCreate {
  target_type: AllocationTarget
  target_id?: string
  amount: Money
}

export interface PaymentRefund {
  id: string
  payment_id: string
  amount: Money
  method: PaymentMethod
  reason_code: RefundReason
  reason_note?: string
  refunded_at: string
  refunded_by: string
  refunder?: UserBrief
}

export interface PaymentRefundCreate {
  amount: Money
  method: PaymentMethod
  reason_code: RefundReason
  reason_note?: string
}

export interface PaymentRecord {
  id: string
  clinic_id: string
  patient_id: string
  amount: Money
  currency: string
  method: PaymentMethod
  payment_date: string
  reference?: string
  notes?: string
  recorded_by: string
  created_at: string
  updated_at: string
  allocations: PaymentAllocation[]
  refunded_total: Money
  net_amount: Money
  recorder?: UserBrief
  patient?: { id: string, first_name: string, last_name: string }
}

export interface PaymentRecordCreate {
  patient_id: string
  amount: Money
  method: PaymentMethod
  payment_date?: string
  reference?: string
  notes?: string
  allocations: PaymentAllocationCreate[]
}

export interface PaymentReallocate {
  allocations: PaymentAllocationCreate[]
}

export interface PatientLedgerEntry {
  entry_type: 'payment' | 'refund' | 'earned'
  occurred_at: string
  amount: Money
  reference_id: string
  description?: string
  // Earned-only enrichment populated by the timeline builder when
  // the entry resolves to a Treatment row.
  treatment_id?: string | null
  treatment_name?: string | null
  treatment_status?: string | null
  professional_id?: string | null
  professional_name?: string | null
}

export interface PatientLedger {
  patient_id: string
  currency: string
  total_paid: Money
  total_earned: Money
  patient_credit: Money
  clinic_receivable: Money
  on_account_balance: Money
  timeline: PatientLedgerEntry[]
}

export interface PaymentsSummary {
  period_start: string
  period_end: string
  currency: string
  total_collected: Money
  total_refunded: Money
  net_collected: Money
  patient_credit_total: Money
  clinic_receivable_total: Money
  refund_ratio: number
  payment_count: number
  refund_count: number
}

export interface MethodBreakdown {
  method: string
  total: Money
  count: number
}

export interface ProfessionalBreakdown {
  professional_id?: string
  professional_name?: string
  total_earned: Money
  count: number
}

export interface AgingBucket {
  label: string
  total: Money
  patient_count: number
}

export interface AgingBuckets {
  currency: string
  buckets: AgingBucket[]
}

export interface RefundsReport {
  period_start: string
  period_end: string
  currency: string
  total_refunded: Money
  refund_ratio: number
  by_reason: { reason_code: string, total: number, count: number }[]
  by_method: MethodBreakdown[]
}

export interface PaymentsTrendPoint {
  bucket_start: string
  collected: Money
  refunded: Money
  net: Money
}

export interface PaymentsTrends {
  granularity: 'day' | 'week' | 'month' | 'year'
  currency: string
  points: PaymentsTrendPoint[]
}

// Billing-side link to a Payment (issue #53).
export interface InvoicePayment {
  id: string
  invoice_id: string
  payment_id: string
  /** Decimal on the wire: the API serialises money as a string. */
  amount: number | string
  created_by: string
  /** When the imputation was recorded — not when the patient paid. */
  created_at: string
  /** From the linked payment; absent only if the relation was not loaded. */
  payment_date?: string | null
  payment_method?: PaymentMethod | null
}

export interface InvoicePaymentApply {
  amount: Money
  method: PaymentMethod
  payment_date?: string
  reference?: string
  notes?: string
}

export type SeriesType = 'invoice' | 'credit_note'

// Invoice Series
export interface InvoiceSeries {
  id: string
  clinic_id: string
  prefix: string
  series_type: SeriesType
  description?: string
  current_number: number
  reset_yearly: boolean
  last_reset_year?: number
  is_default: boolean
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface InvoiceSeriesCreate {
  prefix: string
  series_type: SeriesType
  description?: string
  reset_yearly?: boolean
  is_default?: boolean
}

export interface InvoiceSeriesUpdate {
  prefix?: string
  description?: string
  reset_yearly?: boolean
  is_default?: boolean
  is_active?: boolean
}

export interface SeriesResetRequest {
  new_number: number
}

// Invoice Item
export interface InvoiceItem {
  id: string
  invoice_id: string
  budget_item_id?: string
  catalog_item_id?: string
  // Description
  description: string
  internal_code?: string
  // Pricing
  unit_price: Money
  quantity: number
  // Discounts
  discount_type?: DiscountType
  discount_value?: Money
  // VAT
  vat_type_id?: string
  vat_rate: number
  vat_exempt_reason?: string
  // Calculated totals
  line_subtotal: Money
  line_discount: Money
  line_tax: Money
  line_total: Money
  // Dental context
  tooth_number?: number
  surfaces?: string[]
  // Display
  display_order: number
  // Timestamps
  created_at: string
  updated_at: string
  // Related
  catalog_item?: CatalogItemBrief
  vat_type?: VatTypeBrief
}

export interface InvoiceItemCreate {
  description: string
  internal_code?: string
  catalog_item_id?: string
  unit_price: Money
  quantity?: number
  discount_type?: DiscountType
  discount_value?: Money
  vat_type_id?: string
  vat_exempt_reason?: string
  tooth_number?: number
  surfaces?: string[]
  display_order?: number
}

export interface InvoiceItemFromBudget {
  budget_item_id: string
  quantity?: number
}

export interface InvoiceItemUpdate {
  description?: string
  unit_price?: Money
  quantity?: number
  discount_type?: DiscountType
  discount_value?: Money
  vat_type_id?: string
  vat_exempt_reason?: string
  display_order?: number
}

// Payment
export interface Payment {
  id: string
  invoice_id: string
  amount: Money
  payment_method: PaymentMethod
  payment_date: string
  reference?: string
  notes?: string
  recorded_by: string
  created_at: string
  // Voiding
  is_voided: boolean
  voided_at?: string
  voided_by?: string
  void_reason?: string
  // Related
  recorder?: UserBrief
  voider?: UserBrief
}

export interface PaymentCreate {
  amount: Money
  payment_method: PaymentMethod
  payment_date?: string
  reference?: string
  notes?: string
}

export interface PaymentVoidRequest {
  reason: string
}

// Invoice History
export interface InvoiceHistoryEntry {
  id: string
  invoice_id: string
  action: string
  changed_by: string
  changed_at: string
  previous_state?: Record<string, unknown>
  new_state?: Record<string, unknown>
  notes?: string
  user?: UserBrief
}

// Invoice Brief (for references)
export interface InvoiceBrief {
  id: string
  invoice_number: string
  status: InvoiceStatus
  total: Money
  issue_date?: string
}

// Billing Address
export interface BillingAddress {
  street?: string
  city?: string
  postal_code?: string
  province?: string
  country?: string
}

// Invoice
export interface Invoice {
  id: string
  clinic_id: string
  patient_id: string
  // Identification (null for drafts, assigned when issued)
  invoice_number: string | null
  sequential_number: number | null
  series_id: string | null
  // Links
  budget_id?: string
  credit_note_for_id?: string
  // Status
  status: InvoiceStatus
  // Dates
  issue_date?: string
  due_date?: string
  payment_term_days: number
  // Billing data
  billing_name: string
  billing_tax_id?: string
  billing_address?: BillingAddress
  billing_email?: string
  // Totals
  subtotal: Money
  total_discount: Money
  total_tax: Money
  total: Money
  total_paid: Money
  balance_due: Money
  // Notes
  internal_notes?: string
  public_notes?: string
  // Extensibility
  compliance_data?: Record<string, unknown>
  document_hash?: string
  // Audit
  created_by: string
  issued_by?: string
  // Timestamps
  created_at: string
  updated_at: string
  deleted_at?: string
  // Related
  patient?: PatientBrief
  creator?: UserBrief
  issuer?: UserBrief
  budget?: BudgetBrief
  credit_note_for?: InvoiceBrief
}

export interface InvoiceDetail extends Invoice {
  items: InvoiceItem[]
  payments: Payment[]
}

export interface InvoiceListItem {
  id: string
  invoice_number: string | null // Null for drafts (assigned when issued)
  status: InvoiceStatus
  issue_date?: string
  due_date?: string
  total: Money
  total_paid: Money
  balance_due: Money
  created_at: string
  // Generic compliance summary keyed by ISO country (e.g.
  // {"ES": {state, severity, error_message, ...}}). Owned by the
  // active compliance module — billing exposes it raw.
  compliance_data?: Record<string, Record<string, unknown>> | null
  patient?: PatientBrief
  creator?: UserBrief
}

export interface BudgetBrief {
  id: string
  budget_number: string
  status: BudgetStatus
  total: Money
}

export interface InvoiceCreate {
  patient_id: string
  series_id?: string
  // Billing data removed - drafts get it from patient dynamically
  payment_term_days?: number
  due_date?: string
  internal_notes?: string
  public_notes?: string
  items?: InvoiceItemCreate[]
}

export interface InvoiceFromBudgetCreate {
  items: InvoiceItemFromBudget[]
  // Billing data removed - drafts get it from patient dynamically
  payment_term_days?: number
  due_date?: string
  internal_notes?: string
  public_notes?: string
}

export interface InvoiceUpdate {
  patient_id?: string // Can change patient for draft invoices (without budget)
  // Billing data removed - drafts get it from patient dynamically
  payment_term_days?: number
  due_date?: string
  internal_notes?: string
  public_notes?: string
}

// Workflow
export interface InvoiceIssueRequest {
  issue_date?: string
}

export interface InvoiceSendRequest {
  send_email: boolean
  custom_message?: string
}

export interface CreditNoteItemSelect {
  invoice_item_id: string
  quantity?: number
}

export interface CreditNoteCreate {
  reason: string
  items?: CreditNoteItemSelect[]
  internal_notes?: string
  public_notes?: string
}

// Settings
export interface BillingSettings {
  default_payment_term_days: number
  invoice_footer_text?: string
  bank_account_info?: string
}

export interface BillingSettingsUpdate {
  default_payment_term_days?: number
  invoice_footer_text?: string
  bank_account_info?: string
}

// Report Types
export interface VatSummaryItem {
  vat_type_id?: string
  vat_rate: number
  vat_name: string
  base_amount: Money
  tax_amount: Money
  total_amount: Money
}

export interface BillingSummary {
  period_start: string
  period_end: string
  total_invoiced: Money
  total_paid: Money
  total_pending: Money
  invoice_count: number
  paid_count: number
  overdue_count: number
  vat_breakdown: VatSummaryItem[]
}

export interface OverdueInvoice {
  id: string
  invoice_number: string
  patient_name: string
  issue_date: string
  due_date: string
  days_overdue: number
  balance_due: Money
}

export interface PaymentMethodSummary {
  payment_method: string
  total_amount: Money
  payment_count: number
}

export interface ProfessionalBillingSummary {
  professional_id: string
  professional_name: string
  total_invoiced: Money
  invoice_count: number
}

export interface NumberingGap {
  series_prefix: string
  year: number
  missing_numbers: number[]
}

export interface PatientBillingSummary {
  patient_id: string
  // Budget metrics
  total_budgeted: Money
  work_in_progress: Money
  work_completed: Money
  // Invoice metrics
  total_invoiced: Money
  total_paid: Money
  balance_pending: Money
}

// ============================================================================
// Patient Extended Types (Medical History, Emergency Contact, Timeline)
// ============================================================================

// Patient Address
export interface PatientAddress {
  street?: string
  city?: string
  postal_code?: string
  province?: string
  country?: string
}

// Emergency Contact
export interface EmergencyContact {
  name: string
  relationship?: string
  phone: string
  email?: string
  is_legal_guardian: boolean
}

// Legal Guardian (for minors)
export interface LegalGuardian {
  name: string
  relationship: string // parent, grandparent, legal_tutor, other
  dni?: string
  phone: string
  email?: string
  address?: string
  notes?: string
}

// Medical History Entry Types
export interface AllergyEntry {
  name: string
  type?: string // drug, food, material, environmental
  severity: 'low' | 'medium' | 'high' | 'critical'
  reaction?: string
  notes?: string
}

export interface MedicationEntry {
  name: string
  dosage?: string
  frequency?: string
  start_date?: string
  notes?: string
}

export interface SystemicDiseaseEntry {
  name: string
  type?: string // cardiovascular, respiratory, endocrine, etc.
  diagnosis_date?: string
  is_controlled: boolean
  is_critical: boolean
  medications?: string
  notes?: string
}

export interface SurgicalHistoryEntry {
  procedure: string
  surgery_date?: string
  complications?: string
  notes?: string
}

export type FamilyRelative = 'mother' | 'father' | 'sibling' | 'grandparent' | 'child' | 'other'

export interface FamilyHistoryEntry {
  condition: string
  relative: FamilyRelative
  notes?: string
}

// Full Medical History
export interface MedicalHistory {
  // Lists
  allergies: AllergyEntry[]
  medications: MedicationEntry[]
  systemic_diseases: SystemicDiseaseEntry[]
  surgical_history: SurgicalHistoryEntry[]
  /** Conditions that run in the family (antecedentes heredo-familiares). */
  family_history?: FamilyHistoryEntry[]

  // Special conditions
  is_pregnant: boolean
  pregnancy_week?: number
  is_lactating: boolean

  // Anticoagulants
  is_on_anticoagulants: boolean
  anticoagulant_medication?: string
  inr_value?: number
  last_inr_date?: string

  // Lifestyle
  is_smoker: boolean
  smoking_frequency?: string
  alcohol_consumption?: string

  // Dental specific
  bruxism: boolean

  // Anesthesia
  adverse_reactions_to_anesthesia: boolean
  anesthesia_reaction_details?: string

  // Metadata
  last_updated_at?: string
  last_updated_by?: string
}

// Patient Alert
export interface PatientAlert {
  type: 'asa' | 'allergy' | 'pregnancy' | 'lactating' | 'anticoagulant' | 'anesthesia_reaction' | 'systemic_disease'
  severity: 'low' | 'medium' | 'high' | 'critical'
  title: string
  details?: string
}

// Extended Patient (with all new fields)
export interface PatientExtended extends Patient {
  // Extended demographics
  gender?: 'male' | 'female'
  national_id?: string
  national_id_type?: 'curp' | 'ine' | 'passport' | 'dni' | 'nie' | 'nif'
  profession?: string
  workplace?: string
  preferred_language: string
  address?: PatientAddress
  photo_url?: string

  // Emergency contact
  emergency_contact?: EmergencyContact

  // Legal guardian (for minors)
  legal_guardian?: LegalGuardian

  // Computed alerts
  active_alerts: PatientAlert[]
}

export interface PatientExtendedUpdate extends PatientUpdate {
  // Extended demographics. `null` clears, as above.
  gender?: string | null
  national_id?: string | null
  national_id_type?: string | null
  profession?: string | null
  workplace?: string | null
  preferred_language?: string | null
  address?: PatientAddress | null
  photo_url?: string | null

  // Emergency contact
  emergency_contact?: EmergencyContact

  // Legal guardian (for minors)
  legal_guardian?: LegalGuardian
}

// Timeline Types
export type TimelineCategory = 'visit' | 'treatment' | 'financial' | 'communication' | 'medical' | 'document' | 'note'

export interface TimelineEntry {
  id: string
  event_type: string
  event_category: TimelineCategory
  source_table: string
  source_id: string
  title: string
  description?: string
  event_data?: Record<string, unknown>
  occurred_at: string
  created_by?: string
}

export interface TimelineResponse {
  entries: TimelineEntry[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

// ============================================================================
// Document Types (Media Module)
// ============================================================================

export type DocumentType = 'consent' | 'id_scan' | 'insurance' | 'report' | 'referral' | 'other'

export type MediaKind = 'document' | 'photo' | 'xray' | 'scan' | 'video'
export type MediaCategory = 'intraoral' | 'extraoral' | 'xray' | 'clinical' | 'other'

export interface UploaderBrief {
  id: string
  first_name: string
  last_name: string
}

export interface Document {
  id: string
  patient_id: string
  document_type: DocumentType
  title: string
  description?: string
  original_filename: string
  mime_type: string
  file_size: number
  status: 'active' | 'archived'
  // Media taxonomy (issue #55)
  media_kind: MediaKind
  media_category?: MediaCategory | null
  media_subtype?: string | null
  captured_at?: string | null
  paired_document_id?: string | null
  tags: string[]
  uploaded_by: string
  uploader?: UploaderBrief
  created_at: string
  updated_at: string
  // Convenience download URLs (server-decorated). thumb/medium are null for
  // non-thumbnailable documents (PDFs, etc.); full is always present.
  thumb_url?: string | null
  medium_url?: string | null
  full_url?: string | null
}

export interface DocumentBrief {
  id: string
  document_type: string
  title: string
  original_filename: string
  mime_type: string
  file_size: number
  media_kind: MediaKind
  media_category?: MediaCategory | null
  media_subtype?: string | null
  created_at: string
}

export interface DocumentCreate {
  document_type: DocumentType
  title: string
  description?: string
}

export interface DocumentUpdate {
  document_type?: DocumentType
  title?: string
  description?: string
}

export interface PhotoMetadataUpdate {
  media_category?: MediaCategory | null
  media_subtype?: string | null
  captured_at?: string | null
  tags?: string[] | null
  paired_document_id?: string | null
}

export interface MediaAttachment {
  id: string
  document_id: string
  owner_type: string
  owner_id: string
  display_order: number
  created_at: string
  document?: DocumentBrief | null
  thumb_url?: string | null
}

export interface AttachmentCreate {
  document_id: string
  owner_type: string
  owner_id: string
  display_order?: number
}

// ============================================================================
// Treatment Plan Types
// ============================================================================

// Mirrors the backend state machine (treatment_plan/CLAUDE.md): draft →
// pending → active → completed, with `closed` as the terminal
// non-completed state. `pending` and `closed` were absent and
// `cancelled` — which no plan row ever holds — stood in for them, so
// callers filtering on the real statuses had to cast.
export type TreatmentPlanStatus
  = 'draft' | 'pending' | 'active' | 'completed' | 'closed' | 'archived'

export type PlannedItemStatus = 'pending' | 'completed' | 'cancelled'

/** Nested Treatment brief embedded in plan items (subset of Treatment). */
export interface TreatmentBrief {
  id: string
  clinical_type: ClinicalType
  scope: 'tooth' | 'multi_tooth' | 'global_mouth' | 'global_arch'
  arch?: 'upper' | 'lower' | null
  status: TreatmentStatus
  catalog_item_id?: string | null
  catalog_item?: TreatmentCatalogItemBrief | null
  price_snapshot?: string | null
  teeth: Array<{
    tooth_number: number
    role?: 'pillar' | 'pontic' | null
    surfaces?: Surface[] | null
  }>
}

// Brief treatment plan info (for embedding in items)
export interface TreatmentPlanBrief {
  id: string
  plan_number: string
  title?: string
  status: TreatmentPlanStatus
}

// Planned Treatment Item (references a single Treatment via treatment_id).
export type PlanItemSessionStatus = 'pending' | 'completed' | 'cancelled'

export interface PlanItemSession {
  id: string
  sequence: number
  label?: string | null
  amount: number | string
  status: PlanItemSessionStatus
  completed_at?: string | null
  completed_by?: string | null
  notes?: string | null
}

export interface PlannedTreatmentItem {
  id: string
  clinic_id: string
  treatment_plan_id: string
  treatment_id: string
  sequence_order: number
  /**
   * Stage of care, seeded from the catalog item's `default_phase` and
   * overridable per patient. Drives the grouping of the plan list.
   */
  phase?: TreatmentPhase | null
  status: PlannedItemStatus
  completed_without_appointment: boolean
  completed_at?: string
  completed_by?: string
  assigned_professional_id?: string | null
  notes?: string
  created_at: string
  updated_at: string
  // Nested data
  treatment?: TreatmentBrief
  catalog_item?: TreatmentCatalogItemBrief
  sessions?: PlanItemSession[]
  // Optional plan info (enriched client-side for appointment selector)
  treatment_plan?: TreatmentPlanBrief
}

export interface PlannedTreatmentItemCreate {
  treatment_id: string
  sequence_order?: number
  phase?: TreatmentPhase | null
  notes?: string
  assigned_professional_id?: string | null
}

export interface PlannedTreatmentItemUpdate {
  sequence_order?: number
  phase?: TreatmentPhase | null
  notes?: string
  assigned_professional_id?: string | null
}

export interface CompleteItemRequest {
  completed_without_appointment?: boolean
  notes?: string
}

// Clinical notes — owned by the ``clinical_notes`` module since issue #60.
// Polymorphic over four note_type / owner_type pairings:
//   administrative + diagnosis → owner_type='patient'
//   treatment                  → owner_type='treatment' (odontogram.Treatment.id)
//   treatment_plan             → owner_type='plan' (treatment_plans.id)
export type NoteType
  = | 'administrative'
    | 'diagnosis'
    | 'treatment'
    | 'treatment_plan'
    | 'appointment_clinical'
    | 'appointment_administrative'

export type ClinicalNoteOwnerType = 'patient' | 'treatment' | 'plan' | 'appointment'
export type AttachmentOwnerType = ClinicalNoteOwnerType | 'clinical_note'

export interface NoteAttachment {
  id: string
  document_id: string
  owner_type: AttachmentOwnerType
  owner_id: string
  display_order: number
  created_at: string
  // Document brief — populated by clinical_notes router for inline rendering
  // (preview thumbnail, click-to-lightbox). All optional so transitional
  // callers that don't decorate still parse.
  title?: string | null
  mime_type?: string | null
  media_kind?: MediaKind | null
  thumb_url?: string | null
  medium_url?: string | null
  full_url?: string | null
}

/** Vital signs taken at a visit; every reading is optional. */
export interface NoteVitals {
  systolic?: number | null
  diastolic?: number | null
  heart_rate?: number | null
  respiratory_rate?: number | null
  temperature_c?: number | null
}

export interface ClinicalNote {
  id: string
  clinic_id: string
  note_type: NoteType
  owner_type: ClinicalNoteOwnerType
  owner_id: string
  tooth_number: number | null
  body: string
  vitals?: NoteVitals | null
  author_id: string
  author?: ClinicalNoteAuthor | null
  created_at: string
  updated_at: string
  attachments: NoteAttachment[]
}

export interface ClinicalNoteCreate {
  note_type: NoteType
  owner_type: ClinicalNoteOwnerType
  owner_id: string
  tooth_number?: number | null
  body: string
  vitals?: NoteVitals | null
  attachment_document_ids?: string[]
}

export interface ClinicalNoteUpdate {
  body: string
}

export interface NoteAttachmentCreate {
  owner_type: AttachmentOwnerType
  owner_id: string
  document_id: string
  note_id?: string | null
  display_order?: number
}

export interface ClinicalNoteAuthor {
  id: string
  full_name: string | null
  email: string | null
}

export interface ClinicalNoteLinked {
  kind: 'patient' | 'treatment' | 'plan' | 'appointment'
  id: string | null
  label: string | null
  tooth_number: number | null
}

export interface RecentNoteEntry {
  id: string
  note_type: NoteType
  owner_type: ClinicalNoteOwnerType
  owner_id: string
  tooth_number: number | null
  body: string
  vitals?: NoteVitals | null
  created_at: string
  updated_at: string
  author: ClinicalNoteAuthor
  linked: ClinicalNoteLinked
  attachments: NoteAttachment[]
}

export interface ClinicalNoteEntry {
  source: 'plan' | 'treatment' | 'visit'
  note_id: string | null
  owner_id: string
  plan_item_id: string | null
  body: string
  vitals?: NoteVitals | null
  author_id: string | null
  author: ClinicalNoteAuthor | null
  created_at: string
  updated_at: string | null
  attachments: NoteAttachment[]
}

export interface PlanItemSummary {
  id: string
  treatment_id: string
  sequence_order: number
  status: string
  label: string | null
  teeth: number[]
}

export interface PlanItemNotesGroup {
  plan_item: PlanItemSummary
  notes: ClinicalNoteEntry[]
}

export interface PlanSummary {
  id: string
  plan_number: string
  title: string | null
  status: string
  created_at: string
}

export interface PlanNotesGroup {
  plan: PlanSummary
  plan_notes: ClinicalNoteEntry[]
  treatments: PlanItemNotesGroup[]
}

export interface NoteTemplate {
  id: string
  category: string
  i18n_key: string
  body: string
}

export interface AppointmentTreatmentNoteUpdate {
  notes?: string | null
  completed_in_appointment?: boolean | null
}

export interface AppointmentTreatmentNoteResponse {
  id: string
  appointment_id: string
  planned_treatment_item_id: string | null
  catalog_item_id: string | null
  display_order: number
  completed_in_appointment: boolean
  notes: string | null
  created_at: string | null
}

// Treatment Plan
export interface TreatmentPlan {
  id: string
  clinic_id: string
  patient_id: string
  plan_number: string
  title?: string
  status: TreatmentPlanStatus
  budget_id?: string
  assigned_professional_id?: string
  created_by: string
  created_at: string
  updated_at: string
  item_count: number
  completed_count: number
  total: Money
  patient?: PatientBrief
  budget?: BudgetBrief
}

/**
 * The one thing that has to happen for a plan to move on, computed per
 * request by the backend. The key is the contract; the copy lives in the
 * locales. `null` once the plan is over.
 */
export interface PlanNextAction {
  key:
    | 'add_treatments'
    | 'confirm_plan'
    | 'generate_budget'
    | 'send_budget'
    | 'awaiting_patient'
    | 'budget_expired'
    | 'budget_rejected'
    | 'budget_cancelled'
    | 'budget_addendum'
    | 'schedule_first'
    | 'schedule_next'
    | 'next_appointment'
    | 'all_done'
  budget_status?: string | null
  next_appointment_at?: string | null
  /** Only for `budget_addendum`: treatments added after confirmation. */
  unbudgeted_count?: number | null
}

export type PlanPrognosis = 'favorable' | 'reserved' | 'unfavorable'

export interface TreatmentPlanDetail extends TreatmentPlan {
  diagnosis_notes?: string
  prognosis?: PlanPrognosis | null
  prognosis_notes?: string
  internal_notes?: string
  items: PlannedTreatmentItem[]
  patient?: PatientBrief
  budget?: BudgetBrief
  next_action?: PlanNextAction | null
  /** The clinic asks for a signed informed consent for this plan and it has none. */
  informed_consent_missing?: boolean
  /** Treatments added after the plan was confirmed that no budget prices. */
  unbudgeted_count?: number
  /** The plan's other live budgets — its addenda. */
  other_budgets?: BudgetBrief[]
}

export interface TreatmentPlanCreate {
  patient_id: string
  title?: string
  assigned_professional_id?: string
  diagnosis_notes?: string
  prognosis?: PlanPrognosis | null
  prognosis_notes?: string
  internal_notes?: string
}

export interface TreatmentPlanUpdate {
  title?: string
  assigned_professional_id?: string
  diagnosis_notes?: string
  prognosis?: PlanPrognosis | null
  prognosis_notes?: string
  internal_notes?: string
  /**
   * When true and the plan's `assigned_professional_id` changes, the backend
   * reassigns pending items still pointing at the previous plan doctor.
   * Items with an explicit override or completed items are left alone.
   */
  reassign_pending_items?: boolean
}

export interface TreatmentPlanStatusUpdate {
  status: TreatmentPlanStatus
}

// Budget integration
export interface LinkBudgetRequest {
  budget_id: string
}

export interface GenerateBudgetResponse {
  budget_id: string
  budget_number: string
}

/** One line of a plan template: a catalog item and, optionally, its stage. */
export interface PlanTemplateItem {
  id: string
  sequence: number
  catalog_item_id: string
  phase?: TreatmentPhase | null
  /** A line the clinic may not offer or the patient may not need. */
  is_optional: boolean
  notes?: string | null
  catalog_item?: {
    id: string
    internal_code: string
    names: Record<string, string>
    default_price?: number | null
    /** tooth / multi_tooth need teeth; global_* do not. */
    treatment_scope?: string | null
  } | null
}

/**
 * A charted finding with the treatment proposed for it.
 *
 * `suggested_catalog_item` is null when the clinic's catalog has nothing
 * matching: the finding is still worth listing, because the dentist may want
 * to know it is unaddressed even if the app cannot propose anything.
 */
export interface PlanProposal {
  finding_id: string
  clinical_type: string
  tooth_number?: number | null
  surfaces?: Surface[] | null
  suggested_catalog_item?: {
    id: string
    internal_code: string
    names: Record<string, string>
    default_price?: number | null
    treatment_scope?: string | null
    default_phase?: TreatmentPhase | null
  } | null
}

export interface PlanTemplate {
  id: string
  key?: string | null
  /** The discipline a reference template belongs to; none on the clinic's own. */
  specialty?: { key: string, names: Record<string, string> } | null
  name: string
  description?: string | null
  is_active: boolean
  display_order: number
  items: PlanTemplateItem[]
}

export interface PlanTemplateItemInput {
  catalog_item_id: string
  phase?: TreatmentPhase | null
  is_optional?: boolean
  notes?: string | null
}

export interface PlanTemplateCreate {
  name: string
  description?: string | null
  display_order?: number
  items: PlanTemplateItemInput[]
}

export interface ApplyTemplateRequest {
  template_id: string
  /**
   * Every per-tooth treatment in the template is created once per tooth
   * listed; whole-mouth ones once regardless. Empty for a template with no
   * per-tooth treatments.
   */
  tooth_numbers: number[]
  /** Optional lines this patient does not need. Required ones are refused. */
  excluded_template_item_ids?: string[]
}

/** A template line that could not be applied — the clinic has no such treatment. */
export interface SkippedTemplateLine {
  name: string
  reason: string
}

export interface ApplyTemplateResult {
  items: PlannedTreatmentItem[]
  skipped: SkippedTemplateLine[]
}

/**
 * One treatment on a plan that is still being drawn.
 *
 * Client-side only: it lives in the builder's memory from the tap on the
 * tooth until the plan is created, and never round-trips. The `id` is a
 * counter, not anything the server issued.
 */
export interface PlanDraftLine {
  id: string
  catalogItemId: string
  name: string
  /** Chart type, when the catalog item maps to one. Drives the icon. */
  clinicalType: string
  toothNumbers: number[]
  surfaces: Surface[] | null
  /**
   * Whether the catalog describes this treatment by the faces it touches.
   * A crown does not: it covers the tooth. Carried on the line so the
   * builder can offer the faces for editing without re-reading the catalog.
   */
  requiresSurfaces: boolean
  price: number | null
  /**
   * The charted finding this line was seeded from, when it was not drawn by
   * hand. Deleting such a line is a decision about that finding, and the
   * builder reports it so the new plan stops proposing it.
   */
  findingId?: string | null
  /** tooth | multi_tooth | global_mouth | global_arch. */
  scope: string
  phase: TreatmentPhase | null
  notes: string | null
}
