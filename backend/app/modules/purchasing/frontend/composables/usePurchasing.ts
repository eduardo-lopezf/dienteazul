/**
 * The purchasing API, typed.
 *
 * Money and quantities arrive as decimal strings — they are `NUMERIC`
 * and JSON numbers would round them — so anything doing arithmetic
 * parses first.
 */
import { errorMessage } from '~~/app/utils/error'

export type OrderStatus
  = | 'draft'
    | 'sent'
    | 'partially_received'
    | 'received'
    | 'cancelled'

export interface Supplier {
  id: string
  name: string
  tax_id: string | null
  contact_name: string | null
  email: string | null
  phone: string | null
  notes: string | null
  status: 'active' | 'archived'
}

export interface SupplierInput {
  name: string
  tax_id?: string | null
  contact_name?: string | null
  email?: string | null
  phone?: string | null
  notes?: string | null
}

export interface OrderLine {
  id: string
  item_id: string
  item_name: string
  item_code: string
  base_unit: string
  tracks_lots: boolean
  quantity_ordered: string
  quantity_received: string
  quantity_pending: string
  unit_cost: string
  line_total: string
}

export interface PurchaseOrder {
  id: string
  number: string
  status: OrderStatus
  supplier_id: string
  supplier_name: string
  order_date: string
  expected_date: string | null
  notes: string | null
  sent_at: string | null
  completed_at: string | null
  total: string
  lines: OrderLine[]
}

export interface OrderLineInput {
  item_id: string
  quantity_ordered: string
  unit_cost: string
}

export interface OrderInput {
  supplier_id: string
  order_date: string
  expected_date?: string | null
  notes?: string | null
  lines: OrderLineInput[]
}

export interface ReceiptLineInput {
  line_id: string
  quantity: string
  lot_code?: string | null
  expires_on?: string | null
}

export interface ReceiptResult {
  order_status: OrderStatus
  lines_received: number
  movement_ids: string[]
}

interface ApiOk<T> { data: T }

const BASE = '/api/v1/purchasing'

/** Decimal strings; compare and sum as numbers. */
export function amount(value: string | null): number {
  return value === null ? 0 : Number.parseFloat(value)
}

/**
 * The module's stable error codes, mapped to what to say about them.
 * Same reasoning as the inventory's: the API's `message` is English.
 */
const CODE_MESSAGES: Record<string, string> = {
  'purchasing.supplier.name_taken': 'purchasing.errors.supplierNameTaken',
  'purchasing.supplier.has_open_orders': 'purchasing.errors.supplierHasOpenOrders',
  'purchasing.supplier.not_found': 'purchasing.errors.supplierNotFound',
  'purchasing.order.not_found': 'purchasing.errors.orderNotFound',
  'purchasing.order.not_draft': 'purchasing.errors.orderNotDraft',
  'purchasing.order.not_receivable': 'purchasing.errors.orderNotReceivable',
  'purchasing.order.already_closed': 'purchasing.errors.orderAlreadyClosed',
  'purchasing.receipt.exceeds_pending': 'purchasing.errors.exceedsPending',
  'purchasing.receipt.lot_required': 'purchasing.errors.lotRequired',
  'purchasing.item.unknown': 'purchasing.errors.itemUnknown'
}

/** Resolve at setup, never inside a handler: it reaches `useI18n`. */
export function usePurchasingErrors() {
  const { t, te } = useI18n()

  return function message(error: unknown, fallback: string): string {
    const code = (error as { data?: { code?: string } })?.data?.code
    const key = code ? CODE_MESSAGES[code] : undefined
    return key && te(key) ? t(key) : errorMessage(error, fallback)
  }
}

export function usePurchasing() {
  const api = useApi()

  function query(filters: Record<string, unknown>): string {
    const qs = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null || value === '' || value === false) continue
      qs.append(key, String(value))
    }
    return qs.toString() ? `?${qs.toString()}` : ''
  }

  async function suppliers(status?: 'active' | 'archived'): Promise<ApiOk<Supplier[]>> {
    return await api.get<ApiOk<Supplier[]>>(`${BASE}/suppliers${query({ status })}`)
  }

  async function createSupplier(payload: SupplierInput): Promise<ApiOk<Supplier>> {
    return await api.post<ApiOk<Supplier>>(`${BASE}/suppliers`, payload)
  }

  async function updateSupplier(
    id: string,
    payload: Partial<SupplierInput> & { status?: 'active' | 'archived' }
  ): Promise<ApiOk<Supplier>> {
    return await api.put<ApiOk<Supplier>>(`${BASE}/suppliers/${id}`, payload)
  }

  async function archiveSupplier(id: string): Promise<void> {
    await api.del(`${BASE}/suppliers/${id}`)
  }

  async function orders(
    filters: { status?: OrderStatus, supplier_id?: string, open_only?: boolean } = {}
  ): Promise<ApiOk<PurchaseOrder[]>> {
    return await api.get<ApiOk<PurchaseOrder[]>>(`${BASE}/orders${query(filters)}`)
  }

  async function order(id: string): Promise<ApiOk<PurchaseOrder>> {
    return await api.get<ApiOk<PurchaseOrder>>(`${BASE}/orders/${id}`)
  }

  async function createOrder(payload: OrderInput): Promise<ApiOk<PurchaseOrder>> {
    return await api.post<ApiOk<PurchaseOrder>>(`${BASE}/orders`, payload)
  }

  async function sendOrder(id: string): Promise<ApiOk<PurchaseOrder>> {
    return await api.post<ApiOk<PurchaseOrder>>(`${BASE}/orders/${id}/send`, {})
  }

  async function cancelOrder(id: string): Promise<ApiOk<PurchaseOrder>> {
    return await api.post<ApiOk<PurchaseOrder>>(`${BASE}/orders/${id}/cancel`, {})
  }

  async function receiveOrder(
    id: string,
    payload: { lines: ReceiptLineInput[], note?: string | null }
  ): Promise<ApiOk<ReceiptResult>> {
    return await api.post<ApiOk<ReceiptResult>>(`${BASE}/orders/${id}/receive`, payload)
  }

  return {
    suppliers,
    createSupplier,
    updateSupplier,
    archiveSupplier,
    orders,
    order,
    createOrder,
    sendOrder,
    cancelOrder,
    receiveOrder
  }
}
