<script setup lang="ts">
/**
 * Alta / edición de un tratamiento del catálogo.
 *
 * The form asks four things — what it is called, what kind it is, who does it
 * and where in the mouth it applies — and deduces the rest. The catalog keeps
 * four overlapping classification axes (category, specialty, plan phase and
 * the odontogram bar's clinical category) plus the chart mapping; a dentist
 * knows the first and the other four follow from it. See
 * `../../config/treatmentDefaults.ts` for the two derivation tables.
 *
 * Everything deduced stays visible in a panel and editable under "Ajustes
 * avanzados": the odontogram mapping in particular decides whether the
 * treatment can be planned at all, so it must never be set behind the
 * dentist's back without being shown.
 */
import type {
  CatalogItemSessionInput,
  TreatmentCatalogCategory,
  TreatmentCatalogItem,
  TreatmentCatalogItemUpdate,
  TreatmentCatalogItemCreate,
  TreatmentDentition,
  TreatmentPhase
} from '~~/app/types'
import { getVisualizationRuleLayers } from '~~/app/config/odontogramConstants'
import { PERMISSIONS } from '~~/app/config/permissions'
import {
  DEFAULTS_BY_PLACEMENT,
  DEFAULTS_BY_TYPE,
  placementFromItem,
  chartTypesFor,
  suggestInternalCode,
  type PlacementId
} from '../../config/treatmentDefaults'

const props = defineProps<{
  item: TreatmentCatalogItem | null
  categories: TreatmentCatalogCategory[]
  loading: boolean
}>()

const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{
  save: [data: TreatmentCatalogItemUpdate]
  create: [data: TreatmentCatalogItemCreate]
}>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const { symbol: currencySymbol } = useCurrency()
const { vatTypeOptions, defaultVatType, fetchVatTypes } = useVatTypes()
const { activeSpecialties, fetchSpecialties } = useSpecialties()

onMounted(() => {
  fetchVatTypes()
  fetchSpecialties()
})

const isCreateMode = computed(() => !props.item)
// Seeded items are fully editable — a clinic sets its own prices, names and
// durations, and deactivates what it does not offer. Only the internal code
// stays locked: the seeder matches on it, so renaming it would make the next
// seed run recreate the original alongside the renamed one.
const isSystem = computed(() => !isCreateMode.value && props.item?.is_system)

// ---------------------------------------------------------------------------
// Form state
// ---------------------------------------------------------------------------

const formData = ref<TreatmentCatalogItemUpdate>({})
const placement = ref<PlacementId>('whole_tooth')
/** Chart type. Follows type + placement unless overridden in advanced.
 *  Declared here because the populate watcher below runs immediately. */
const odontogramType = ref<string | undefined>(undefined)
/**
 * Disciplines the treatment belongs to. A list, because the relation is one:
 * a crown over an implant is Implantology *and* Oral Rehabilitation, and 48
 * of the 136 seeded treatments carry more than one.
 *
 * This was a single id. Opening a treatment took `specialties[0]` and saving
 * sent that one back, and the API replaces the whole set — so opening a crown
 * to change its price and pressing Save dropped two of its three disciplines.
 * The survivor was always the most generic one, because the list arrives
 * oldest first: editing prices emptied Implantology into General Dentistry.
 */
const specialtyIds = ref<string[]>([])
const advancedOpen = ref(false)
/** Once the dentist edits the code by hand we stop regenerating it. */
const codeTouched = ref(false)
/**
 * True while the populate watcher is loading an item. The type watcher below
 * re-proposes specialty, phase and placement, and must not fire for a value
 * the clinic already saved.
 */
const populating = ref(false)

const itemName = computed({
  get: () => formData.value.names?.[locale.value] || '',
  set: (value: string) => {
    if (!formData.value.names) formData.value.names = {}
    formData.value.names[locale.value] = value
  }
})

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

