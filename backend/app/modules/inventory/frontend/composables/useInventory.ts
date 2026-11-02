import { errorMessage } from '~~/app/utils/error'

/**
 * The inventory's API, typed.
 *
 * Mirrors the backend literals rather than importing them: the host has
 * no shared types file for this module, and a narrow copy here is what
 * keeps the screen type-safe. Quantities arrive as strings — they are
 * `NUMERIC(12,3)` and JSON numbers would round them — so everything that
 * does arithmetic parses first.
 */
export type ItemCategory
  = | 'consumable'
    | 'restorative'
    | 'anaesthetic'
    | 'instrument'
    | 'implant'
    | 'prosthetic'
    | 'hygiene'
    | 'office'
    | 'other'

export type LocationKind = 'warehouse' | 'cabinet' | 'fridge' | 'other'

export type MovementReason
  = | 'purchase_receipt'
    | 'consumption'
    | 'transfer'
    | 'adjustment'
    | 'expiry_write_off'
    | 'return'

/** What `POST /movements` accepts: a transfer has its own endpoint. */
export type PostableReason = Exclude<MovementReason, 'transfer' | 'adjustment'>

export interface PurchasePresentation {
  label: string
  factor: string
}

export interface InventoryItem {
  id: string
  code: string
  name: string
  category: ItemCategory
  base_unit: string
  purchase_presentations: PurchasePresentation[]
  tracks_lots: boolean
  reorder_point: string | null
  reorder_quantity: string | null
  cost_per_base_unit: string | null
  notes: string | null
  status: 'active' | 'archived'
  created_at: string
}

export interface InventoryLocation {
  id: string
  name: string
  kind: LocationKind
  cabinet_id: string | null
  is_default: boolean
  status: 'active' | 'archived'
}

export interface InventoryLot {
  id: string
  item_id: string
  lot_code: string
  expires_on: string | null
}

export interface ImplantTrace {
  id: string
  patient_id: string
  /** Null when the Patients app is off: the id is ours, the name is not. */
  first_name: string | null
  last_name: string | null
  item_id: string
  item_code: string
  item_name: string
  lot_id: string
  lot_code: string
  expires_on: string | null
  placed_on: string
  tooth_number: number | null
  serial_number: string | null
  notes: string | null
}

export interface ImplantRecordInput {
  patient_id: string
  item_id: string
  lot_id: string
  placed_on: string
  tooth_number?: number | null
  serial_number?: string | null
  notes?: string | null
}

export interface MaterialLine {
  item_id: string
  item_code: string
  item_name: string
  base_unit: string
  tracks_lots: boolean
  quantity_base: string
}

export interface TreatmentMaterials {
  catalog_item_id: string
  /** Null when the Treatments app is off: the ids are ours, the names are not. */
  treatment_code: string | null
  treatment_name: string | null
  lines: MaterialLine[]
}

export interface CatalogTreatmentOption {
  id: string
  internal_code: string
  name: string
}

export interface StockLine {
  item_id: string
  item_code: string
  item_name: string
  category: ItemCategory
  base_unit: string
  location_id: string
  location_name: string
  lot_id: string | null
  lot_code: string | null
  expires_on: string | null
  quantity: string
  item_total: string
  reorder_point: string | null
  is_low: boolean
  days_to_expiry: number | null
}

export interface StockAlerts {
  low_stock: StockLine[]
  expiring: StockLine[]
  expired: StockLine[]
}

export interface UserBrief {
  id: string
  first_name: string
  last_name: string
}

export interface InventoryMovement {
  id: string
  item_id: string
  item_name: string
  location_id: string
  location_name: string
  lot_id: string | null
  lot_code: string | null
  quantity_base: string
  reason: MovementReason
  note: string | null
  source_ref: Record<string, unknown> | null
  performed_by: string | null
  /** Null for a movement with no human behind it, such as a scheduled job. */
  performed_by_user: UserBrief | null
  cost_per_base_unit: string | null
  created_at: string
}

