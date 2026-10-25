/**
 * What the tooth card (`ToothDiagnosisModal`) offers when a tooth is clicked
 * with nothing armed: the findings a diagnosis charts, each a switch, applied
 * to every tooth picked on the card's chart.
 *
 * Most are diagnostic treatments (`clinical_type`, no catalog item) charted
 * as existing, one per tooth so each can come off on its own; "indicated for
 * extraction" is a planned extraction, so it reaches the plan and the ceo-d;
 * a retained tooth is the eruption status `impacted`; caries go on surfaces,
 * so they open the surface picker, one tooth at a time.
 */
import type { ClinicalType, ToothTreatmentView } from '~~/app/types'
import type { EruptionStatus } from './dentitionLayout'

export interface ToothFinding {
  /** i18n key under `odontogram.findings.items` and test id. */
  key: string
  kind: 'treatment' | 'surface' | 'eruption'
  /** The clinical type charted (treatment and surface kinds). */
  type?: ClinicalType
  /** The status it is charted with; `existing` unless said. */
  status?: 'existing' | 'planned'
  /** The eruption status (eruption kind). */
  eruption?: EruptionStatus
  /** The bar icon (`TREATMENT_ICONS`) that shows how the chart draws it. */
  icon: string
  /** The finding it replaces: a tooth turns one way, not both. */
  excludes?: string
}

/** The findings asked for on the diagnosis card, in its order. */
export const MAIN_FINDINGS: ToothFinding[] = [
  { key: 'missing', kind: 'treatment', type: 'missing', icon: 'missing' },
  { key: 'extraction_indicated', kind: 'treatment', type: 'extraction', status: 'planned', icon: 'extraction' },
  { key: 'impacted', kind: 'eruption', eruption: 'impacted', icon: 'unerupted' },
  { key: 'rotation_left', kind: 'treatment', type: 'rotation_left', icon: 'rotation_left', excludes: 'rotation_right' },
  { key: 'rotation_right', kind: 'treatment', type: 'rotation_right', icon: 'rotation_right', excludes: 'rotation_left' },
  { key: 'intrusion', kind: 'treatment', type: 'intrusion', icon: 'intrusion', excludes: 'extrusion' },
  { key: 'extrusion', kind: 'treatment', type: 'extrusion', icon: 'extrusion', excludes: 'intrusion' },
  { key: 'diastema', kind: 'treatment', type: 'diastema', icon: 'diastema' },
  { key: 'crowding', kind: 'treatment', type: 'crowding', icon: 'crowding' },
  { key: 'bracket', kind: 'treatment', type: 'bracket', icon: 'bracket' },
  { key: 'caries', kind: 'surface', type: 'caries', icon: 'caries' }
]

/** Other findings the chart already draws, offered below the main ones. */
export const OTHER_FINDINGS: ToothFinding[] = [
  { key: 'incipient_caries', kind: 'surface', type: 'incipient_caries', icon: 'incipient_caries' },
  { key: 'fracture', kind: 'treatment', type: 'fracture', icon: 'fracture' },
  { key: 'pulpitis', kind: 'treatment', type: 'pulpitis', icon: 'pulpitis' },
  { key: 'periapical_small', kind: 'treatment', type: 'periapical_small', icon: 'periapical_small' },
  { key: 'pigmentation', kind: 'surface', type: 'pigmentation', icon: 'pigmentation' }
]

export const ALL_FINDINGS: ToothFinding[] = [...MAIN_FINDINGS, ...OTHER_FINDINGS]

export function findingByKey(key: string): ToothFinding | undefined {
  return ALL_FINDINGS.find(f => f.key === key)
}

export interface FindingState {
  active: boolean
  /** Treatments the card may take off the tooth when the switch goes off. */
  removable: string[]
  /**
   * On, but charted from elsewhere — a catalog treatment, a plan, several
   * teeth at once — so the card does not take it off.
   */
  locked: boolean
}

/**
 * Whether the finding is on one tooth. Only what the card itself charts —
 * a single-tooth treatment with no catalog item — is removed from here;
 * anything else is left to the treatment list, where its plan or budget is.
 */
export function findingState(
  finding: ToothFinding,
  views: ToothTreatmentView[],
  eruptionStatus: EruptionStatus | null
): FindingState {
  if (finding.kind === 'eruption') {
    const active = eruptionStatus === finding.eruption
    return { active, removable: [], locked: false }
  }
  const status = finding.status ?? 'existing'
  const matching = views.filter(v => v.treatment_type === finding.type && v.status === status)
  const removable = matching
    .filter(v => !v.catalog_item_id && !v.is_multi)
    .map(v => v.treatment_id)
  return {
    active: matching.length > 0,
    removable,
    locked: matching.length > 0 && removable.length === 0
  }
}

