/**
 * Caries indices from what is charted: CPO-D (permanent teeth: cariados,
 * perdidos, obturados) and ceo-d (primary teeth: cariados, extracción
 * indicada, obturados). Each tooth counts once, under one letter.
 *
 * Only what is in the mouth counts — work done or found (`existing`); a
 * planned treatment is an intention, except a planned extraction of a primary
 * tooth, which is exactly the "e". The chart does not record *why* a tooth
 * was lost or crowned, so the usual survey reading applies:
 *
 * Permanent tooth (11–48), first that applies:
 * - not counted when it is not there by nature: unerupted, impacted, absent
 *   from birth (eruption status, or an `unerupted` finding);
 * - **P**: missing, extracted, replaced by an implant, or a bridge pontic;
 * - **C**: the tooth record says caries, or a caries lesion or a temporary
 *   filling is charted and no restoration was recorded on the tooth after it
 *   (the caries finding stays on the chart once treated);
 * - **O**: a filling, inlay, overlay, crown or root canal treatment.
 *   Veneers, sealants and bridge abutments are not counted: they are not
 *   the trace of caries.
 *
 * Primary tooth (51–85): exfoliated, unerupted or absent from birth are not
 * counted; a lost primary tooth is not counted either (exfoliation and
 * extraction cannot be told apart); **e** is an extraction indicated
 * (planned, or the tooth condition); then **c** and **o** as above.
 */
import type { Treatment } from '~~/app/types'
import type { EruptionStatus } from './dentitionLayout'

// Type aliases, not interfaces, and that is the whole reason: both are
// handed to `t('odontogram.indices.cpodParts', cpod)` as the message's
// named values, and `t` wants a `Record<string, unknown>`. TypeScript
// gives an object type alias an implicit index signature and an
// interface none, so as interfaces these matched no overload of `t`
// (TS2769, four call sites between the chart and the printed sheet).
export type Cpod = {
  decayed: number
  missing: number
  filled: number
  total: number
}

export type Ceod = {
  decayed: number
  extraction: number
  filled: number
  total: number
}

export interface IndexFacts {
  /** Treatments on the chart as shown (the history view's when in the past). */
  treatments: Treatment[]
  /** The tooth's whole-tooth condition, from its record. */
  conditionOf?: (tooth: number) => string | null | undefined
  statusOf?: (tooth: number) => EruptionStatus | null | undefined
}

const CARIES = new Set(['caries', 'filling_temporary'])
const RESTORATION = new Set([
  'filling_composite',
  'filling_amalgam',
  'inlay',
  'overlay',
  'crown',
  'root_canal_full',
  'root_canal_two_thirds',
  'root_canal_half',
  'root_canal_overfill',
  'post'
])
const LOST = new Set(['missing', 'extraction', 'implant', 'crown_on_implant', 'provisional_crown_on_implant'])
const NOT_THERE_BY_NATURE: ReadonlySet<EruptionStatus> = new Set([
  'unerupted',
  'impacted',
  'congenitally_missing'
])

type Letter = 'decayed' | 'lost' | 'extraction' | 'filled' | null

interface Mark {
  type: string
  planned: boolean
  role: string | null
  at: string
}

function marksByTooth(treatments: Treatment[]): Map<number, Mark[]> {
  const out = new Map<number, Mark[]>()
  for (const treatment of treatments) {
    for (const member of treatment.teeth ?? []) {
      const marks = out.get(member.tooth_number) ?? []
      marks.push({
        type: treatment.clinical_type,
        planned: treatment.status === 'planned',
        role: member.role ?? null,
        at: treatment.performed_at ?? treatment.recorded_at ?? treatment.created_at
      })
      out.set(member.tooth_number, marks)
    }
  }
  return out
}

/**
 * Decayed or filled: a caries counts unless restored after it. The tooth
 * record's condition is the clinician's word on the tooth as it is now, so
 * `caries` there wins over any treatment.
 */
function decayedOrFilled(done: Mark[], condition: string | null | undefined): Letter {
  if (condition === 'caries') return 'decayed'
  const latest = (types: Set<string>) =>
    done.filter(m => types.has(m.type)).map(m => m.at).sort().at(-1)
  const caries = latest(CARIES)
  const restored = latest(RESTORATION)
  if (caries && (!restored || restored < caries)) return 'decayed'
  if (restored) return 'filled'
  if (condition === 'filling' || condition === 'crown' || condition === 'root_canal') return 'filled'
  return null
}

function permanentLetter(marks: Mark[], condition: string | null | undefined): Letter {
  const done = marks.filter(m => !m.planned)
  if (done.some(m => LOST.has(m.type) || (m.type === 'bridge' && m.role === 'pontic'))) return 'lost'
  if (condition === 'missing' || condition === 'implant') return 'lost'
  return decayedOrFilled(done, condition)
}

function primaryLetter(marks: Mark[], condition: string | null | undefined): Letter {
  const done = marks.filter(m => !m.planned)
  if (done.some(m => LOST.has(m.type)) || condition === 'missing') return null
  if (marks.some(m => m.planned && m.type === 'extraction') || condition === 'extraction_indicated') {
    return 'extraction'
  }
  return decayedOrFilled(done, condition)
}

/** CPO-D and ceo-d of the chart. */
export function dentalIndices(facts: IndexFacts): { cpod: Cpod, ceod: Ceod } {
  const cpod: Cpod = { decayed: 0, missing: 0, filled: 0, total: 0 }
  const ceod: Ceod = { decayed: 0, extraction: 0, filled: 0, total: 0 }
  const marks = marksByTooth(facts.treatments)
  const teeth = new Set<number>(marks.keys())
  // A whole-tooth condition can be on a record with no treatment behind it.
  for (const quadrant of [1, 2, 3, 4, 5, 6, 7, 8]) {
    for (let position = 1; position <= (quadrant >= 5 ? 5 : 8); position++) {
      const tooth = quadrant * 10 + position
      const condition = facts.conditionOf?.(tooth)
      if (condition && condition !== 'healthy') teeth.add(tooth)
    }
  }

  for (const tooth of teeth) {
    const toothMarks = marks.get(tooth) ?? []
    const status = facts.statusOf?.(tooth) ?? null
    const condition = facts.conditionOf?.(tooth)
    const primary = Math.floor(tooth / 10) >= 5
    if (status && NOT_THERE_BY_NATURE.has(status)) continue
    if (primary) {
      if (status === 'exfoliated') continue
      const letter = primaryLetter(toothMarks, condition)
      if (letter === 'decayed') ceod.decayed++
      else if (letter === 'extraction') ceod.extraction++
      else if (letter === 'filled') ceod.filled++
    } else {
      if (toothMarks.some(m => !m.planned && m.type === 'unerupted')) continue
      const letter = permanentLetter(toothMarks, condition)
      if (letter === 'decayed') cpod.decayed++
      else if (letter === 'lost') cpod.missing++
      else if (letter === 'filled') cpod.filled++
    }
  }
  cpod.total = cpod.decayed + cpod.missing + cpod.filled
  ceod.total = ceod.decayed + ceod.extraction + ceod.filled
  return { cpod, ceod }
}