interface SessionRow {
  sequence?: number
  label: string
  default_price: number
}
const sessionsEnabled = ref(false)
const sessions = ref<SessionRow[]>([])

function sessionsToPayload(): CatalogItemSessionInput[] {
  return sessions.value.map((s, idx) => ({
    sequence: idx + 1,
    labels: { [locale.value]: s.label },
    default_price: Number(s.default_price) || 0
  }))
}

function addSession() {
  sessions.value.push({ label: '', default_price: 0 })
}

function removeSession(idx: number) {
  sessions.value.splice(idx, 1)
}

const sessionsSum = computed(() =>
  sessions.value.reduce((acc, s) => acc + (Number(s.default_price) || 0), 0)
)

const sessionsSumMatches = computed(() => {
  const total = Number(formData.value.default_price) || 0
  return Math.abs(sessionsSum.value - total) <= 0.01
})

const sessionsProgress = computed(() => {
  const total = Number(formData.value.default_price) || 0
  if (total <= 0) return 0
  return Math.min(100, Math.max(0, (sessionsSum.value / total) * 100))
})

watch(sessionsEnabled, (enabled) => {
  if (!enabled) sessions.value = []
  else if (sessions.value.length === 0) addSession()
})

// ---------------------------------------------------------------------------
// Populate
// ---------------------------------------------------------------------------

/**
 * Load the form from `props.item`, or reset it for a new treatment.
 *
 * Called both when the item changes and every time the modal opens. The
 * second is not redundant: creating two treatments in a row leaves
 * `props.item` at null both times, so watching it alone never fired and the
 * second form opened still carrying the first one's answers.
 */
function populate() {
  const newItem = props.item
  populating.value = true
  advancedOpen.value = false
  if (newItem) {
    codeTouched.value = true
    formData.value = {
      internal_code: newItem.internal_code,
      category_id: newItem.category_id,
      names: { ...newItem.names },
      descriptions: newItem.descriptions ? { ...newItem.descriptions } : undefined,
      default_price: newItem.default_price,
      cost_price: newItem.cost_price,
      pricing_strategy: newItem.pricing_strategy || 'flat',
      pricing_config: newItem.pricing_config ?? null,
      surface_prices: newItem.surface_prices ? { ...newItem.surface_prices } : null,
      default_duration_minutes: newItem.default_duration_minutes,
      requires_appointment: newItem.requires_appointment,
      vat_type_id: newItem.vat_type_id,
      treatment_scope: newItem.treatment_scope,
      is_diagnostic: newItem.is_diagnostic,
      requires_surfaces: newItem.requires_surfaces,
      dentition: newItem.dentition ?? 'both',
      default_phase: newItem.default_phase,
      material_notes: newItem.material_notes,
      is_active: newItem.is_active
    }
    placement.value = placementFromItem(newItem.treatment_scope, newItem.requires_surfaces)
    specialtyIds.value = (newItem.specialties ?? []).map(s => s.id)
    odontogramType.value = newItem.odontogram_mapping?.odontogram_treatment_type
    if (newItem.sessions && newItem.sessions.length > 0) {
      sessionsEnabled.value = true
      sessions.value = newItem.sessions
        .slice()
        .sort((a, b) => a.sequence - b.sequence)
        .map(s => ({
          sequence: s.sequence,
          label: s.labels?.[locale.value] || s.labels?.es || s.labels?.en || '',
          default_price: Number(s.default_price)
        }))
    } else {
      sessionsEnabled.value = false
      sessions.value = []
    }
  } else {
    codeTouched.value = false
    formData.value = {
      internal_code: '',
      category_id: props.categories[0]?.id,
      names: { [locale.value]: '' },
      default_price: 0,
      cost_price: 0,
      pricing_strategy: 'flat',
      pricing_config: null,
      surface_prices: null,
      default_duration_minutes: 30,
      requires_appointment: true,
      vat_type_id: defaultVatType.value?.id,
      treatment_scope: 'tooth',
      is_diagnostic: false,
      requires_surfaces: false,
      dentition: 'both',
      is_active: true
    }
    placement.value = DEFAULTS_BY_TYPE[
      props.categories.find(c => c.id === props.categories[0]?.id)?.key ?? ''
    ]?.defaultPlacement ?? 'whole_tooth'
    specialtyIds.value = []
    odontogramType.value = undefined
    sessionsEnabled.value = false
    sessions.value = []
  }
  // Release on the next tick, once the watchers this populate triggered
  // have run against the loaded values.
  void nextTick(() => {
    populating.value = false
  })
}

