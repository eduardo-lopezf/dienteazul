/**
 * Colour of a site marker by probing depth, after the SEPA chart: up to
 * 3 mm is health (green), over 3 mm is a pathological pocket (red) — the
 * same threshold that writes the depth in red in the metric table
 * (`utils/perioConvention.ts`, docs/technical/periodontogram/color-convention.md).
 * Unmeasured sites stay neutral. Frontend-only — the backend never cares
 * about colours, and the deep-pocket index keeps its own 5 mm threshold.
 */
import { isPathologicalDepth } from '../utils/perioConvention'

export type HeatmapTone = 'neutral' | 'healthy' | 'pathological'

// Calm-design pastel mapping (soft fill + accent ring + dark readable text):
// a marker signals the bucket without shouting over the chart.
const TONE_TO_CLASS: Record<HeatmapTone, string> = {
  neutral: 'bg-gray-100 ring-gray-300 text-gray-500 dark:bg-gray-700/70 dark:ring-gray-500 dark:text-gray-300',
  healthy: 'bg-emerald-50 ring-emerald-400 text-emerald-700 dark:bg-emerald-900/50 dark:ring-emerald-500 dark:text-emerald-200',
  pathological: 'bg-red-50 ring-red-500 text-red-700 dark:bg-red-900/50 dark:ring-red-500 dark:text-red-200'
}

const TONE_TO_HEX: Record<HeatmapTone, string> = {
  neutral: '#d1d5db', // gray-300
  healthy: '#34d399', // emerald-400
  pathological: '#ef4444' // red-500
}

export function probingDepthTone(pd: number | null | undefined): HeatmapTone {
  if (pd === null || pd === undefined) return 'neutral'
  return isPathologicalDepth(pd) ? 'pathological' : 'healthy'
}

export function probingDepthClasses(pd: number | null | undefined): string {
  return TONE_TO_CLASS[probingDepthTone(pd)]
}

export function probingDepthHex(pd: number | null | undefined): string {
  return TONE_TO_HEX[probingDepthTone(pd)]
}
