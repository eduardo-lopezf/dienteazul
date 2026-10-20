/**
 * What the alta form deduces so the dentist does not have to answer it.
 *
 * The catalog carries four overlapping classification axes — category,
 * specialty, plan phase and the odontogram bar's clinical category — and a
 * dentist filling the form knows one of them: what kind of treatment it is.
 * The other three follow from it closely enough that asking is busywork, and
 * every one of them is correctable: the specialty is a field in the form, the
 * phase can be overridden per patient when the item is planned, and the bar
 * tab only decides where the chip is listed.
 *
 * Keys are the catalog category keys, which the seeded catalog and the
 * odontogram's clinical categories both use.
 */

import type { TreatmentPhase } from '~~/app/types'

export interface TypeDefaults {
  /** `key` of the specialty that usually performs it. */
  specialtyKey: string
  /** Stage of care, one of the backend's TREATMENT_PHASES. */
  phase: TreatmentPhase
  /** Tab of the odontogram bar — the mapping's `clinical_category`. */
  clinicalCategory: string
  /** Canonical odontogram type for a tooth-scoped item of this kind. */
  toothType: string
  /** Odontogram type for a whole-mouth / whole-arch item of this kind. */
  globalType: string
  /**
   * Placements that make clinical sense for this kind of treatment, in the
   * order the chips are shown. Anything else is not "unusual", it is
   * meaningless: there is no such thing as an endodontic treatment of an arch,
   * and offering it only invites a wrong answer.
   */
  placements: PlacementId[]
  /** Preselected chip. Always one of `placements`. */
  defaultPlacement: PlacementId
  /**
   * Chart types worth offering for a tooth-scoped item of this kind. Not the
   * whole enum: a dentist filing a filling has no use for `bracket`, and the
   * field used to be free text where you had to know the identifier by heart.
   */
  chartTypesTooth: string[]
  /**
   * Whether the treatment can be executed and billed in stages. False for the
   * kinds that are a single act — a consultation, a radiograph or a fluoride
   * application either happens or it does not.
   */
  allowsSessions: boolean
}

export const DEFAULTS_BY_TYPE: Readonly<Record<string, TypeDefaults>> = {
  diagnostico: {
    specialtyKey: 'general',
    phase: 'diagnostico',
    clinicalCategory: 'diagnostico',
    toothType: 'caries',
    globalType: 'consultation',
    placements: ['mouth', 'whole_tooth'],
    defaultPlacement: 'mouth',
    chartTypesTooth: [
      'caries',
      'incipient_caries',
      'pigmentation',
      'fracture',
      'missing',
      'pulpitis',
      'periapical_small',
      'periapical_medium',
      'periapical_large',
      'rotated',
      'displaced',
      'unerupted'
    ],
    allowsSessions: false
  },
  preventivo: {
    specialtyKey: 'higiene',
    phase: 'preventivo',
    clinicalCategory: 'preventivo',
    toothType: 'sealant',
    globalType: 'hygiene',
    placements: ['mouth', 'several_teeth', 'whole_tooth'],
    defaultPlacement: 'mouth',
    chartTypesTooth: [
      'sealant'
    ],
    allowsSessions: false
  },
  restauradora: {
    specialtyKey: 'general',
    phase: 'estabilizacion',
    clinicalCategory: 'restauradora',
    toothType: 'filling_composite',
    globalType: 'hygiene',
    placements: ['tooth_surfaces', 'whole_tooth', 'several_teeth'],
    defaultPlacement: 'tooth_surfaces',
    chartTypesTooth: [
      'filling_composite',
      'filling_amalgam',
      'filling_temporary',
      'inlay',
      'overlay',
      'crown',
      'veneer',
      'bridge',
      'splint'
    ],
    allowsSessions: true
  },
  endodoncia: {
    specialtyKey: 'endodoncia',
    phase: 'estabilizacion',
    clinicalCategory: 'endodoncia',
    toothType: 'root_canal_full',
    globalType: 'checkup',
    placements: ['whole_tooth'],
    defaultPlacement: 'whole_tooth',
    chartTypesTooth: [
      'root_canal_full',
      'root_canal_two_thirds',
      'root_canal_half',
      'post',
      'root_canal_overfill'
    ],
    allowsSessions: true
  },
  periodoncia: {
    specialtyKey: 'periodoncia',
    phase: 'estabilizacion',
    clinicalCategory: 'periodoncia',
    toothType: 'extraction',
    globalType: 'hygiene',
    placements: ['mouth', 'several_teeth', 'whole_tooth'],
    defaultPlacement: 'mouth',
    chartTypesTooth: [
      'extraction',
      'splint'
    ],
    allowsSessions: true
  },
  cirugia: {
    specialtyKey: 'cirugia',
    phase: 'estabilizacion',
    clinicalCategory: 'cirugia',
    toothType: 'extraction',
    globalType: 'consultation',
    placements: ['whole_tooth', 'several_teeth', 'mouth'],
    defaultPlacement: 'whole_tooth',
    chartTypesTooth: [
      'extraction',
      'implant',
      'apicoectomy',
      'biopsy_soft_tissue',
      'biopsy_hard_tissue'
    ],
    allowsSessions: true
  },
  protesis: {
    specialtyKey: 'rehabilitacion',
    phase: 'rehabilitacion',
    clinicalCategory: 'protesis',
    toothType: 'crown',
    globalType: 'checkup',
    placements: ['whole_tooth', 'several_teeth', 'arch'],
    defaultPlacement: 'whole_tooth',
    chartTypesTooth: [
      'crown',
      'crown_on_implant',
      'provisional_crown_on_implant',
      'bridge'
    ],
    allowsSessions: true
  },
  ortodoncia: {
    specialtyKey: 'ortodoncia',
    phase: 'rehabilitacion',
    clinicalCategory: 'ortodoncia',
    toothType: 'bracket',
    globalType: 'checkup',
    placements: ['mouth', 'arch', 'whole_tooth'],
    defaultPlacement: 'mouth',
    chartTypesTooth: [
      'bracket',
      'tube',
      'band',
      'attachment',
      'retainer'
    ],
    allowsSessions: true
  },
  estetica: {
    specialtyKey: 'estetica',
    phase: 'estetica',
    clinicalCategory: 'estetica',
    toothType: 'veneer',
    globalType: 'hygiene',
    placements: ['tooth_surfaces', 'whole_tooth', 'several_teeth', 'mouth'],
    defaultPlacement: 'whole_tooth',
    chartTypesTooth: [
      'veneer',
      'filling_composite',
      'crown'
    ],
    allowsSessions: true
  },
  pediatrica: {
    specialtyKey: 'odontopediatria',
    phase: 'estabilizacion',
    clinicalCategory: 'pediatrica',
    toothType: 'filling_composite',
    globalType: 'checkup',
    placements: ['tooth_surfaces', 'whole_tooth', 'several_teeth', 'mouth'],
    defaultPlacement: 'whole_tooth',
    chartTypesTooth: [
      'filling_composite',
      'sealant',
      'crown',
      'extraction'
    ],
    allowsSessions: true
  }
}