watch(() => props.item, populate, { immediate: true })
watch(open, (isOpen) => {
  if (isOpen) populate()
})

// ---------------------------------------------------------------------------
// Derivation — the point of the form
// ---------------------------------------------------------------------------

const categoryOptions = computed(() =>
  props.categories.map(c => ({
    value: c.id,
    label: c.names[locale.value] || c.names.es || c.names.en || c.key
  }))
)

const specialtyOptions = computed(() =>
  activeSpecialties.value.map(s => ({
    value: s.id,
    label: s.names[locale.value] || s.names.es || s.names.en || ''
  }))
)

/** Catalog category key of the selected type, e.g. `restauradora`. */
const categoryKey = computed(() =>
  props.categories.find(c => c.id === formData.value.category_id)?.key ?? ''
)

const typeDefaults = computed(() => DEFAULTS_BY_TYPE[categoryKey.value])
const placementDefaults = computed(() => DEFAULTS_BY_PLACEMENT[placement.value])

const suggestedOdontogramType = computed(() => {
  const d = typeDefaults.value
  if (!d) return undefined
  return placementDefaults.value.isGlobal ? d.globalType : d.toothType
})

const effectiveOdontogramType = computed(
  () => odontogramType.value || suggestedOdontogramType.value
)

/**
 * Only the placements that mean something for this kind of treatment. An
 * endodontic treatment of an arch is not unusual, it is meaningless.
 *
 * Editing is the exception: an item already saved with a placement outside
 * the list keeps it offered, so opening and saving an old record never
 * migrates its scope behind the clinic's back. `Férula de descarga` is a real
 * case — an arch-wide item filed under Restauradora.
 */
const allowedPlacements = computed<PlacementId[]>(() => {
  const allowed = typeDefaults.value?.placements ?? (Object.keys(DEFAULTS_BY_PLACEMENT) as PlacementId[])
  const current = placement.value
  return allowed.includes(current) ? allowed : [...allowed, current]
})

const placementOptions = computed(() =>
  allowedPlacements.value.map(id => ({ id, label: t(`catalog.placement.${id}`) }))
)

/** With a single valid placement the row is a statement, not a choice. */
const placementIsFixed = computed(() => placementOptions.value.length === 1)

const typeAllowsSessions = computed(() => typeDefaults.value?.allowsSessions ?? true)

/**
 * Chart types worth offering, narrowed by type and placement. This used to be
 * a free text box: correcting the suggestion meant knowing that the value is
 * spelled `imaging`, which nothing on screen told you.
 */
const chartTypeOptions = computed(() => {
  const list = chartTypesFor(categoryKey.value, placementDefaults.value.isGlobal)
  const current = effectiveOdontogramType.value
  const all = current && !list.includes(current) ? [...list, current] : list
  return all.map(type => ({
    value: type,
    label: t(`odontogram.treatments.types.${type}`, type)
  }))
})

/** Push the derived values into the payload whenever an answer changes. */
watchEffect(() => {
  const p = placementDefaults.value
  const d = typeDefaults.value
  formData.value.treatment_scope = p.scope
  formData.value.requires_surfaces = p.requiresSurfaces
  formData.value.pricing_strategy = p.pricingStrategy
  if (d) {
    formData.value.is_diagnostic = categoryKey.value === 'diagnostico'
    formData.value.default_phase = formData.value.default_phase ?? d.phase
  }
})

