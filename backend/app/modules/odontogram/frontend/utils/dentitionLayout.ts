/**
 * Which teeth a patient's chart shows, by dentition — and what to warn about.
 *
 * - `deciduous`: the 20 primary teeth (51–85).
 * - `mixed`: one tooth per position, the one in the mouth. What the clinician
 *   charted decides first (the tooth's eruption status, or anything charted
 *   on it); with nothing said, the eruption chronology does: the permanent
 *   successor once its age comes, otherwise the primary tooth it replaces.
 *   Molars 6 and 7 have no predecessor and appear on the same terms.
 * - `permanent`: the 32 permanent teeth; third molars dimmed under
 *   `THIRD_MOLARS_FROM_AGE`, unless something is charted on them.
 *
 * Teeth whose status says they are not in the mouth (unerupted, impacted,
 * congenitally missing, exfoliated) are drawn dimmed, whatever the view.
 *
 * Age only *suggests* — the server returns `suggested_dentition` and the
 * clinician may pick another for the patient. The chronology is the clinic's
 * (`eruption_ages` on the chart), the usual one by default.
 */

export type Dentition = 'auto' | 'deciduous' | 'mixed' | 'permanent'
export type ShownDentition = Exclude<Dentition, 'auto'>
export type EruptionStatus
  = | 'unerupted'
    | 'erupting'
    | 'erupted'
    | 'exfoliated'
    | 'congenitally_missing'
    | 'impacted'
/** The teeth a catalog treatment can be done on (catalog `dentition`). */
export type TreatmentDentition = 'both' | 'deciduous' | 'permanent'
/** Arch → position (1–8, as a string key) → usual eruption age. */
export type EruptionAges = Record<'upper' | 'lower', Record<string, number>>

export interface TeethLayout {
  upperRight: number[]
  upperLeft: number[]
  lowerRight: number[]
  lowerLeft: number[]
}

/** What the chart knows about the patient's teeth. */
export interface ChartFacts {
  age: number | null
  /** Something is charted on the tooth (a treatment, a condition). */
  charted?: (tooth: number) => boolean
  /** The tooth's eruption status, when the clinician said it. */
  statusOf?: (tooth: number) => EruptionStatus | null | undefined
  /** The clinic's chronology; the usual one when absent. */
  ages?: EruptionAges
}

/** Mirrors `THIRD_MOLARS_FROM_AGE` in `odontogram/constants.py`. */
export const THIRD_MOLARS_FROM_AGE = 18
/** Mirrors `ERUPTION_TOLERANCE_YEARS`. */
export const ERUPTION_TOLERANCE_YEARS = 2

/** Mirrors `DEFAULT_ERUPTION_AGES`. */
export const DEFAULT_ERUPTION_AGES: EruptionAges = {
  upper: { 1: 7, 2: 8, 3: 11, 4: 10, 5: 10, 6: 6, 7: 12, 8: 17 },
  lower: { 1: 6, 2: 7, 3: 9, 4: 10, 5: 11, 6: 6, 7: 11, 8: 17 }
}

/** Statuses that say the tooth is in the mouth. */
const IN_MOUTH: ReadonlySet<EruptionStatus> = new Set(['erupting', 'erupted'])
/** Statuses that say it is not. */
const NOT_IN_MOUTH: ReadonlySet<EruptionStatus> = new Set([
  'unerupted',
  'impacted',
  'congenitally_missing',
  'exfoliated'
])

const PERMANENT: TeethLayout = {
  upperRight: [18, 17, 16, 15, 14, 13, 12, 11],
  upperLeft: [21, 22, 23, 24, 25, 26, 27, 28],
  lowerRight: [48, 47, 46, 45, 44, 43, 42, 41],
  lowerLeft: [31, 32, 33, 34, 35, 36, 37, 38]
}

const DECIDUOUS: TeethLayout = {
  upperRight: [55, 54, 53, 52, 51],
  upperLeft: [61, 62, 63, 64, 65],
  lowerRight: [85, 84, 83, 82, 81],
  lowerLeft: [71, 72, 73, 74, 75]
}

const nothing = () => false
const unsaid = () => null

/** The dentition to draw: the clinician's choice, else what the age says. */
export function shownDentition(chosen: Dentition, suggested: ShownDentition): ShownDentition {
  return chosen === 'auto' ? suggested : chosen
}

/** Usual age a permanent tooth erupts, by the clinic's chronology. */
export function eruptionAge(tooth: number, ages: EruptionAges = DEFAULT_ERUPTION_AGES): number | undefined {
  const arch = Math.floor(tooth / 10) <= 2 ? 'upper' : 'lower'
  return ages[arch][String(tooth % 10)]
}

/** Whether a permanent tooth is expected in the mouth at `age`. */
export function hasErupted(
  tooth: number,
  age: number | null,
  ages: EruptionAges = DEFAULT_ERUPTION_AGES
): boolean {
  const usual = eruptionAge(tooth, ages)
  return age !== null && usual !== undefined && age >= usual
}

/** The primary tooth a permanent one replaces; `null` for molars 6–8. */
export function predecessorOf(tooth: number): number | null {
  const position = tooth % 10
  if (position > 5) return null
  return (Math.floor(tooth / 10) + 4) * 10 + position
}

/** The permanent tooth that replaces a primary one (54 → 14). */
export function successorOf(primary: number): number | null {
  const quadrant = Math.floor(primary / 10)
  if (quadrant < 5 || quadrant > 8 || primary % 10 > 5) return null
  return (quadrant - 4) * 10 + (primary % 10)
}

