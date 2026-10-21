/**
 * The box chart: each tooth a square of five surfaces, as on the paper
 * odontogram forms, in the NOM-013 colours (`nomColors.ts`): red caries and
 * work to do, blue work done, green incipient caries and provisional work,
 * yellow sealants; a vertical line for endodontics, an X for a tooth absent
 * (blue) or to extract (red).
 *
 * Rows follow the form: permanent teeth outside, primary teeth inside. A
 * mixed dentition shows all four rows and dims the teeth not in the mouth
 * (the anatomical chart shows one tooth per position instead).
 *
 * The square is drawn as seen from the front of the patient: the patient's
 * right on the chart's left. Upper teeth have their vestibular face on top,
 * lower teeth at the bottom; the mesial face looks to the midline.
 */
import type { Surface, ToothTreatmentView } from '~~/app/types'
import { dimmedTeeth, teethLayout, type ChartFacts, type ShownDentition } from './dentitionLayout'
import { nomTone, type NomTone } from './nomColors'

/** One half-row: the teeth on each side of the midline, in chart order. */
export interface BoxRow {
  key: 'upperPermanent' | 'upperPrimary' | 'lowerPrimary' | 'lowerPermanent'
  right: number[]
  left: number[]
  /** Which side of the box the code cell sits on. */
  upper: boolean
}

const ROWS: BoxRow[] = [
  { key: 'upperPermanent', right: [18, 17, 16, 15, 14, 13, 12, 11], left: [21, 22, 23, 24, 25, 26, 27, 28], upper: true },
  { key: 'upperPrimary', right: [55, 54, 53, 52, 51], left: [61, 62, 63, 64, 65], upper: true },
  { key: 'lowerPrimary', right: [85, 84, 83, 82, 81], left: [71, 72, 73, 74, 75], upper: false },
  { key: 'lowerPermanent', right: [48, 47, 46, 45, 44, 43, 42, 41], left: [31, 32, 33, 34, 35, 36, 37, 38], upper: false }
]

/** The rows a dentition draws. */
export function boxRows(dentition: ShownDentition): BoxRow[] {
  if (dentition === 'permanent') return ROWS.filter(r => r.key.endsWith('Permanent'))
  if (dentition === 'deciduous') return ROWS.filter(r => r.key.endsWith('Primary'))
  return ROWS
}

/**
 * Teeth the box chart dims: those the anatomical chart dims, and — in a
 * mixed dentition, where every row is drawn — the teeth not in the mouth
 * (the ones the anatomical chart leaves out).
 */
export function boxDimmedTeeth(dentition: ShownDentition, facts: ChartFacts): number[] {
  const dimmed = dimmedTeeth(dentition, facts)
  if (dentition !== 'mixed') return dimmed
  const shown = new Set(Object.values(teethLayout('mixed', facts)).flat())
  for (const row of ROWS) {
    for (const tooth of [...row.right, ...row.left]) {
      if (!shown.has(tooth)) dimmed.push(tooth)
    }
  }
  return dimmed
}

export type BoxSide = 'top' | 'bottom' | 'left' | 'right' | 'center'

/** The surface each side of a tooth's square stands for. */
export function surfaceAt(tooth: number, side: BoxSide): Surface {
  if (side === 'center') return 'O'
  const quadrant = Math.floor(tooth / 10)
  const upper = [1, 2, 5, 6].includes(quadrant)
  // Patient's right (quadrants 1, 4, 5, 8) is on the chart's left, so the
  // midline — the mesial face — is to its right.
  const onChartLeft = [1, 4, 5, 8].includes(quadrant)
  if (side === 'top') return upper ? 'V' : 'L'
  if (side === 'bottom') return upper ? 'L' : 'V'
  if (side === 'right') return onChartLeft ? 'M' : 'D'
  return onChartLeft ? 'D' : 'M'
}

/** A colour on the square, after the NOM-013 convention (`nomColors.ts`). */
export type Paint = NomTone

export interface ToothBoxState {
  surfaces: Partial<Record<Surface, Paint>>
  /** An X over the square: the tooth is gone (blue) or to be extracted (red). */
  cross: Paint | null
  /** A ring round the square: a crown — done, planned or provisional. */
  ring: Paint | null
  /** A vertical line through the tooth: endodontics, done or planned. */
  rootLine: Paint | null
  /** Whole-tooth work written as a code above or below the square. */
  codes: Array<{ type: string, tone: Paint }>
}

const CARIES = new Set(['caries', 'incipient_caries'])
const GONE = new Set(['missing', 'extraction'])
const RING = new Set(['crown', 'crown_on_implant', 'provisional_crown_on_implant'])
const ENDODONTICS = new Set(['root_canal_full', 'root_canal_two_thirds', 'root_canal_half', 'root_canal_overfill'])

function empty(): ToothBoxState {
  return { surfaces: {}, cross: null, ring: null, rootLine: null, codes: [] }
}

/**
 * The tooth record's whole-tooth condition, drawn first: what is charted on
 * the tooth is drawn over it.
 */
const CONDITION_MARKS: Record<string, (state: ToothBoxState) => void> = {
  caries: (state) => {
    state.surfaces.O = 'red'
  },
  filling: (state) => {
    state.surfaces.O = 'blue'
  },
  sealant: (state) => {
    state.surfaces.O = 'yellow'
  },
  crown: (state) => {
    state.ring = 'blue'
  },
  missing: (state) => {
    state.cross = 'blue'
  },
  extraction_indicated: (state) => {
    state.cross = 'red'
  },
  root_canal: (state) => {
    state.rootLine = 'blue'
  },
  implant: (state) => {
    state.codes.push({ type: 'implant', tone: 'blue' })
  },
  fracture: (state) => {
    state.codes.push({ type: 'fracture', tone: 'red' })
  }
}

function conditionState(condition: string | null | undefined): ToothBoxState {
  const state = empty()
  if (condition) CONDITION_MARKS[condition]?.(state)
  return state
}

/**
 * What to draw on a tooth's square, in the norm's colours: red caries and
 * work to do, blue work done, green incipient caries and provisional work,
 * yellow sealants. On a surface the later mark wins, so a caries restored
 * afterwards shows the restoration.
 */
export function toothBoxState(
  views: ToothTreatmentView[],
  condition?: string | null
): ToothBoxState {
  const state = conditionState(condition)
  const ordered = [...views].sort((a, b) =>
    (a.performed_at ?? a.recorded_at).localeCompare(b.performed_at ?? b.recorded_at)
  )
  for (const view of ordered) {
    const type = view.clinical_type
    const tone = nomTone(type, view.status)
    if (view.surfaces?.length) {
      for (const surface of view.surfaces) state.surfaces[surface] = tone
      continue
    }
    if (GONE.has(type) || (type === 'bridge' && view.role === 'pontic')) {
      // Absent is blue, to extract red — and a planned extraction never
      // hides that the tooth is already gone.
      if (state.cross !== 'blue') state.cross = view.status === 'planned' ? 'red' : 'blue'
      continue
    }
    if (RING.has(type)) {
      state.ring = tone
      if (type !== 'crown') state.codes.push({ type, tone })
      continue
    }
    if (ENDODONTICS.has(type)) {
      state.rootLine = tone
      continue
    }
    if (CARIES.has(type)) {
      // A whole-tooth caries: the crown of the box.
      state.surfaces.O = tone
      continue
    }
    state.codes.push({ type, tone })
  }
  return state
}
