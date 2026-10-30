/**
 * Orchestrator for /reports dashboard.
 *
 * Single composable surface for the index page. Owns:
 *   - the shared date-range filter ref (``useReportPeriod``),
 *   - per-card { loading, error, data } state,
 *   - parallel fan-out over reports + payments endpoints,
 *   - delta computation by re-fetching the previous equal-length range,
 *   - AbortController cancellation on filter change or unmount.
 *
 * Permission gating: callers pre-checked with usePermissions() should
 * still call refresh(); endpoints we lack permission for return null/[]
 * gracefully (useApi 403s are caught silently here).
 */
import type { ReportPeriod } from '~/composables/useReportPeriod'
import { useReports } from './useReports'
import type {
  AppointmentFunnel,
  FirstVisitsSummary,
  PaymentsAgingBuckets,
  PaymentsMethodBreakdown,
  PaymentsProfessionalBreakdown,
  PaymentsSummaryReport,
  PaymentsTrends
} from './useReports'

/** The shared Productividad range (``useReportPeriod``). */
export type DashboardRange = ReportPeriod

interface CardState<T> {
  loading: boolean
  error: boolean
  data: T | null
}

interface RangeCard<T> extends CardState<T> {
  /** Percentage change vs the previous equal-length range. */
  delta: number | null
  /** Source series for the small sparkline (raw numbers, oldest → newest). */
  spark: number[]
}

export interface DashboardState {
  // Range-scoped cards
  paymentsCurrent: RangeCard<PaymentsSummaryReport>
  paymentsTrends: CardState<PaymentsTrends>
  methods: CardState<PaymentsMethodBreakdown[]>
  production: CardState<PaymentsProfessionalBreakdown[]>
  newPatients: RangeCard<FirstVisitsSummary>
  funnel: RangeCard<AppointmentFunnel>
  // Point-in-time
  aging: CardState<PaymentsAgingBuckets>
}

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** Previous range of the same length, ending the day before `from`. */
function previousRange(range: DashboardRange): DashboardRange {
  const from = new Date(`${range.from}T00:00:00`)
  const to = new Date(`${range.to}T00:00:00`)
  const days = Math.max(1, Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1)
  const prevTo = new Date(from)
  prevTo.setDate(prevTo.getDate() - 1)
  const prevFrom = new Date(prevTo)
  prevFrom.setDate(prevFrom.getDate() - (days - 1))
  return { from: toIso(prevFrom), to: toIso(prevTo) }
}

function pct(curr: number, prev: number): number | null {
  if (!Number.isFinite(curr) || !Number.isFinite(prev)) return null
  if (prev === 0) return curr === 0 ? 0 : null
  return ((curr - prev) / Math.abs(prev)) * 100
}

function num(value: string | number | null | undefined): number {
  if (value == null) return 0
  const n = typeof value === 'string' ? parseFloat(value) : value
  return Number.isFinite(n) ? n : 0
}

