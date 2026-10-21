/**
 * Turning a record entry's `detail` into lines a person can read.
 *
 * The server sends each fact under its owning column's name and never
 * decides the wording (a record is read in the clinic's language), so the
 * labels and the coded values are translated here.
 */
type Translate = (key: string, params?: Record<string, unknown>) => string
type Exists = (key: string) => boolean

export interface DetailLine {
  key: string
  label: string
  value: string
}

/** Already said by the entry's summary, or by the section it is in. */
const HIDDEN = new Set([
  'first_name', 'last_name', 'name', 'procedure', 'condition', 'items',
  'media_category', 'scan_document_id', 'document_sha256', 'chief_complaint'
])

/**
 * Where a coded value is already translated. The record reuses the words
 * of the screen where the fact was written, so "caries" reads the same
 * here as on the odontogram. `record.value.<key>` is tried first.
 */
const VALUE_KEYS: Record<string, string[]> = {
  type: ['patients.medicalHistory.allergyTypes', 'patients.medicalHistory.diseaseTypes'],
  severity: ['patients.medicalHistory.severity'],
  alcohol_consumption: ['patients.medicalHistory.alcohol'],
  gender: ['patients.gender'],
  clinical_type: ['odontogram.treatments.types'],
  status: ['treatmentPlans.status', 'consents.status'],
  closure_reason: ['treatmentPlans.closureReason'],
  kind: ['consents.kinds'],
  signer_capacity: ['consents.capacity'],
  relative: ['patients.medicalHistory.relatives'],
  prognosis: ['treatmentPlans.prognosis'],
  declared_conditions: ['healthQuestionnaire.conditions'],
  question: ['healthQuestionnaire.questions'],
  form_kind: ['healthQuestionnaire.forms'],
  form_field: ['healthQuestionnaire.pediatric.fields']
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:\d{2})?)?$/

export function formatDate(iso: string, locale: string): string {
  // A bare date has no time zone: read it as the calendar day it names.
  const date = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso)
  return date.toLocaleDateString(locale, { day: '2-digit', month: 'short', year: 'numeric' })
}

interface Tooth { tooth_number: number, surfaces?: string[] | null }

function teeth(value: unknown[]): string {
  return value.map((tooth) => {
    if (typeof tooth === 'number') return String(tooth)
    const { tooth_number: number, surfaces } = tooth as Tooth
    return surfaces?.length ? `${number} (${surfaces.join(', ')})` : String(number)
  }).join(', ')
}

function text(key: string, value: unknown, t: Translate, te: Exists, locale: string): string {
  if (typeof value === 'boolean') return t(value ? 'common.yes' : 'common.no')
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') {
    if (ISO_DATE.test(value)) return formatDate(value, locale)
    for (const prefix of [`record.value.${key}`, ...(VALUE_KEYS[key] ?? [])]) {
      if (te(`${prefix}.${value}`)) return t(`${prefix}.${value}`)
    }
    // A code nobody translated still reads better without its underscores.
    return /^[a-z]+(_[a-z]+)+$/.test(value) ? value.replaceAll('_', ' ') : value
  }
  if (Array.isArray(value)) {
    if (key === 'teeth') return teeth(value)
    if (key === 'form_data') {
      // What a form asks to write, each value under its own label.
      return (value as { field: string, value: string }[])
        .map(item => `${text('form_field', item.field, t, te, locale)}: ${item.value}`)
        .join(' · ')
    }
    if (key === 'affirmative_answers') {
      // What the patient answered "yes" to, with the cause they gave.
      return (value as { question: string, detail?: string | null }[]).map((item) => {
        const question = text('question', item.question, t, te, locale)
        return item.detail ? `${question} — ${item.detail}` : question
      }).join(' · ')
    }
    // A list of codes: each one in the words of the screen it came from.
    return value.map(item => text(key, item, t, te, locale)).filter(Boolean).join(', ')
  }
  if (value && typeof value === 'object') {
    return Object.values(value).filter(part => part !== null && part !== '').join(', ')
  }
  return ''
}

export function detailLines(
  detail: Record<string, unknown>,
  summary: string,
  t: Translate,
  te: Exists,
  locale: string
): DetailLine[] {
  const lines: DetailLine[] = []
  for (const [key, value] of Object.entries(detail)) {
    if (HIDDEN.has(key) || value === null || value === undefined || value === '') continue
    const shown = text(key, value, t, te, locale)
    if (!shown || shown === summary) continue
    const label = `record.field.${key}`
    lines.push({ key, label: te(label) ? t(label) : key, value: shown })
  }
  return lines
}

export interface PlanItem { treatment: string | null, teeth: number[], status: string }

export function planItems(detail: Record<string, unknown>): PlanItem[] {
  return Array.isArray(detail.items) ? detail.items as PlanItem[] : []
}