/**
 * "Where does it apply?" — the one clinical question the software cannot
 * deduce, asked the way a dentist would put it. Everything on the Clínico tab
 * used to ask the same thing in the schema's own vocabulary.
 */
export type PlacementId
  = 'tooth_surfaces' | 'whole_tooth' | 'several_teeth' | 'arch' | 'mouth'

export interface PlacementDefaults {
  scope: 'tooth' | 'multi_tooth' | 'global_arch' | 'global_mouth'
  requiresSurfaces: boolean
  pricingStrategy: 'flat' | 'per_tooth' | 'per_surface' | 'per_role'
  /** Whether the item lands on the odontogram chart at all. */
  isGlobal: boolean
}

export const DEFAULTS_BY_PLACEMENT: Readonly<Record<PlacementId, PlacementDefaults>> = {
  tooth_surfaces: {
    scope: 'tooth',
    requiresSurfaces: true,
    pricingStrategy: 'per_surface',
    isGlobal: false
  },
  whole_tooth: {
    scope: 'tooth',
    requiresSurfaces: false,
    pricingStrategy: 'flat',
    isGlobal: false
  },
  several_teeth: {
    scope: 'multi_tooth',
    requiresSurfaces: false,
    pricingStrategy: 'per_tooth',
    isGlobal: false
  },
  arch: {
    scope: 'global_arch',
    requiresSurfaces: false,
    pricingStrategy: 'flat',
    isGlobal: true
  },
  mouth: {
    scope: 'global_mouth',
    requiresSurfaces: false,
    pricingStrategy: 'flat',
    isGlobal: true
  }
}

/** Reverse lookup, so editing an existing item preselects the right chip. */
export function placementFromItem(
  scope: string | undefined,
  requiresSurfaces: boolean | undefined
): PlacementId {
  if (scope === 'global_mouth') return 'mouth'
  if (scope === 'global_arch') return 'arch'
  if (scope === 'multi_tooth') return 'several_teeth'
  return requiresSurfaces ? 'tooth_surfaces' : 'whole_tooth'
}

/**
 * Build the internal code from the type and the name, so a dentist never has
 * to invent one. Unique per clinic and immutable on seeded items, which is
 * exactly the kind of value a person should not be asked to mint by hand.
 *
 * `REST` + `OBTURACION-COMPOSITE` → `REST-OBTURACION-COMPOSITE`, trimmed to
 * the column's 50 characters. The caller checks it for collisions and appends
 * a suffix when the clinic already used it.
 */
export function suggestInternalCode(categoryKey: string, name: string): string {
  const prefix = (categoryKey || 'TRAT').slice(0, 4).toUpperCase()
  const slug = name
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  if (!slug) return prefix
  return `${prefix}-${slug}`.slice(0, 50).replace(/-+$/, '')
}

/**
 * Chart types for an item that is not attached to a tooth. A whole-mouth or
 * whole-arch act is a visit-level act whatever the discipline, so the four
 * process types serve every kind; surgery additionally has the skeletal ones.
 */
const CHART_TYPES_GLOBAL = ['consultation', 'checkup', 'imaging', 'hygiene']
const CHART_TYPES_SKELETAL = [
  'osteotomy_lefort1',
  'osteotomy_sagittal_ramus',
  'genioplasty',
  'osteosynthesis',
  'osteosynthesis_removal'
]

/** The shortlist the form offers for this type + placement. */
export function chartTypesFor(categoryKey: string, isGlobal: boolean): string[] {
  if (isGlobal) {
    return categoryKey === 'cirugia'
      ? [...CHART_TYPES_GLOBAL, ...CHART_TYPES_SKELETAL]
      : [...CHART_TYPES_GLOBAL]
  }
  return [...(DEFAULTS_BY_TYPE[categoryKey]?.chartTypesTooth ?? [])]
}
