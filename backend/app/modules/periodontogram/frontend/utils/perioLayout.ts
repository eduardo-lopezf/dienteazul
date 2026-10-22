/**
 * How the chart is laid out for the width it has.
 *
 * A whole arch is 96 px of row labels + 16 teeth × 60 px, plus its border.
 * Where that does not fit — a tablet, upright or on its side — each arch is
 * drawn as its two quadrants, one under the other: 8 teeth, the same cells
 * at the same size. Narrower still (the sidebar open on an upright tablet)
 * a quadrant is shrunk to fit, down to 75 %; past that it scrolls.
 */
export const FULL_ARCH_PX = 1060
export const QUADRANT_PX = 578
export const MIN_ZOOM = 0.75

export interface PerioLayout {
  split: boolean
  zoom: number
}

export function perioLayout(width: number): PerioLayout {
  // Not measured yet (server render, first frame): the whole chart.
  if (width <= 0 || width >= FULL_ARCH_PX) return { split: false, zoom: 1 }
  if (width >= QUADRANT_PX) return { split: true, zoom: 1 }
  return { split: true, zoom: Math.max(MIN_ZOOM, Math.floor((width / QUADRANT_PX) * 100) / 100) }
}