// A type change re-proposes the specialty and the plan phase — in create mode
// only, which is what the comment always claimed and the code did not do: it
// re-proposed on an existing item too, overwriting decisions the clinic had
// made. On a saved treatment the two fields are right there to be changed by
// hand; nothing needs to change them from behind.
watch(categoryKey, (key) => {
  const d = DEFAULTS_BY_TYPE[key]
  if (!d || populating.value) return
  if (isCreateMode.value) {
    formData.value.default_phase = d.phase
    const match = activeSpecialties.value.find(s => s.key === d.specialtyKey)
    if (match) specialtyIds.value = [match.id]
  }
  // On a new treatment the type carries the placement with it: choosing
  // Diagnóstico should land on "toda la boca", not leave "un diente completo"
  // over from the previous type. On an existing item we only intervene when
  // the saved placement no longer exists, so editing never rewrites a choice
  // the clinic already made.
  if (isCreateMode.value || !d.placements.includes(placement.value)) {
    placement.value = d.defaultPlacement
  }
})

// A kind that is a single act cannot be billed in stages.
watch(typeAllowsSessions, (allows) => {
  if (!allows) sessionsEnabled.value = false
})

// Seed the specialty once the list arrives, for a form opened before the fetch.
// Only when none is set: a treatment saved without any discipline must not
// acquire one just because its form was opened.
watch([activeSpecialties, typeDefaults], () => {
  if (specialtyIds.value.length || !typeDefaults.value || !isCreateMode.value) return
  const match = activeSpecialties.value.find(s => s.key === typeDefaults.value!.specialtyKey)
  if (match) specialtyIds.value = [match.id]
})

// The code follows type + name until the dentist takes it over.
watch([categoryKey, itemName], ([key, name]) => {
  if (codeTouched.value || !isCreateMode.value) return
  formData.value.internal_code = suggestInternalCode(key, name)
})

const derivedRows = computed(() => {
  const d = typeDefaults.value
  const rows: Array<{ key: string, value: string }> = [
    { key: t('catalog.derived.code'), value: formData.value.internal_code || '—' },
    {
      key: t('catalog.derived.phase'),
      value: formData.value.default_phase
        ? t(`catalog.phases.${formData.value.default_phase}`)
        : '—'
    },
    {
      key: t('catalog.derived.scope'),
      value: t(`catalog.scopeTypes.${placementDefaults.value.scope}`)
    },
    {
      key: t('catalog.derived.pricing'),
      value: t(`catalog.pricingStrategy.${placementDefaults.value.pricingStrategy}`)
    }
  ]
  if (d) {
    rows.push({
      key: t('catalog.derived.barTab'),
      value: t(`odontogram.treatments.categories.${d.clinicalCategory}`, d.clinicalCategory)
    })
  }
  rows.push({
    key: t('catalog.derived.chart'),
    value: effectiveOdontogramType.value
      ? t(`odontogram.treatments.types.${effectiveOdontogramType.value}`, effectiveOdontogramType.value)
      : '—'
  })
  return rows
})

// ---------------------------------------------------------------------------
// Pricing detail
// ---------------------------------------------------------------------------

const SURFACE_TIERS = ['1', '2', '3', '4', '5'] as const
const showSurfacePrices = computed(() => placementDefaults.value.pricingStrategy === 'per_surface')

watch(showSurfacePrices, (show) => {
  if (show) {
    if (!formData.value.surface_prices) {
      const base = Number(formData.value.default_price) || 0
      formData.value.surface_prices = {
        1: base, 2: base, 3: base, 4: base, 5: base
      } as unknown as Record<string, number>
    }
  } else {
    formData.value.surface_prices = null
  }
}, { immediate: true })

function getTierPrice(tier: string): number | undefined {
  const v = formData.value.surface_prices?.[tier]
  return typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : undefined
}