export interface MovementFilters {
  item_id?: string
  location_id?: string
  reason?: MovementReason
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export interface ItemInput {
  code: string
  name: string
  base_unit: string
  category: ItemCategory
  tracks_lots: boolean
  reorder_point?: string | null
  reorder_quantity?: string | null
  cost_per_base_unit?: string | null
  notes?: string | null
}

export interface MovementInput {
  item_id: string
  location_id?: string | null
  lot_id?: string | null
  quantity_base: string
  reason: PostableReason
  note?: string | null
  cost_per_base_unit?: string | null
}

/**
 * What `PUT /items/{id}` accepts.
 *
 * `code` and `tracks_lots` are absent on purpose: an article's code
 * identifies it, and lot tracking cannot be turned on without leaving
 * the stock already recorded with no lot, nor off without orphaning the
 * lots there are.
 */
export interface ItemUpdateInput {
  name?: string
  base_unit?: string
  category?: ItemCategory
  reorder_point?: string | null
  reorder_quantity?: string | null
  cost_per_base_unit?: string | null
  notes?: string | null
  status?: 'active' | 'archived'
}

export interface LocationInput {
  name: string
  kind: LocationKind
  cabinet_id?: string | null
  is_default?: boolean
}

export interface ItemFilters {
  page?: number
  pageSize?: number
  search?: string
  category?: ItemCategory
  status?: 'active' | 'archived'
}

export interface StockFilters {
  item_id?: string
  location_id?: string
  category?: ItemCategory
  search?: string
  include_empty?: boolean
}

export interface CountLineInput {
  item_id: string
  location_id: string
  lot_id?: string | null
  counted_quantity: string
}

export interface CountResult {
  lines_counted: number
  adjustments_posted: number
  movement_ids: string[]
}

interface ApiOk<T> { data: T }
interface ApiPaged<T> { data: T[], total: number, page: number, page_size: number }

const BASE = '/api/v1/inventory'

/** Quantities are decimal strings; compare and sum as numbers. */
export function quantity(value: string | null): number {
  return value === null ? 0 : Number.parseFloat(value)
}

/**
 * The module's stable error codes, mapped to what to say about them.
 *
 * `errorMessage` falls back to the server's own text, which is English —
 * fine for a log, wrong for a dialog in a Spanish clinic. Only the codes
 * a person can actually hit are here; anything else keeps the fallback.
 */
const CODE_MESSAGES: Record<string, string> = {
  'inventory.item.code_taken': 'inventory.errors.itemCodeTaken',
  'inventory.item.not_found': 'inventory.errors.itemNotFound',
  'inventory.location.name_taken': 'inventory.errors.locationNameTaken',
  'inventory.location.not_empty': 'inventory.errors.locationNotEmpty',
  'inventory.location.archived': 'inventory.errors.locationArchived',
  'inventory.lot.required': 'inventory.errors.lotRequired',
  'inventory.lot.not_tracked': 'inventory.errors.lotNotTracked',
  'inventory.lot.code_taken': 'inventory.errors.lotCodeTaken',
  'inventory.stock.insufficient': 'inventory.errors.stockInsufficient',
  'inventory.movement.sign_invalid': 'inventory.errors.signInvalid',
  'inventory.transfer.same_location': 'inventory.errors.sameLocation'
}

/**
 * Resolve at setup, never inside a handler: this reaches `useI18n`,
 * which throws "Must be called at the top of a `setup` function" from a
 * callback and loses the rest of that callback's work.
 */
export function useInventoryErrors() {
  const { t, te } = useI18n()

  return function message(error: unknown, fallback: string): string {
    const code = (error as { data?: { code?: string } })?.data?.code
    const key = code ? CODE_MESSAGES[code] : undefined
    return key && te(key) ? t(key) : errorMessage(error, fallback)
  }
}

export function useInventory() {
  const api = useApi()

  function query(filters: Record<string, unknown>): string {
    const qs = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null || value === '' || value === false) continue
      qs.append(key, String(value))
    }
    return qs.toString() ? `?${qs.toString()}` : ''
  }

  async function stock(filters: StockFilters = {}): Promise<ApiOk<StockLine[]>> {
    return await api.get<ApiOk<StockLine[]>>(`${BASE}/stock${query(filters)}`)
  }

  async function alerts(windowDays?: number): Promise<ApiOk<StockAlerts>> {
    return await api.get<ApiOk<StockAlerts>>(
      `${BASE}/stock/alerts${query({ window_days: windowDays })}`
    )
  }

  async function items(filters: ItemFilters = {}): Promise<ApiPaged<InventoryItem>> {
    const { page = 1, pageSize = 100, ...rest } = filters
    return await api.get<ApiPaged<InventoryItem>>(
      `${BASE}/items${query({ ...rest, page, page_size: pageSize })}`
    )
  }

  async function createItem(payload: ItemInput): Promise<ApiOk<InventoryItem>> {
    return await api.post<ApiOk<InventoryItem>>(`${BASE}/items`, payload)
  }

  async function updateItem(
    id: string,
    payload: ItemUpdateInput
  ): Promise<ApiOk<InventoryItem>> {
    return await api.put<ApiOk<InventoryItem>>(`${BASE}/items/${id}`, payload)
  }

  /** Archives, never deletes: the ledger references the article forever. */
  async function archiveItem(id: string): Promise<void> {
    await api.del(`${BASE}/items/${id}`)
  }

  async function locations(status?: 'active' | 'archived'): Promise<ApiOk<InventoryLocation[]>> {
    return await api.get<ApiOk<InventoryLocation[]>>(`${BASE}/locations${query({ status })}`)
  }

  async function createLocation(payload: LocationInput): Promise<ApiOk<InventoryLocation>> {
    return await api.post<ApiOk<InventoryLocation>>(`${BASE}/locations`, payload)
  }

  async function updateLocation(
    id: string,
    payload: Partial<LocationInput> & { status?: 'active' | 'archived' }
  ): Promise<ApiOk<InventoryLocation>> {
    return await api.put<ApiOk<InventoryLocation>>(`${BASE}/locations/${id}`, payload)
  }

  /** Refused by the API while the location still holds stock. */
  async function archiveLocation(id: string): Promise<void> {
    await api.del(`${BASE}/locations/${id}`)
  }

  async function lots(itemId: string): Promise<ApiOk<InventoryLot[]>> {
    return await api.get<ApiOk<InventoryLot[]>>(`${BASE}/items/${itemId}/lots`)
  }

  async function createLot(
    itemId: string,
    payload: { lot_code: string, expires_on?: string | null }
  ): Promise<ApiOk<InventoryLot>> {
    return await api.post<ApiOk<InventoryLot>>(`${BASE}/items/${itemId}/lots`, payload)
  }

  async function movements(
    filters: MovementFilters = {}
  ): Promise<ApiPaged<InventoryMovement>> {
    return await api.get<ApiPaged<InventoryMovement>>(`${BASE}/movements${query(filters)}`)
  }

  async function recordMovement(payload: MovementInput): Promise<ApiOk<InventoryMovement>> {
    return await api.post<ApiOk<InventoryMovement>>(`${BASE}/movements`, payload)
  }

  async function closeCount(
    payload: { lines: CountLineInput[], note?: string | null }
  ): Promise<ApiOk<CountResult>> {
    return await api.post<ApiOk<CountResult>>(`${BASE}/stock/count`, payload)
  }

  async function materials(): Promise<ApiOk<TreatmentMaterials[]>> {
    return await api.get<ApiOk<TreatmentMaterials[]>>(`${BASE}/materials`)
  }

  /** Empty when the Treatments app is off — there is nothing to pick. */
  async function catalogueTreatments(): Promise<ApiOk<CatalogTreatmentOption[]>> {
    return await api.get<ApiOk<CatalogTreatmentOption[]>>(`${BASE}/materials/treatments`)
  }

  async function setMaterials(
    catalogItemId: string,
    lines: { item_id: string, quantity_base: string }[]
  ): Promise<ApiOk<MaterialLine[]>> {
    return await api.put<ApiOk<MaterialLine[]>>(`${BASE}/materials/${catalogItemId}`, { lines })
  }

  async function implants(
    filters: { patient_id?: string, lot_id?: string, item_id?: string } = {}
  ): Promise<ApiOk<ImplantTrace[]>> {
    return await api.get<ApiOk<ImplantTrace[]>>(`${BASE}/implants${query(filters)}`)
  }

  async function recordImplant(payload: ImplantRecordInput): Promise<ApiOk<ImplantTrace>> {
    return await api.post<ApiOk<ImplantTrace>>(`${BASE}/implants`, payload)
  }

  return {
    stock,
    alerts,
    items,
    createItem,
    updateItem,
    archiveItem,
    locations,
    createLocation,
    updateLocation,
    archiveLocation,
    lots,
    createLot,
    movements,
    recordMovement,
    closeCount,
    materials,
    catalogueTreatments,
    setMaterials,
    implants,
    recordImplant
  }
}