/** Whether the permanent tooth at this position is the one in the mouth. */
function permanentInMouth(tooth: number, facts: ChartFacts): boolean {
  const statusOf = facts.statusOf ?? unsaid
  const status = statusOf(tooth)
  if (status && IN_MOUTH.has(status)) return true
  if ((facts.charted ?? nothing)(tooth)) return true
  const predecessor = predecessorOf(tooth)
  const primaryStatus = predecessor === null ? null : statusOf(predecessor)
  if (primaryStatus === 'exfoliated') return true
  // The clinician said where each stands: the primary one stays.
  if (status && NOT_IN_MOUTH.has(status)) return false
  if (primaryStatus && IN_MOUTH.has(primaryStatus)) return false
  return hasErupted(tooth, facts.age, facts.ages)
}

function mixedQuadrant(permanent: number[], facts: ChartFacts): number[] {
  const out: number[] = []
  for (const tooth of permanent) {
    const position = tooth % 10
    if (position === 8) continue
    const predecessor = predecessorOf(tooth)
    if (permanentInMouth(tooth, facts)) {
      out.push(tooth)
    } else if (predecessor !== null) {
      out.push(predecessor)
    } else if ((facts.statusOf ?? unsaid)(tooth)) {
      // A molar the clinician charted as not there yet (or impacted, or
      // absent): drawn, dimmed, so the status can be read and changed.
      out.push(tooth)
    }
  }
  return out
}

/** The teeth to draw, quadrant by quadrant, in chart order. */
export function teethLayout(dentition: ShownDentition, facts: ChartFacts): TeethLayout {
  if (dentition === 'deciduous') return DECIDUOUS
  if (dentition === 'permanent') return PERMANENT
  return {
    upperRight: mixedQuadrant(PERMANENT.upperRight, facts),
    upperLeft: mixedQuadrant(PERMANENT.upperLeft, facts),
    lowerRight: mixedQuadrant(PERMANENT.lowerRight, facts),
    lowerLeft: mixedQuadrant(PERMANENT.lowerLeft, facts)
  }
}

/**
 * Teeth drawn dimmed: those whose status says they are not in the mouth, and
 * third molars not expected yet with nothing charted.
 */
export function dimmedTeeth(dentition: ShownDentition, facts: ChartFacts): number[] {
  const statusOf = facts.statusOf ?? unsaid
  const charted = facts.charted ?? nothing
  const shown = Object.values(teethLayout(dentition, facts)).flat()
  return shown.filter((tooth) => {
    const status = statusOf(tooth)
    if (status && NOT_IN_MOUTH.has(status)) return true
    if (status && IN_MOUTH.has(status)) return false
    return dentition === 'permanent'
      && tooth % 10 === 8
      && facts.age !== null
      && facts.age < THIRD_MOLARS_FROM_AGE
      && !charted(tooth)
  })
}

export interface EruptionAlert {
  kind: 'retained_primary' | 'delayed_eruption'
  tooth: number
  /** The successor, for a primary tooth kept too long. */
  successor?: number
  /** Usual eruption age of the tooth that is late. */
  usualAge: number
}

/**
 * What to warn about, from what is charted only — a chart with nothing said
 * about eruption warns of nothing:
 *
 * - a primary tooth charted as in the mouth (or with something charted on
 *   it) while its successor is `tolerance` years past its usual age and not
 *   in the mouth: possibly retained too long;
 * - a permanent tooth charted as not erupted (or impacted) `tolerance` years
 *   past its usual age: delayed eruption. Third molars are left out.
 */
export function eruptionAlerts(
  facts: ChartFacts,
  tolerance: number = ERUPTION_TOLERANCE_YEARS
): EruptionAlert[] {
  const age = facts.age
  if (age === null) return []
  const statusOf = facts.statusOf ?? unsaid
  const charted = facts.charted ?? nothing
  const alerts: EruptionAlert[] = []

  for (const primary of Object.values(DECIDUOUS).flat()) {
    const successor = successorOf(primary)!
    const usualAge = eruptionAge(successor, facts.ages)!
    const primaryStatus = statusOf(primary)
    const primaryThere = (primaryStatus && IN_MOUTH.has(primaryStatus))
      || (!primaryStatus && charted(primary))
    const successorStatus = statusOf(successor)
    if (
      primaryThere
      && age >= usualAge + tolerance
      && !(successorStatus && IN_MOUTH.has(successorStatus))
      && successorStatus !== 'congenitally_missing'
      && !charted(successor)
    ) {
      alerts.push({ kind: 'retained_primary', tooth: primary, successor, usualAge })
    }
  }

  for (const tooth of Object.values(PERMANENT).flat()) {
    if (tooth % 10 === 8) continue
    const status = statusOf(tooth)
    const usualAge = eruptionAge(tooth, facts.ages)!
    if ((status === 'unerupted' || status === 'impacted') && age >= usualAge + tolerance) {
      alerts.push({ kind: 'delayed_eruption', tooth, usualAge })
    }
  }
  return alerts
}

/** Whether a treatment of this dentition can be done on the tooth. */
export function fitsTooth(dentition: TreatmentDentition | undefined, tooth: number): boolean {
  if (!dentition || dentition === 'both') return true
  return (Math.floor(tooth / 10) >= 5) === (dentition === 'deciduous')
}

/**
 * Whether the treatment bar offers a treatment on a chart drawn in this
 * dentition: a mixed one has teeth of both, so it offers everything and the
 * tooth decides (`fitsTooth`).
 */
export function offeredOn(dentition: TreatmentDentition | undefined, shown: ShownDentition): boolean {
  if (!dentition || dentition === 'both' || shown === 'mixed') return true
  return dentition === shown
}
