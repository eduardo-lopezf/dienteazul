/**
 * useReportPeriod — the single period filter behind every Productividad screen.
 *
 * The range lives in one ``useState`` so a drill-down from the panel keeps
 * what the user chose instead of snapping back to "this month", and each
 * screen mirrors it into ``?from=&to=`` so a period stays bookmarkable.
 *
 * It is host state on purpose: `/reports/payments` belongs to the payments
 * module and shares the same control without either module importing the
 * other.
 */
export interface ReportPeriod {
  from: string
  to: string
}

/** FilterDateRange's shape — both ends optional while the popover is open. */
interface NullableRange {
  from: string | null
  to: string | null
}

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

/** Current month to date. */
export function defaultReportPeriod(): ReportPeriod {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const first = new Date(today.getFullYear(), today.getMonth(), 1)
  return { from: toIso(first), to: toIso(today) }
}

export function useReportPeriod() {
  const route = useRoute()
  const router = useRouter()

  const period = useState<ReportPeriod>('reports.period', () => {
    const qFrom = typeof route.query.from === 'string' ? route.query.from : null
    const qTo = typeof route.query.to === 'string' ? route.query.to : null
    if (qFrom && qTo) return { from: qFrom, to: qTo }
    return defaultReportPeriod()
  })

  // Every report needs both ends, so a cleared range falls back to the
  // default rather than letting nulls reach the endpoints.
  const model = computed<NullableRange>({
    get: () => ({ from: period.value.from, to: period.value.to }),
    set: (v) => {
      period.value = v.from && v.to ? { from: v.from, to: v.to } : defaultReportPeriod()
    }
  })

  function writeQuery(range: ReportPeriod) {
    void router.replace({ query: { ...route.query, from: range.from, to: range.to } })
  }

  /**
   * Keep this screen's URL in step with the shared range. Call once from
   * setup. A bookmarked link wins over the state left by a previous screen.
   */
  function syncQuery() {
    const qFrom = typeof route.query.from === 'string' ? route.query.from : null
    const qTo = typeof route.query.to === 'string' ? route.query.to : null
    if (qFrom && qTo && (qFrom !== period.value.from || qTo !== period.value.to)) {
      period.value = { from: qFrom, to: qTo }
    }

    // Written on the client only: a replace() during SSR setup would
    // resolve the route twice before anything renders.
    onMounted(() => writeQuery(period.value))
    watch(period, writeQuery, { deep: true })
  }

  return { period, model, syncQuery }
}
