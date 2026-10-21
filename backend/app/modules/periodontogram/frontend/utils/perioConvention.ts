/**
 * SEPA charting convention (docs/technical/periodontogram/color-convention.md):
 * a probing depth over 3 mm and a band of keratinized gingiva of 2 mm or
 * less are written in red. Display only — the deep-pocket index keeps its
 * own threshold (`DEEP_POCKET_THRESHOLD_MM`, 5 mm).
 */
export const PATHOLOGICAL_DEPTH_OVER_MM = 3
export const NARROW_KERATINIZED_GINGIVA_MM = 2

export function isPathologicalDepth(mm: number | null | undefined): boolean {
  return mm != null && mm > PATHOLOGICAL_DEPTH_OVER_MM
}

export function isNarrowKeratinizedGingiva(mm: number | null | undefined): boolean {
  return mm != null && mm <= NARROW_KERATINIZED_GINGIVA_MM
}