function setTierPrice(tier: string, value: number | string | undefined) {
  if (!formData.value.surface_prices) formData.value.surface_prices = {}
  const n = value === undefined || value === '' ? 0 : Number(value)
  formData.value.surface_prices[tier] = Number.isFinite(n) ? n : 0
}

const DURATION_PRESETS = [15, 30, 45, 60, 90] as const

const PHASES: readonly TreatmentPhase[] = [
  'diagnostico', 'urgencia', 'preventivo', 'estabilizacion', 'rehabilitacion', 'estetica', 'mantenimiento'
]

const phaseOptions = computed(() =>
  PHASES.map(p => ({ value: p, label: t(`catalog.phases.${p}`) }))
)

const DENTITIONS: readonly TreatmentDentition[] = ['both', 'deciduous', 'permanent']

const dentitionOptions = computed(() =>
  DENTITIONS.map(d => ({ value: d, label: t(`catalog.dentitions.${d}`) }))
)

// `default_phase` is nullable in the API, and the select has no notion of
// null — it clears to undefined. Bridge the two here rather than widening
// the field, so clearing the phase still sends an explicit null.
const defaultPhase = computed<TreatmentPhase | undefined>({
  get: () => formData.value.default_phase ?? undefined,
  set: (value) => {
    formData.value.default_phase = value ?? null
  }
})

// ---------------------------------------------------------------------------
// Submit
// ---------------------------------------------------------------------------

/**
 * Why the form cannot be saved yet, in the dentist's words, or null when it
 * can. A disabled button with no explanation is indistinguishable from a
 * broken one — and the session template makes that easy to hit, since eight
 * rows have to add up to the exact total before anything happens.
 */
// Checked here rather than only where the modal is opened: the guard on a
// trigger protects that one trigger, and a caller added later that forgets
// it would hand the user a full form and a 403 on save. Reusing
// `blockingReason` means the reason is shown, not merely enforced.
const canWrite = computed(() => can(PERMISSIONS.catalog.write))

const blockingReason = computed<string | null>(() => {
  if (!canWrite.value) return t('catalog.blocked.permission')
  if (!itemName.value) return t('catalog.blocked.name')
  if (!formData.value.category_id) return t('catalog.blocked.type')
  if (!formData.value.internal_code) return t('catalog.blocked.code')
  if (sessionsEnabled.value) {
    if (sessions.value.length === 0) return t('catalog.blocked.sessionsEmpty')
    if (sessions.value.some(s => !s.label)) return t('catalog.blocked.sessionLabel')
    if (sessions.value.some(s => s.default_price < 0)) return t('catalog.blocked.sessionNegative')
    if (!sessionsSumMatches.value) {
      return t('catalog.blocked.sessionSum', {
        sum: sessionsSum.value.toFixed(2),
        total: Number(formData.value.default_price || 0).toFixed(2)
      })
    }
  }
  return null
})

const isValid = computed(() => blockingReason.value === null)

function handleSubmit() {
  if (!canWrite.value || !isValid.value) return

  const cleanData: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(formData.value)) {
    if (value !== undefined) cleanData[key] = value
  }

  // Without a mapping the treatment never reaches the plan builder, so one is
  // always sent. `clinical_category` comes from the type, which is what puts
  // the chip in the right tab.
  const oType = effectiveOdontogramType.value
  if (oType && typeDefaults.value) {
    cleanData.odontogram_mapping = {
      odontogram_treatment_type: oType,
      visualization_rules: placementDefaults.value.isGlobal ? [] : getVisualizationRuleLayers(oType),
      visualization_config: {},
      clinical_category: typeDefaults.value.clinicalCategory
    }
  }

  cleanData.sessions = sessionsEnabled.value ? sessionsToPayload() : []
  // Always sent, and always the complete set: the API replaces rather than
  // merges, so a short list is a deletion.
  cleanData.specialty_ids = [...specialtyIds.value]

  if (isCreateMode.value) emit('create', cleanData as TreatmentCatalogItemCreate)
  else emit('save', cleanData as TreatmentCatalogItemUpdate)
}

