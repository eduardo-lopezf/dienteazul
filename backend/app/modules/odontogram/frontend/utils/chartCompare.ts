/**
 * What changed on a chart between two dates: treatments charted, done or
 * withdrawn in between, teeth whose eruption status moved (an exchange, a
 * tooth coming through) and teeth whose record's condition changed. Each side
 * is the chart as it stood that day (`GET /odontogram/at`), so a treatment
 * done after the first date is still planned on it.
 */
import type { Treatment } from '~~/app/types'

export interface ChartAtDate {
  treatments: Treatment[]
  teeth: Array<{ tooth_number: number, general_condition?: string, eruption_status?: string | null }>
}

export type ChangeKind = 'added' | 'performed' | 'removed' | 'eruption' | 'condition'

export interface ChartChange {
  kind: ChangeKind
  /** First tooth it touches; `null` for whole-mouth and whole-arch work. */
  tooth: number | null
  teeth: number[]
  /** The clinical type; for an eruption or condition change, the new value. */
  type: string
  /** Status on the second date (for `added`). */
  planned?: boolean
  /** The value on the first date (for `eruption` and `condition`). */
  from?: string | null
}

function isPlanned(treatment: Treatment): boolean {
  return treatment.status === 'planned'
}

function teethOf(treatment: Treatment): number[] {
  return (treatment.teeth ?? []).map(t => t.tooth_number).sort((a, b) => a - b)
}

/** The changes from `before` to `after`, tooth by tooth; whole-mouth last. */
export function compareCharts(before: ChartAtDate, after: ChartAtDate): ChartChange[] {
  const changes: ChartChange[] = []
  const beforeById = new Map(before.treatments.map(t => [t.id, t]))
  const afterById = new Map(after.treatments.map(t => [t.id, t]))

  for (const treatment of after.treatments) {
    const teeth = teethOf(treatment)
    const was = beforeById.get(treatment.id)
    const base = { tooth: teeth[0] ?? null, teeth, type: treatment.clinical_type }
    if (!was) {
      changes.push({ kind: 'added', ...base, planned: isPlanned(treatment) })
    } else if (isPlanned(was) && !isPlanned(treatment)) {
      changes.push({ kind: 'performed', ...base })
    }
  }
  for (const treatment of before.treatments) {
    if (afterById.has(treatment.id)) continue
    const teeth = teethOf(treatment)
    changes.push({ kind: 'removed', tooth: teeth[0] ?? null, teeth, type: treatment.clinical_type })
  }

  const statusBefore = new Map(before.teeth.map(t => [t.tooth_number, t.eruption_status ?? null]))
  for (const tooth of after.teeth) {
    const now = tooth.eruption_status ?? null
    const then = statusBefore.get(tooth.tooth_number) ?? null
    if (now !== then && now !== null) {
      changes.push({ kind: 'eruption', tooth: tooth.tooth_number, teeth: [tooth.tooth_number], type: now, from: then })
    }
  }

  const conditionBefore = new Map(before.teeth.map(t => [t.tooth_number, t.general_condition ?? 'healthy']))
  for (const tooth of after.teeth) {
    const now = tooth.general_condition ?? 'healthy'
    const then = conditionBefore.get(tooth.tooth_number) ?? 'healthy'
    if (now !== then) {
      changes.push({ kind: 'condition', tooth: tooth.tooth_number, teeth: [tooth.tooth_number], type: now, from: then })
    }
  }

  return changes.sort((a, b) => (a.tooth ?? 999) - (b.tooth ?? 999))
}