export function useDashboardSnapshot() {
  const reports = useReports()
  const { can } = usePermissions()
  const { on } = useReportApps()

  // One range for the whole section: the detail screens read and write
  // the same state, so a drill-down keeps the period.
  const { period: filters } = useReportPeriod()

  function makeRangeCard<T>(): RangeCard<T> {
    return { loading: true, error: false, data: null, delta: null, spark: [] }
  }
  function makeCard<T>(): CardState<T> {
    return { loading: true, error: false, data: null }
  }

  const state = reactive<DashboardState>({
    paymentsCurrent: makeRangeCard<PaymentsSummaryReport>(),
    paymentsTrends: makeCard<PaymentsTrends>(),
    methods: makeCard<PaymentsMethodBreakdown[]>(),
    production: makeCard<PaymentsProfessionalBreakdown[]>(),
    newPatients: makeRangeCard<FirstVisitsSummary>(),
    funnel: makeRangeCard<AppointmentFunnel>(),
    aging: makeCard<PaymentsAgingBuckets>()
  })

  let controller: AbortController | null = null

  function markStart() {
    for (const key of Object.keys(state) as (keyof DashboardState)[]) {
      state[key].loading = true
      state[key].error = false
    }
  }

  async function refresh() {
    if (controller) controller.abort()
    controller = new AbortController()
    const signal = controller.signal

    markStart()

    const range = filters.value
    const prev = previousRange(range)
    // A section reads only while its App runs (ADR 0037).
    const canPayments = can('payments.reports.read') && on('payments')
    const canScheduling = can('reports.scheduling.read') && on('agenda')

    const tasks: Promise<unknown>[] = []

    // -- Payments summary (current + previous for delta) -------------------
    if (canPayments) {
      tasks.push(
        Promise.all([
          reports.fetchPaymentsSummary(range.from, range.to, { signal }),
          reports.fetchPaymentsSummary(prev.from, prev.to, { signal })
        ]).then(([curr, prevSummary]) => {
          if (signal.aborted) return
          state.paymentsCurrent.loading = false
          state.paymentsCurrent.data = curr
          if (!curr) state.paymentsCurrent.error = true
          if (curr && prevSummary) {
            state.paymentsCurrent.delta = pct(
              num(curr.net_collected),
              num(prevSummary.net_collected)
            )
          }
        })
      )

      // Trends drive the cash collected sparkline + the area chart.
      tasks.push(
        Promise.all([
          reports.fetchPaymentsTrends(range.from, range.to, 'day', { signal }),
          reports.fetchPaymentsTrends(prev.from, prev.to, 'day', { signal })
        ]).then(([curr]) => {
          if (signal.aborted) return
          state.paymentsTrends.loading = false
          state.paymentsTrends.data = curr
          if (!curr) state.paymentsTrends.error = true
          if (curr) {
            state.paymentsCurrent.spark = curr.points.map(p => num(p.collected))
          }
        })
      )

      tasks.push(
        reports.fetchPaymentsByMethod(range.from, range.to, { signal }).then((rows) => {
          if (signal.aborted) return
          state.methods.loading = false
          state.methods.data = rows
        })
      )

      tasks.push(
        reports.fetchPaymentsByProfessional(range.from, range.to, { signal }).then((rows) => {
          if (signal.aborted) return
          state.production.loading = false
          state.production.data = rows
        })
      )
    } else {
      state.paymentsCurrent.loading = false
      state.paymentsTrends.loading = false
      state.methods.loading = false
      state.production.loading = false
    }

    // -- Scheduling KPIs ---------------------------------------------------
    if (canScheduling) {
      tasks.push(
        Promise.all([
          reports.fetchFirstVisits(range.from, range.to),
          reports.fetchFirstVisits(prev.from, prev.to)
        ]).then(([curr, prevFv]) => {
          if (signal.aborted) return
          state.newPatients.loading = false
          state.newPatients.data = curr
          if (!curr) state.newPatients.error = true
          if (curr && prevFv) {
            state.newPatients.delta = pct(curr.new_patients, prevFv.new_patients)
          }
        })
      )

      tasks.push(
        Promise.all([
          reports.fetchFunnel(range.from, range.to),
          reports.fetchFunnel(prev.from, prev.to)
        ]).then(([curr, prevFn]) => {
          if (signal.aborted) return
          state.funnel.loading = false
          state.funnel.data = curr
          if (!curr) state.funnel.error = true
          if (curr && prevFn && curr.no_show_rate != null && prevFn.no_show_rate != null) {
            // no_show_rate is already a percentage 0..100. Use relative change so
            // the badge reads consistent with the other tiles.
            state.funnel.delta = pct(curr.no_show_rate, prevFn.no_show_rate)
          }
        })
      )
    } else {
      state.newPatients.loading = false
      state.funnel.loading = false
    }

    // -- Snapshots (point-in-time) ----------------------------------------
    if (canPayments) {
      tasks.push(
        reports.fetchAgingReceivables({ signal }).then((data) => {
          if (signal.aborted) return
          state.aging.loading = false
          state.aging.data = data
          if (!data) state.aging.error = true
        })
      )
    } else {
      state.aging.loading = false
    }

    await Promise.allSettled(tasks)
  }

  /**
   * True once everything has answered and the range holds nothing the
   * user can see. Snapshot cards (patient credit, receivables) are left
   * out on purpose: they describe today, not the range, so a clinic with
   * old debt and a quiet month is still an empty period.
   */
  const periodIsEmpty = computed(() => {
    const cards = Object.values(state) as { loading: boolean }[]
    if (cards.some(card => card.loading)) return false

    const canPayments = can('payments.reports.read') && on('payments')
    const canScheduling = can('reports.scheduling.read') && on('agenda')
    if (!canPayments && !canScheduling) return false

    const paymentsEmpty
      = !canPayments
        || ((state.paymentsCurrent.data?.payment_count ?? 0) === 0
          && (state.production.data?.length ?? 0) === 0)
    const schedulingEmpty
      = !canScheduling
        || ((state.newPatients.data?.total_appointments ?? 0) === 0
          && num(state.funnel.data?.total) === 0)

    return paymentsEmpty && schedulingEmpty
  })

  onMounted(() => {
    void refresh()
  })

  watch(
    filters,
    () => {
      void refresh()
    },
    { deep: true }
  )

  onBeforeUnmount(() => {
    if (controller) controller.abort()
  })

  return { filters, state, periodIsEmpty, refresh, previousRange }
}