function handleClose() {
  open.value = false
}
</script>

<template>
  <UModal
    v-model:open="open"
    :ui="{ content: '!max-w-2xl' }"
  >
    <template #content>
      <div class="bg-surface rounded-lg w-full max-h-[92vh] flex flex-col">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-default flex items-start gap-3">
          <div class="min-w-0 flex-1">
            <h2 class="text-lg font-semibold text-highlighted">
              {{ isCreateMode ? t('catalog.newItem') : t('catalog.editItem') }}
            </h2>
            <p class="text-sm text-muted truncate">
              {{ itemName || t('catalog.unnamed') }}
            </p>
          </div>
          <UBadge
            v-if="isSystem"
            color="neutral"
            variant="subtle"
            size="sm"
          >
            {{ t('catalog.system') }}
          </UBadge>
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            size="sm"
            :aria-label="t('actions.close')"
            @click="handleClose"
          />
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          <!-- ── Qué es ─────────────────────────────────────────────── -->
          <section class="space-y-4">
            <h3 class="text-caption uppercase tracking-wide text-subtle">
              {{ t('catalog.sections.what') }}
            </h3>

            <UFormField
              :label="t('catalog.name')"
              required
            >
              <UInput
                v-model="itemName"
                :placeholder="t('catalog.namePlaceholder')"
                class="w-full"
              />
            </UFormField>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <UFormField
                :label="t('catalog.treatmentType')"
                required
              >
                <USelect
                  v-model="formData.category_id"
                  :items="categoryOptions"
                  value-key="value"
                  :placeholder="t('catalog.selectCategory')"
                  class="w-full"
                />
              </UFormField>

              <UFormField
                :label="t('catalog.performedBy')"
                :help="t('catalog.performedByHelp')"
              >
                <USelectMenu
                  v-model="specialtyIds"
                  :items="specialtyOptions"
                  value-key="value"
                  label-key="label"
                  multiple
                  :placeholder="t('catalog.selectSpecialty')"
                  class="w-full"
                />
              </UFormField>
            </div>
          </section>

          <!-- ── Dónde se aplica ────────────────────────────────────── -->
          <section class="space-y-3">
            <h3 class="text-caption uppercase tracking-wide text-subtle">
              {{ t('catalog.sections.where') }}
            </h3>
            <div
              v-if="placementIsFixed"
              class="flex items-center gap-2 text-sm"
            >
              <UIcon
                name="i-lucide-lock"
                class="text-dimmed size-4 shrink-0"
              />
              <span>{{ placementOptions[0]?.label }}</span>
            </div>
            <div
              v-else
              class="flex flex-wrap gap-2"
            >
              <UButton
                v-for="opt in placementOptions"
                :key="opt.id"
                :color="placement === opt.id ? 'primary' : 'neutral'"
                :variant="placement === opt.id ? 'soft' : 'outline'"
                size="sm"
                @click="placement = opt.id"
              >
                {{ opt.label }}
              </UButton>
            </div>
            <p class="text-caption text-subtle">
              {{ placementIsFixed ? t('catalog.placementFixed') : t('catalog.placementHelp') }}
            </p>
          </section>

          <!-- ── Precio y duración ──────────────────────────────────── -->
          <section class="space-y-4">
            <h3 class="text-caption uppercase tracking-wide text-subtle">
              {{ t('catalog.sections.money') }}
            </h3>

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <UFormField :label="t('catalog.defaultPrice')">
                <UInput
                  v-model.number="formData.default_price"
                  type="number"
                  min="0"
                  step="0.01"
                  class="w-full"
                >
                  <template #trailing>
                    <span class="text-dimmed text-caption">{{ currencySymbol }}</span>
                  </template>
                </UInput>
              </UFormField>

              <UFormField :label="t('catalog.vatType')">
                <USelect
                  v-model="formData.vat_type_id"
                  :items="vatTypeOptions"
                  value-key="value"
                  :placeholder="t('catalog.selectVatType')"
                  class="w-full"
                />
              </UFormField>

              <UFormField :label="t('catalog.duration')">
                <UInput
                  v-model.number="formData.default_duration_minutes"
                  type="number"
                  min="0"
                  max="480"
                  step="5"
                  class="w-full"
                >
                  <template #trailing>
                    <span class="text-dimmed text-caption">min</span>
                  </template>
                </UInput>
              </UFormField>
            </div>

            <div class="flex flex-wrap gap-1.5">
              <UButton
                v-for="preset in DURATION_PRESETS"
                :key="preset"
                :color="formData.default_duration_minutes === preset ? 'primary' : 'neutral'"
                :variant="formData.default_duration_minutes === preset ? 'soft' : 'ghost'"
                size="xs"
                @click="formData.default_duration_minutes = preset"
              >
                {{ preset }} min
              </UButton>
            </div>

            <!-- Surface tiers, only when the placement asks for surfaces -->
            <div
              v-if="showSurfacePrices"
              class="rounded-md border border-default p-3 space-y-2"
            >
              <p class="text-caption text-subtle">
                {{ t('catalog.surfacePrices.help') }}
              </p>
              <div class="grid grid-cols-5 gap-2">
                <UFormField
                  v-for="tier in SURFACE_TIERS"
                  :key="tier"
                  :label="tier"
                >
                  <UInput
                    :model-value="getTierPrice(tier)"
                    type="number"
                    min="0"
                    step="0.01"
                    size="sm"
                    class="w-full"
                    @update:model-value="setTierPrice(tier, $event)"
                  />
                </UFormField>
              </div>
            </div>

            <!-- Sessions. Hidden for kinds that are a single act. -->
            <div
              v-if="typeAllowsSessions"
              class="rounded-md border border-default p-3 space-y-3"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <p class="text-sm font-medium">
                    {{ t('catalog.sessions.title') }}
                  </p>
                  <p class="text-caption text-subtle">
                    {{ t('catalog.sessions.help') }}
                  </p>
                </div>
                <USwitch v-model="sessionsEnabled" />
              </div>

              <div
                v-if="sessionsEnabled"
                class="space-y-2"
              >
                <div
                  v-for="(session, idx) in sessions"
                  :key="idx"
                  class="flex items-end gap-2"
                >
                  <UFormField
                    class="flex-1"
                    :label="idx === 0 ? t('catalog.sessions.labelColumn') : undefined"
                  >
                    <UInput
                      v-model="session.label"
                      :placeholder="t('catalog.sessions.labelPlaceholder')"
                      size="sm"
                      class="w-full"
                    />
                  </UFormField>
                  <UFormField
                    class="w-32"
                    :label="idx === 0 ? t('catalog.defaultPrice') : undefined"
                  >
                    <UInput
                      v-model.number="session.default_price"
                      type="number"
                      min="0"
                      step="0.01"
                      size="sm"
                      class="w-full"
                    />
                  </UFormField>
                  <UButton
                    icon="i-lucide-trash-2"
                    color="neutral"
                    variant="ghost"
                    size="sm"
                    :aria-label="t('actions.delete')"
                    @click="removeSession(idx)"
                  />
                </div>

                <div class="flex items-center justify-between gap-3">
                  <UButton
                    icon="i-lucide-plus"
                    color="neutral"
                    variant="ghost"
                    size="xs"
                    @click="addSession"
                  >
                    {{ t('catalog.sessions.add') }}
                  </UButton>
                  <p
                    class="text-caption tnum"
                    :class="sessionsSumMatches ? 'text-success' : 'text-error'"
                  >
                    {{ sessionsSum.toFixed(2) }} / {{ Number(formData.default_price || 0).toFixed(2) }}
                  </p>
                </div>
                <UProgress
                  :model-value="sessionsProgress"
                  :color="sessionsSumMatches ? 'success' : 'warning'"
                  size="sm"
                />
              </div>
            </div>
          </section>

          <!-- ── Se configura solo ──────────────────────────────────── -->
          <section
            class="rounded-md border border-default bg-elevated/40 p-3 space-y-2"
          >
            <h3 class="text-caption uppercase tracking-wide text-subtle">
              {{ t('catalog.derived.title') }}
            </h3>
            <dl class="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2">
              <div
                v-for="row in derivedRows"
                :key="row.key"
              >
                <dt class="text-caption text-subtle">
                  {{ row.key }}
                </dt>
                <dd class="text-sm text-default truncate">
                  {{ row.value }}
                </dd>
              </div>
            </dl>
          </section>

          <!-- ── Ajustes avanzados ──────────────────────────────────── -->
          <section>
            <UButton
              :icon="advancedOpen ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
              color="neutral"
              variant="ghost"
              size="sm"
              @click="advancedOpen = !advancedOpen"
            >
              {{ t('catalog.sections.advanced') }}
            </UButton>

            <div
              v-if="advancedOpen"
              class="mt-3 space-y-4 pl-1"
            >
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <UFormField
                  :label="t('catalog.code')"
                  :help="isSystem ? t('catalog.codeLockedHelp') : t('catalog.codeAutoHelp')"
                >
                  <UInput
                    v-model="formData.internal_code"
                    :disabled="isSystem"
                    class="w-full font-mono"
                    @update:model-value="codeTouched = true"
                  />
                </UFormField>

                <UFormField :label="t('catalog.phase')">
                  <USelect
                    v-model="defaultPhase"
                    :items="phaseOptions"
                    value-key="value"
                    class="w-full"
                  />
                </UFormField>
              </div>

              <UFormField
                :label="t('catalog.odontogramType')"
                :help="t('catalog.odontogramTypeHelp')"
              >
                <USelect
                  :model-value="effectiveOdontogramType"
                  :items="chartTypeOptions"
                  value-key="value"
                  class="w-full"
                  @update:model-value="odontogramType = String($event)"
                />
              </UFormField>

              <UFormField
                :label="t('catalog.dentition')"
                :help="t('catalog.dentitionHelp')"
              >
                <USelect
                  v-model="formData.dentition"
                  :items="dentitionOptions"
                  value-key="value"
                  class="w-full"
                  data-testid="catalog-item-dentition"
                />
              </UFormField>

              <UFormField :label="t('catalog.materialNotes')">
                <UTextarea
                  v-model="formData.material_notes"
                  :rows="2"
                  :placeholder="t('catalog.materialNotesPlaceholder')"
                  class="w-full"
                />
              </UFormField>

              <div class="flex flex-wrap gap-6">
                <div class="flex items-center gap-2">
                  <USwitch v-model="formData.requires_appointment" />
                  <span class="text-sm">{{ t('catalog.requiresAppointment') }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <USwitch v-model="formData.is_active" />
                  <span class="text-sm">{{ t('catalog.active') }}</span>
                </div>
              </div>
            </div>
          </section>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-default flex items-center justify-end gap-3">
          <p
            v-if="blockingReason"
            class="text-caption text-warning mr-auto"
          >
            {{ blockingReason }}
          </p>
          <UButton
            color="neutral"
            variant="ghost"
            @click="handleClose"
          >
            {{ t('actions.cancel') }}
          </UButton>
          <UButton
            color="primary"
            :loading="loading"
            :disabled="!isValid"
            @click="handleSubmit"
          >
            {{ isCreateMode ? t('actions.create') : t('actions.save') }}
          </UButton>
        </div>
      </div>
    </template>
  </UModal>
</template>
