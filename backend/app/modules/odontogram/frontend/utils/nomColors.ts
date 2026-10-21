/**
 * The colours the odontogram draws teeth in, after the convention of the
 * Mexican record (NOM-013-SSA2-2015 and the clinical practice around it;
 * see docs/technical/odontogram/color-convention.md):
 *
 * - **red**: active caries and lesions, and any work still to do;
 * - **blue**: work done (fillings, endodontics, crowns, implants) and a tooth
 *   already absent;
 * - **green**: incipient caries (white spots) and provisional work;
 * - **yellow**: prevention (pit and fissure sealants).
 *
 * The status comes first: anything planned is red, whatever it is. The
 * treatment bar keeps its own palette — its icons tell treatments apart; the
 * chart tells the state of the mouth.
 */
export type NomTone = 'red' | 'blue' | 'green' | 'yellow'

/** Findings that are disease in the mouth now. */
const LESIONS = new Set([
  'caries',
  'pulpitis',
  'periapical_small',
  'periapical_medium',
  'periapical_large',
  'fracture',
  // A tooth record's condition, read by the change history.
  'extraction_indicated'
])
const INCIPIENT_OR_PROVISIONAL = new Set([
  'incipient_caries',
  'filling_temporary',
  'provisional_crown_on_implant'
])
const PREVENTION = new Set(['sealant'])

export function nomTone(type: string, status: 'existing' | 'planned' | string): NomTone {
  if (status === 'planned') return 'red'
  if (LESIONS.has(type)) return 'red'
  if (INCIPIENT_OR_PROVISIONAL.has(type)) return 'green'
  if (PREVENTION.has(type)) return 'yellow'
  return 'blue'
}

/** Light and dark renderings of each tone; paper always takes the light one. */
export const NOM_COLORS: Record<NomTone, { light: string, dark: string }> = {
  red: { light: '#DC2626', dark: '#F87171' },
  blue: { light: '#1D4ED8', dark: '#60A5FA' },
  green: { light: '#16A34A', dark: '#4ADE80' },
  yellow: { light: '#EAB308', dark: '#FACC15' }
}

export function nomColor(type: string, status: string, dark = false): string {
  const tone = NOM_COLORS[nomTone(type, status)]
  return dark ? tone.dark : tone.light
}