/** What the card knows of each tooth. */
export interface TeethFacts {
  viewsOf: (tooth: number) => ToothTreatmentView[]
  statusOf: (tooth: number) => EruptionStatus | null
}

/**
 * Changes made on the card and not yet saved: `${finding.key}:${tooth}` →
 * whether the finding should be on that tooth. Only what differs from the
 * chart is kept; *Aceptar* saves it, *Cancelar* drops it.
 */
export type FindingDraft = ReadonlyMap<string, boolean>

function draftKey(finding: ToothFinding, tooth: number): string {
  return `${finding.key}:${tooth}`
}

function stateOn(finding: ToothFinding, tooth: number, facts: TeethFacts): FindingState {
  return findingState(finding, facts.viewsOf(tooth), facts.statusOf(tooth))
}

/** Whether the finding is on the tooth, counting what is pending. */
export function effectiveOn(
  finding: ToothFinding,
  tooth: number,
  facts: TeethFacts,
  draft: FindingDraft = new Map()
): boolean {
  return draft.get(draftKey(finding, tooth)) ?? stateOn(finding, tooth, facts).active
}

export interface SelectionSummary {
  /** Picked teeth the finding is on. */
  active: number
  total: number
  /** On every picked tooth, and none of it is the card's to take off. */
  locked: boolean
}

export function selectionSummary(
  finding: ToothFinding,
  teeth: number[],
  facts: TeethFacts,
  draft: FindingDraft = new Map()
): SelectionSummary {
  const active = teeth.filter(t => effectiveOn(finding, t, facts, draft)).length
  return {
    active,
    total: teeth.length,
    locked: active > 0
      && active === teeth.length
      && teeth.every(t => !draft.has(draftKey(finding, t)) && stateOn(finding, t, facts).locked)
  }
}

/**
 * A press of the switch over the picked teeth, kept as pending. On all of
 * them already: it comes off all of them (what the card may take off).
 * Otherwise it goes on the teeth that lack it, and the opposite movement
 * comes off those. Surface findings are not drafted: they go through the
 * surface picker, one tooth at a time.
 */
export function toggleDraft(
  finding: ToothFinding,
  teeth: number[],
  facts: TeethFacts,
  draft: FindingDraft
): Map<string, boolean> {
  const next = new Map(draft)
  if (!teeth.length || finding.kind === 'surface') return next
  const set = (f: ToothFinding, tooth: number, on: boolean) => {
    const real = stateOn(f, tooth, facts)
    if (!on && real.active && real.locked) return
    if (on === real.active) next.delete(draftKey(f, tooth))
    else next.set(draftKey(f, tooth), on)
  }
  const allOn = teeth.every(t => effectiveOn(finding, t, facts, draft))
  const opposite = finding.excludes ? findingByKey(finding.excludes) : undefined
  for (const tooth of teeth) {
    if (allOn) {
      set(finding, tooth, false)
    } else if (!effectiveOn(finding, tooth, facts, draft)) {
      set(finding, tooth, true)
      if (opposite) set(opposite, tooth, false)
    }
  }
  return next
}

export interface FindingChange {
  finding: ToothFinding
  tooth: number
  /** `true`: it goes on the tooth; `false`: it comes off. */
  on: boolean
}

/** What saving the draft does, removals first so a turn swaps cleanly. */
export function draftChanges(draft: FindingDraft): FindingChange[] {
  const changes: FindingChange[] = []
  for (const [key, on] of draft) {
    const [findingKey, tooth] = key.split(':')
    const finding = findingByKey(findingKey!)
    if (finding) changes.push({ finding, tooth: Number(tooth), on })
  }
  return changes.sort((a, b) => Number(a.on) - Number(b.on))
}

/**
 * The tooth as it will be once the draft is saved, for the card's chart:
 * what comes off is left out, what goes on is drawn as charted today.
 */
export function draftViews(
  tooth: number,
  facts: TeethFacts,
  draft: FindingDraft
): ToothTreatmentView[] {
  let views = facts.viewsOf(tooth)
  for (const finding of ALL_FINDINGS) {
    if (finding.kind !== 'treatment') continue
    const on = draft.get(draftKey(finding, tooth))
    if (on === undefined) continue
    const status = finding.status ?? 'existing'
    if (on) {
      views = [...views, {
        id: `draft:${finding.key}:${tooth}`,
        treatment_id: `draft:${finding.key}:${tooth}`,
        tooth_number: tooth,
        treatment_type: finding.type!,
        clinical_type: finding.type!,
        surfaces: null,
        role: null,
        status,
        recorded_at: new Date().toISOString(),
        source_module: 'odontogram',
        created_at: '',
        updated_at: '',
        is_multi: false,
        teeth_count: 1
      }]
    } else {
      const removable = new Set(stateOn(finding, tooth, facts).removable)
      views = views.filter(v => !removable.has(v.treatment_id))
    }
  }
  return views
}
