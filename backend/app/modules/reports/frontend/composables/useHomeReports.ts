import type { OverdueInvoice } from '~~/app/types'
import { sampleOverdueInvoices } from '../utils/previewSamples'

/**
 * Shared state for reports widgets on the home dashboard. Overdue
 * invoices are fetched once and reused by the hero tile and the
 * attention panel.
 */
export function useHomeReports() {
  // Inside a widget example (Settings → Widgets) the list is made up,
  // nothing is fetched and the shared state is left alone (ADR 0040).
  if (useWidgetPreview()) {
    const sample = sampleOverdueInvoices()
    return {
      overdue: readonly(ref(sample)),
      overdueLoaded: readonly(ref(true)),
      loadOverdue: async () => sample
    }
  }

  const { fetchOverdueInvoices } = useReports()

  const overdue = useState<OverdueInvoice[]>('reports.home:overdue', () => [])
  const overdueLoaded = useState<boolean>('reports.home:overdue-loaded', () => false)

  async function loadOverdue(): Promise<OverdueInvoice[]> {
    overdue.value = await fetchOverdueInvoices()
    overdueLoaded.value = true
    return overdue.value
  }

  return {
    overdue: readonly(overdue),
    overdueLoaded: readonly(overdueLoaded),
    loadOverdue
  }
}
