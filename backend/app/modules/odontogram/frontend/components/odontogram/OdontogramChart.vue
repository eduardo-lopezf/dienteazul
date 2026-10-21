<script setup lang="ts">
/**
 * OdontogramChart - Main dental chart component
 *
 * Features:
 * - Interactive tooth visualization with dual view (occlusal + lateral)
 * - Click-to-apply treatment mode with keyboard shortcuts
 * - Timeline slider for historical view
 * - Treatment management (add, edit, delete, perform)
 */

import type {
  ClinicalType,
  OdontogramHistoryEntry,
  Surface,
  ToothTreatmentView,
  Treatment,
  TreatmentCreate,
  TreatmentStatus
} from '~~/app/types'
import { TREATMENT_SHORTCUTS } from '~~/app/constants/odontogram'
import { calculateToothRange, getMultiToothConfig, isSameArch } from '~~/app/config/odontogramConstants'
import { viewsForTooth } from '~~/app/utils/treatmentView'
import { isSurfaceTreatment } from './TreatmentIcons'
import {
  dimmedTeeth as dimmedForDentition,
  eruptionAlerts,
  fitsTooth,
  offeredOn,
  shownDentition,
  teethLayout as layoutForDentition,
  type ChartFacts,
  type Dentition,
  type EruptionStatus,
  type ShownDentition
} from '../../utils/dentitionLayout'
import { dentalIndices } from '../../utils/dentalIndices'
import { boxDimmedTeeth as boxDimmed } from '../../utils/boxChart'

export type OdontogramMode = 'full' | 'view-only' | 'diagnosis' | 'planning'

const props = withDefaults(defineProps<{
  patientId: string
  mode?: OdontogramMode
  statusFilter?: TreatmentStatus[]
  /** Teeth to highlight (for hover linking from parent) */
  highlightedTeethProp?: number[]
  /** Global treatment IDs to highlight in the globals strip (hover linking). */
  highlightedGlobalIds?: string[]
  /** Plan ID for filtering treatments in planning mode */
  planId?: string
  /** Plan title shown as context banner inside the TreatmentBar (planning mode). */
  planTitle?: string
}>(), {
  mode: 'full',
  highlightedTeethProp: () => [],
  highlightedGlobalIds: () => []
})

const emit = defineEmits<{
  treatmentAdd: [treatment: Treatment]
  treatmentPerform: [treatmentId: string]
  /** Fired after any treatment mutation (add/update/delete/perform) */
  treatmentsChanged: []
  /** Emitted when user hovers over a tooth (for hover linking) */
  toothHover: [toothNumber: number | null]
  /** Emitted when user hovers a chip in the globals strip. */
  globalHover: [treatmentId: string | null]
  /** Arch currently under hover (for painting the arch halo). */
  archHover: [arch: 'upper' | 'lower' | null]
  /**
   * A click landed on a tooth while the chart was in `view-only`.
   *
   * The chart refuses the click but cannot say why: it is handed
   * `view-only` by whoever owns it, and the reason lives there — a plan
   * locked by a budget in progress, a ficha opened by someone without
   * write rights. So it reports the refusal and the owner explains it.
   */
  readonlyInteraction: [toothNumber: number]
}>()

const { t, locale } = useI18n()
const toast = useToast()
const treatmentCatalog = useTreatmentCatalog()

// ============================================================================
// Composables
// ============================================================================

const {
  loading,
  error,
  odontogramData,
  fetchOdontogram,
  fetchPatientHistory,
  getToothRecord,
  treatments,
  treatmentsLoading,
  fetchTreatments,
  createTreatment,
  performTreatment,
  deleteTreatment,
  updateTreatment,
  getToothTreatments,
  timelineDates,
  viewingDate,
  timelineLoading,
  isViewingHistory,
  displayTreatments,
  displayTeeth,
  fetchTimeline,
  fetchOdontogramAtDate,
  returnToCurrentView
} = useOdontogram()

const treatmentPlansApi = useTreatmentPlans()

// ============================================================================
// State
// ============================================================================

// ----------------------------------------------------------------------------
// Dentition: what the patient's age suggests, unless the clinician chose
// another for this patient (kept on the server). See `utils/dentitionLayout`.
// ----------------------------------------------------------------------------

const api = useApi()
/** The clinician's choice for this patient; `auto` follows the age. */
const chosenDentition = ref<Dentition>('auto')
watch(odontogramData, (data) => {
  chosenDentition.value = data?.dentition ?? 'auto'
}, { immediate: true })
const patientAge = computed(() => odontogramData.value?.patient_age ?? null)
const suggestedDentition = computed<ShownDentition>(
  () => odontogramData.value?.suggested_dentition ?? 'permanent'
)
const dentitionMode = computed<ShownDentition>(
  () => shownDentition(chosenDentition.value, suggestedDentition.value)
)
const dentitionOptions = computed(() => [
  { value: 'auto', label: t('odontogram.dentition.auto') },
  { value: 'deciduous', label: t('odontogram.dentition.deciduous') },
  { value: 'mixed', label: t('odontogram.dentition.mixed') },
  { value: 'permanent', label: t('odontogram.dentition.permanent') }
])
/** "8 años · Mixta", or why the age cannot decide. */
const dentitionHint = computed(() =>
  patientAge.value === null
    ? t('odontogram.dentition.noBirthDate')
    : t('odontogram.dentition.byAge', {
        age: patientAge.value,
        dentition: t(`odontogram.dentition.${suggestedDentition.value}`).toLowerCase()
      })
)

/** Something is charted on the tooth: it is in the mouth, whatever the age. */
function isCharted(tooth: number): boolean {
  if (displayTreatments.value.some(tr => tr.teeth?.some(tt => tt.tooth_number === tooth))) {
    return true
  }
  const record = getToothRecord(tooth)
  return !!record && record.general_condition !== 'healthy'
}

async function chooseDentition(value: Dentition) {
  const previous = chosenDentition.value
  chosenDentition.value = value
  // A read-only chart may be looked at another way, not changed for everyone.
  if (isReadonly.value) return
  try {
    await api.put(`/api/v1/odontogram/patients/${props.patientId}/odontogram/dentition`, {
      dentition: value
    })
  } catch {
    chosenDentition.value = previous
    toast.add({ title: t('odontogram.dentition.saveFailed'), color: 'error' })
  }
}
const selectedTooth = ref<number | null>(null)
const showSurfaceSelector = ref(false)
const hoveredTooth = ref<number | null>(null)
const internalHighlightedTeeth = ref<number[]>([])
/** Arch currently under hover from the globals strip — paints a subtle halo. */
const hoveredArch = ref<'upper' | 'lower' | null>(null)

function handleGlobalHover(id: string | null) {
  emit('globalHover', id)
}
function handleArchHover(arch: 'upper' | 'lower' | null) {
  hoveredArch.value = arch
  emit('archHover', arch)
}

// Merge internal highlighted teeth with prop (for hover linking).
// Multi-tooth selection has its own dedicated style via `multi-selected-teeth`.
const highlightedTeeth = computed(() => [
  ...internalHighlightedTeeth.value,
  ...props.highlightedTeethProp
])

// Click-to-apply mode. Stores the clinical_type (e.g. 'crown', 'bridge') and/or
// catalog item selected via the TreatmentBar. Catalog-item selection is tracked
// separately in `selectedCatalogItemId`.
const selectedTreatmentType = ref<string | null>(null)
const selectedCatalogItemId = ref<string | null>(null)
const selectedTreatmentStatus = ref<TreatmentStatus>('existing')

// Multi-tooth selection (bridges, splints, multiple veneers/crowns)
const multiToothSelection = ref<{ teeth: number[], anchor: number | null }>({ teeth: [], anchor: null })
const showMultiToothConfirm = ref(false)

// Undo stack (single entry per Treatment, whether single- or multi-tooth).
const undoStack = ref<Array<{ treatmentId: string, type: string }>>([])

// History section
const historyData = ref<OdontogramHistoryEntry[]>([])
const historyLoading = ref(false)

// Treatment editing (per-tooth view — edit modal operates on single-tooth context).
const showTreatmentEditModal = ref(false)
const editingTreatment = ref<ToothTreatmentView | null>(null)

// Always show dual view
const showLateral = true

// ============================================================================
// Computed
// ============================================================================

const isReadonly = computed(() => props.mode === 'view-only' || isViewingHistory.value)
const isPlanningMode = computed(() => props.mode === 'planning')
const isDiagnosisMode = computed(() => props.mode === 'diagnosis')

// Map OdontogramChart mode to TreatmentBar mode
const treatmentBarMode = computed(() => {
  if (props.mode === 'diagnosis') return 'diagnosis'
  if (props.mode === 'planning') return 'planning'
  return 'full'
})
const isClickToApplyMode = computed(() => selectedTreatmentType.value !== null)

const multiToothConfig = computed(() => {
  if (!selectedTreatmentType.value) return null
  return getMultiToothConfig(selectedTreatmentType.value as string)
})

const isMultiToothMode = computed(() => multiToothConfig.value !== null)

/** What the chart knows of the patient's teeth, for the layout and warnings. */
const chartFacts = computed<ChartFacts>(() => ({
  age: patientAge.value,
  charted: isCharted,
  // In the history view, where the tooth stood on that date (rebuilt by the
  // server from its eruption history); otherwise today's record.
  statusOf: tooth => (
    (isViewingHistory.value
      ? displayTeeth.value.find(r => r.tooth_number === tooth)
      : getToothRecord(tooth))?.eruption_status ?? null
  ) as EruptionStatus | null,
  ages: odontogramData.value?.eruption_ages
}))
// ----------------------------------------------------------------------------
// View: the anatomical chart (crown and root) or the box chart of the paper
// forms. A matter of taste per person, so it is kept in this browser only.
// ----------------------------------------------------------------------------

/** The chart on two dates side by side (`OdontogramCompare`). */
const compareOpen = ref(false)

type ChartView = 'anatomical' | 'boxes'
const CHART_VIEW_KEY = 'odontogram:view'
const chartView = ref<ChartView>('anatomical')
onMounted(() => {
  try {
    if (localStorage.getItem(CHART_VIEW_KEY) === 'boxes') chartView.value = 'boxes'
  } catch {
    // No storage (private window): the default view it is.
  }
})
function chooseChartView(value: ChartView) {
  chartView.value = value
  try {
    localStorage.setItem(CHART_VIEW_KEY, value)
  } catch {
    // Nothing to remember it in; it holds for this visit.
  }
}
const chartViewOptions = computed(() => [
  { value: 'anatomical', label: t('odontogram.boxes.viewAnatomical') },
  { value: 'boxes', label: t('odontogram.boxes.viewBoxes') }
])
/** In a mixed dentition the box chart draws every row: see `boxDimmedTeeth`. */
const boxDimmedTeeth = computed(() => boxDimmed(dentitionMode.value, chartFacts.value))

/** CPO-D and ceo-d of the chart as shown — the history view's in the past. */
const indices = computed(() =>
  dentalIndices({
    treatments: displayTreatments.value,
    conditionOf: tooth => getToothRecord(tooth)?.general_condition,
    statusOf: chartFacts.value.statusOf
  })
)
const showCpod = computed(() => dentitionMode.value !== 'deciduous')
const showCeod = computed(() => dentitionMode.value !== 'permanent')
const teethLayout = computed(() => layoutForDentition(dentitionMode.value, chartFacts.value))
const dimmedTeeth = computed(() => dimmedForDentition(dentitionMode.value, chartFacts.value))
const alerts = computed(() =>
  isViewingHistory.value
    ? []
    : eruptionAlerts(chartFacts.value, odontogramData.value?.eruption_tolerance)
)

// ----------------------------------------------------------------------------
// Eruption: clicking a tooth with no treatment armed opens its eruption card.
// ----------------------------------------------------------------------------

const eruptionTooth = ref<number | null>(null)

function openEruption(toothNumber: number) {
  eruptionTooth.value = toothNumber
}

async function onEruptionChanged() {
  await fetchOdontogram(props.patientId)
}

const pendingTreatment = computed(() => {
  if (!selectedTreatmentType.value) return null
  // Multi-tooth keys (bridge, multiple_veneers...) are UI-only. Skip the single-tooth preview.
  if (isMultiToothMode.value) return null
  return {
    type: selectedTreatmentType.value as ClinicalType,
    status: selectedTreatmentStatus.value
  }
})

// ============================================================================
// Lifecycle
// ============================================================================

async function loadAll(patientId: string) {
  await Promise.all([
    fetchOdontogram(patientId),
    fetchTreatments(patientId),
    fetchTimeline(patientId)
  ])
}

onMounted(async () => {
  await loadAll(props.patientId)
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})

watch(() => props.patientId, async (newId) => {
  if (newId) {
    returnToCurrentView()
    await Promise.all([
      fetchOdontogram(newId),
      fetchTreatments(newId),
      fetchTimeline(newId)
    ])
  }
})

// Emit tooth hover for parent hover linking
watch(hoveredTooth, (toothNumber) => {
  emit('toothHover', toothNumber)
})

// ============================================================================
// Tooth Data Helpers
// ============================================================================

function getToothData(toothNumber: number) {
  const record = getToothRecord(toothNumber)
  return {
    generalCondition: record?.general_condition || 'healthy',
    isDisplaced: record?.is_displaced ?? false,
    isRotated: record?.is_rotated ?? false
  }
}

function treatmentIncludesTooth(treatment: Treatment, toothNumber: number): boolean {
  return treatment.teeth.some(t => t.tooth_number === toothNumber)
}

/** Return per-tooth views for a given tooth number, honoring statusFilter. */
function getFilteredTreatments(toothNumber: number): ToothTreatmentView[] {
  const source: Treatment[] = isViewingHistory.value
    ? displayTreatments.value.filter(t => treatmentIncludesTooth(t, toothNumber))
    : getToothTreatments(toothNumber)

  const views = viewsForTooth(source, toothNumber)
  if (!props.statusFilter?.length) return views
  return views.filter(v => props.statusFilter?.includes(v.status))
}

/** Treatment id shared by all teeth of a multi-tooth treatment (used for connectors). */
function getToothGroupId(toothNumber: number): string | null {
  const list = getFilteredTreatments(toothNumber)
  const multi = list.find(v => v.is_multi)
  return multi?.treatment_id ?? null
}

function getToothGroupStatus(toothNumber: number): TreatmentStatus | null {
  const list = getFilteredTreatments(toothNumber)
  const multi = list.find(v => v.is_multi)
  return multi?.status ?? null
}

function getToothGroupType(toothNumber: number): string | null {
  const list = getFilteredTreatments(toothNumber)
  const multi = list.find(v => v.is_multi)
  return multi?.clinical_type ?? null
}

/** If the bridge crosses the midline (e.g. 12-11-21-22), both teeth belong
 *  to the same group and the connector sits in the quadrant divider slot. */
function midlineBridgeStatus(leftTooth: number, rightTooth: number): 'existing' | 'planned' | null {
  const leftId = getToothGroupId(leftTooth)
  const rightId = getToothGroupId(rightTooth)
  if (!leftId || leftId !== rightId) return null
  if (getToothGroupType(leftTooth) !== 'bridge') return null
  const status = getToothGroupStatus(leftTooth)
  if (status !== 'existing' && status !== 'planned') return null
  return status
}

const upperMidlineBridgeStatus = computed<'existing' | 'planned' | null>(() => {
  const right = teethLayout.value.upperRight
  const left = teethLayout.value.upperLeft
  const r = right[right.length - 1]
  const l = left[0]
  if (r === undefined || l === undefined) return null
  return midlineBridgeStatus(r, l)
})

const lowerMidlineBridgeStatus = computed<'existing' | 'planned' | null>(() => {
  const right = teethLayout.value.lowerRight
  const left = teethLayout.value.lowerLeft
  const r = right[right.length - 1]
  const l = left[0]
  if (r === undefined || l === undefined) return null
  return midlineBridgeStatus(r, l)
})

// ============================================================================
// Keyboard Shortcuts
// ============================================================================

function handleKeydown(e: KeyboardEvent) {
  if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

  if (e.key === 'Escape') {
    if (isMultiToothMode.value && multiToothSelection.value.teeth.length > 0) {
      resetMultiToothSelection()
      return
    }
    cancelClickToApplyMode()
    return
  }

  if (e.key === 'Enter' && isMultiToothMode.value) {
    // When the confirm popup is open it owns the confirm action (including
    // per-tooth role toggles for bridges); let it handle Enter natively.
    if (!showMultiToothConfirm.value) {
      requestMultiToothConfirm()
    }
    return
  }

  if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
    e.preventDefault()
    handleUndo()
    return
  }

  if (e.key.toLowerCase() === 'p') {
    selectedTreatmentStatus.value = 'planned'
    return
  }

  if (e.key.toLowerCase() === 'e') {
    selectedTreatmentStatus.value = 'existing'
    return
  }

  const shortcut = TREATMENT_SHORTCUTS[e.key]
  if (shortcut && !isReadonly.value) {
    selectedTreatmentType.value = shortcut
  }
}

// ============================================================================
// Click-to-Apply Mode
// ============================================================================

function handleSurfaceClick(toothNumber: number, surface: Surface) {
  if (isReadonly.value || !isClickToApplyMode.value) return
  if (!treatmentFits(toothNumber)) return

  // In multi-tooth mode, surface clicks collapse to tooth-level selection.
  if (isMultiToothMode.value) {
    handleMultiToothClick(toothNumber)
    return
  }

  if (isSurfaceTreatment(selectedTreatmentType.value!)) {
    applyTreatment(toothNumber, [surface])
  } else {
    applyTreatment(toothNumber)
  }
}

function handleToothClick(toothNumber: number) {
  // A read-only chart used to swallow the click in silence, which reads as a
  // broken odontogram: the "solo lectura" badge says the chart is frozen but
  // not what would thaw it. Report it upward instead of guessing — the answer
  // belongs to whoever set the mode.
  //
  // `isViewingHistory` is deliberately not reported: the timeline slider is
  // visibly holding the chart in the past and dragging it back to today is
  // the whole affordance, so there is nothing to explain.
  if (isReadonly.value) {
    if (props.mode === 'view-only' && !isViewingHistory.value) {
      emit('readonlyInteraction', toothNumber)
    }
    return
  }
  if (!isClickToApplyMode.value) {
    openEruption(toothNumber)
    return
  }
  if (!treatmentFits(toothNumber)) return

  if (isMultiToothMode.value) {
    handleMultiToothClick(toothNumber)
    return
  }

  if (isSurfaceTreatment(selectedTreatmentType.value!)) {
    selectedTooth.value = toothNumber
    showSurfaceSelector.value = true
  } else {
    applyTreatment(toothNumber)
  }
}

// Switching the view to a dentition the armed treatment is not offered on
// disarms it, as the bar no longer shows it.
watch(dentitionMode, (shown) => {
  const id = selectedCatalogItemId.value
  const item = id ? treatmentCatalog.treatments.value.find(c => c.id === id) : undefined
  if (item && !offeredOn(item.dentition, shown)) cancelClickToApplyMode()
})

/**
 * Whether the armed catalog treatment can be done on the tooth — a mixed
 * dentition shows primary and permanent teeth side by side, and the bar
 * offers both kinds. A treatment for the other one is refused with a word
 * instead of a server error (the server refuses it too).
 */
function treatmentFits(toothNumber: number): boolean {
  const id = selectedCatalogItemId.value
  if (!id) return true
  const item = treatmentCatalog.treatments.value.find(c => c.id === id)
  if (!item || fitsTooth(item.dentition, toothNumber)) return true
  const name = item.names[locale.value] || item.names.es || item.names.en || item.internal_code
  toast.add({
    title: t(
      item.dentition === 'deciduous' ? 'odontogram.dentition.deciduousOnly' : 'odontogram.dentition.permanentOnly',
      { treatment: name, tooth: toothNumber }
    ),
    color: 'warning'
  })
  return false
}

// ============================================================================
// Multi-tooth Selection
// ============================================================================

function handleMultiToothClick(toothNumber: number) {
  const cfg = multiToothConfig.value
  if (!cfg) return

  if (cfg.selectionMode === 'range') {
    if (multiToothSelection.value.anchor === null) {
      multiToothSelection.value = { teeth: [toothNumber], anchor: toothNumber }
      return
    }

    try {
      const range = calculateToothRange(multiToothSelection.value.anchor, toothNumber)
      if (range.length < cfg.minTeeth) {
        toast.add({
          title: t('odontogram.multiTooth.errors.tooFew', { n: cfg.minTeeth }),
          color: 'warning'
        })
        return
      }
      if (range.length > cfg.maxTeeth) {
        toast.add({
          title: t('odontogram.multiTooth.errors.tooMany', { n: cfg.maxTeeth }),
          color: 'warning'
        })
        return
      }
      multiToothSelection.value.teeth = range
      showMultiToothConfirm.value = true
    } catch {
      toast.add({
        title: t('odontogram.multiTooth.errors.sameArchRequired'),
        color: 'warning'
      })
    }
    return
  }

  // free selection mode
  const existing = multiToothSelection.value.teeth
  const idx = existing.indexOf(toothNumber)
  if (idx === -1) {
    const candidate = [...existing, toothNumber]
    if (cfg.requiresSameArch && !isSameArch(candidate)) {
      toast.add({
        title: t('odontogram.multiTooth.errors.sameArchRequired'),
        color: 'warning'
      })
      return
    }
    if (candidate.length > cfg.maxTeeth) {
      toast.add({
        title: t('odontogram.multiTooth.errors.tooMany', { n: cfg.maxTeeth }),
        color: 'warning'
      })
      return
    }
    multiToothSelection.value = { ...multiToothSelection.value, teeth: candidate }
  } else {
    multiToothSelection.value = {
      ...multiToothSelection.value,
      teeth: existing.filter(t => t !== toothNumber)
    }
  }
}

function canConfirmFreeSelection(): boolean {
  const cfg = multiToothConfig.value
  if (!cfg || cfg.selectionMode !== 'free') return false
  return multiToothSelection.value.teeth.length >= cfg.minTeeth
}

function requestMultiToothConfirm() {
  if (canConfirmFreeSelection()) {
    showMultiToothConfirm.value = true
  }
}

async function confirmMultiToothSelection(
  teethRoles: Array<{ tooth_number: number, role: 'pillar' | 'pontic' }> | null = null
) {
  const cfg = multiToothConfig.value
  if (!cfg) return
  const sortedTeeth = [...multiToothSelection.value.teeth].sort((a, b) => a - b)

  let status: TreatmentStatus = selectedTreatmentStatus.value
  if (isDiagnosisMode.value) status = 'existing'
  else if (isPlanningMode.value) status = 'planned'

  const payload: TreatmentCreate = {
    scope: 'multi_tooth',
    status
  }
  if (cfg.mode === 'bridge' && teethRoles && teethRoles.length > 0) {
    payload.teeth = teethRoles
  } else {
    payload.tooth_numbers = sortedTeeth
  }
  if (cfg.mode === 'uniform') {
    payload.clinical_type = cfg.key as ClinicalType
  } else {
    payload.clinical_type = 'bridge'
  }
  if (selectedCatalogItemId.value) {
    payload.catalog_item_id = selectedCatalogItemId.value
  }

  const created = await createTreatment(props.patientId, payload)
  if (!created) {
    showMultiToothConfirm.value = false
    return
  }

  if (isPlanningMode.value && props.planId) {
    await treatmentPlansApi.addItem(props.planId, { treatment_id: created.id })
  }

  undoStack.value.push({ treatmentId: created.id, type: cfg.key })
  resetMultiToothSelection()
  emit('treatmentAdd', created)
  emit('treatmentsChanged')
  // Selection is deliberately kept — see `applyTreatment`.
}

function resetMultiToothSelection() {
  multiToothSelection.value = { teeth: [], anchor: null }
  showMultiToothConfirm.value = false
}

function handleToothContextMenu(toothNumber: number, event: MouseEvent) {
  if (isReadonly.value) return
  event.preventDefault()
  openEruption(toothNumber)
}

async function applyTreatment(toothNumber: number, surfaces?: Surface[]) {
  if (!selectedTreatmentType.value && !selectedCatalogItemId.value) return

  let status: TreatmentStatus = selectedTreatmentStatus.value
  if (isDiagnosisMode.value) status = 'existing'
  else if (isPlanningMode.value) status = 'planned'

  const payload: TreatmentCreate = {
    tooth_numbers: [toothNumber],
    status,
    scope: 'tooth'
  }
  if (selectedCatalogItemId.value) {
    payload.catalog_item_id = selectedCatalogItemId.value
  }
  if (selectedTreatmentType.value) {
    payload.clinical_type = selectedTreatmentType.value as ClinicalType
  }
  if (surfaces?.length) payload.surfaces = surfaces

  const treatment = await createTreatment(props.patientId, payload)
  if (!treatment) return

  // In planning mode linked to a specific plan, attach the new Treatment as a
  // PlannedTreatmentItem so it shows up in the plan's list.
  if (isPlanningMode.value && props.planId) {
    await treatmentPlansApi.addItem(props.planId, { treatment_id: treatment.id })
  }

  undoStack.value.push({ treatmentId: treatment.id, type: treatment.clinical_type })

  toast.add({
    title: `${t(`odontogram.treatments.types.${treatment.clinical_type}`, treatment.clinical_type)} - ${t('odontogram.tooth')} ${toothNumber}`,
    description: t('odontogram.treatments.treatmentAdded'),
    color: 'success',
    // `onClick`, not `click`: Nuxt UI renders a toast action by spreading
    // the object onto a `UButton`, which declares `onClick` as a prop. A
    // `click` key lands as a plain attribute and is never called, so this
    // button did nothing at all. Ctrl+Z always worked — which is why the
    // undo path itself is fine and only the binding was wrong.
    actions: [{ label: t('common.undo'), onClick: handleUndo }]
  })

  emit('treatmentAdd', treatment)
  emit('treatmentsChanged')
  // The selection stays armed. Dental work comes in sets — four sealants,
  // a quadrant of scaling, composites on 16/26/36 — and clearing after every
  // tooth meant hunting the same chip out of a ~30-item list each time. The
  // badge in the header shows what is armed and releases it; so does Esc,
  // and every application still offers Undo in its toast.
}

function handleSurfaceConfirm(surfaces: Surface[]) {
  if (selectedTooth.value && surfaces.length) {
    applyTreatment(selectedTooth.value, surfaces)
  }
  selectedTooth.value = null
}

async function handleUndo() {
  const lastAction = undoStack.value.pop()
  if (!lastAction) return
  await deleteTreatment(lastAction.treatmentId)
  emit('treatmentsChanged')
  toast.add({ title: t('common.undone'), color: 'neutral' })
}

// ============================================================================
// Batch placement by quadrant
//
// Periodontal work is charted by quadrant, always; sealants go on the four
// first molars; cordales are four teeth. Placing those one tooth at a time
// was the remaining repetition after the selection was made sticky.
//
// Deliberately quadrant-only, and always behind a confirmation that names
// the teeth: eight treatments created by a mis-click have no bulk undo.
// ============================================================================

const batchQuadrant = ref<number | null>(null)
const batchApplying = ref(false)

/**
 * All teeth of the current dentition, flat. `teethLayout` is keyed by
 * quadrant for rendering; the batch maths wants the numbers.
 */
const allTeethFlat = computed(() => Object.values(teethLayout.value).flat() as number[])

/** Quadrants present in the current dentition, in FDI order. */
const availableQuadrants = computed(() => {
  const seen = new Set<number>()
  for (const n of allTeethFlat.value) seen.add(Math.floor(n / 10))
  return [...seen].sort((a, b) => a - b)
})

/**
 * Batch is offered only for a plain per-tooth treatment: a surface treatment
 * would need surfaces chosen per tooth, and a multi-tooth act (bridge,
 * splint) is one clinical decision spanning teeth, not many.
 */
const canBatchApply = computed(() =>
  isClickToApplyMode.value
  && !isMultiToothMode.value
  && !isReadonly.value
  && !isSurfaceTreatment(selectedTreatmentType.value!)
)

const batchTeeth = computed(() =>
  batchQuadrant.value === null
    ? []
    : allTeethFlat.value.filter(n => Math.floor(n / 10) === batchQuadrant.value)
)

async function confirmBatchApply() {
  const teeth = batchTeeth.value
  if (teeth.length === 0) return
  batchApplying.value = true
  try {
    // Sequential on purpose: each application creates a Treatment and a plan
    // item, and the backend assigns sequence_order from the current maximum.
    for (const toothNumber of teeth) {
      await applyTreatment(toothNumber)
    }
  } finally {
    batchApplying.value = false
    batchQuadrant.value = null
  }
}

function cancelClickToApplyMode() {
  selectedTreatmentType.value = null
  selectedCatalogItemId.value = null
  hoveredTooth.value = null
  resetMultiToothSelection()
}

// Global treatments are created inside TreatmentBar using its own useTreatments()
// instance, so the chart's local treatments[] doesn't see them — refetch so the
// globals strip and any parent listeners stay in sync.
async function handleGlobalTreatmentApplied(treatment: Treatment) {
  await fetchTreatments(props.patientId)
  emit('treatmentAdd', treatment)
  emit('treatmentsChanged')
}

// ============================================================================
// Treatment Editing
// ============================================================================

function handleEditTreatment(treatment: ToothTreatmentView) {
  editingTreatment.value = treatment
  showTreatmentEditModal.value = true
}

async function handleTreatmentUpdate(
  treatmentId: string,
  data: { status?: TreatmentStatus, notes?: string }
) {
  // `updateTreatment` returns null on failure (it has already toasted).
  // Closing the modal anyway is how surface edits disappeared behind an
  // error the user had no chance to act on.
  const saved = await updateTreatment(treatmentId, data)
  if (!saved) return
  emit('treatmentsChanged')
  showTreatmentEditModal.value = false
  editingTreatment.value = null
}

async function handleTreatmentDelete(treatmentId: string) {
  // A performed treatment may already be invoiced, and there is no undo
  // endpoint — it must not delete on a single click.
  if (!window.confirm(t('odontogram.confirms.deleteTreatment'))) return
  const deleted = await deleteTreatment(treatmentId)
  if (!deleted) return
  emit('treatmentsChanged')
  showTreatmentEditModal.value = false
  editingTreatment.value = null
}

async function handleTreatmentPerform(treatmentId: string) {
  const updated = await performTreatment(treatmentId)
  if (updated) emit('treatmentPerform', treatmentId)
  emit('treatmentsChanged')
  showTreatmentEditModal.value = false
  editingTreatment.value = null
}

// ============================================================================
// Timeline & History
// ============================================================================

async function handleTimelineDateChange(date: string | null) {
  if (date === null) {
    returnToCurrentView()
  } else {
    await fetchOdontogramAtDate(props.patientId, date)
  }
}

// The endpoint pages at 50 and reports the true count; taking `data` and
// dropping `total` is how the older half of a clinical history became
// invisible (audit S5).
const historyTotal = ref(0)
const historyPage = ref(1)
const historyLoadingMore = ref(false)

async function onHistoryExpanded(expanded: boolean) {
  if (expanded && !historyData.value.length) {
    historyLoading.value = true
    historyPage.value = 1
    const response = await fetchPatientHistory(props.patientId, historyPage.value)
    if (response) {
      historyData.value = response.data
      historyTotal.value = response.total
    }
    historyLoading.value = false
  }
}

async function onHistoryLoadMore() {
  if (historyLoadingMore.value) return
  historyLoadingMore.value = true
  try {
    const next = historyPage.value + 1
    const response = await fetchPatientHistory(props.patientId, next)
    if (response) {
      historyData.value = [...historyData.value, ...response.data]
      historyTotal.value = response.total
      historyPage.value = next
    }
  } finally {
    historyLoadingMore.value = false
  }
}

// Exposed so parents (PlanDetailView) can refresh the local treatments cache
// after mutations they own (remove item, complete item).
defineExpose({
  refetchTreatments: () => fetchTreatments(props.patientId)
})
</script>

<template>
  <div class="odontogram-chart">
    <!-- Header -->
    <!-- Wraps: four dentitions do not fit beside the title in a card. -->
    <div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 mb-4">
      <div class="flex items-center gap-2">
        <h3 class="text-h1 text-default">
          {{ t('odontogram.title') }}
        </h3>
        <UBadge
          v-if="mode === 'view-only'"
          :label="t('odontogram.readOnly')"
          color="neutral"
          variant="subtle"
        />
        <UBadge
          v-if="mode === 'planning'"
          :label="t('odontogram.planning')"
          color="warning"
          variant="subtle"
        />
        <!-- Armed treatment. It survives each application on purpose, so it
             has to be obvious what is armed and how to put it down. -->
        <div
          v-if="isClickToApplyMode"
          class="armed-chip"
        >
          <UBadge
            :label="multiToothConfig
              ? t(multiToothConfig.labelKey)
              : t(`odontogram.treatments.types.${selectedTreatmentType}`)"
            color="primary"
            variant="solid"
          />
          <UButton
            size="xs"
            variant="ghost"
            color="neutral"
            icon="i-lucide-x"
            :title="t('odontogram.releaseTreatment')"
            :aria-label="t('odontogram.releaseTreatment')"
            @click="cancelClickToApplyMode"
          />
        </div>

        <!-- Whole-quadrant placement for the armed treatment. -->
        <div
          v-if="canBatchApply"
          class="flex items-center gap-1"
        >
          <span class="text-caption text-subtle">{{ t('odontogram.batch.label') }}</span>
          <UButton
            v-for="quadrant in availableQuadrants"
            :key="quadrant"
            size="xs"
            variant="outline"
            color="neutral"
            :title="t('odontogram.batch.quadrantTitle', { quadrant })"
            @click="batchQuadrant = quadrant"
          >
            {{ quadrant }}
          </UButton>
        </div>
      </div>

      <!-- Dentition toggle -->
      <div class="flex flex-col items-start gap-1 max-w-full overflow-x-auto">
        <SegmentedControl
          :model-value="chosenDentition"
          :options="dentitionOptions"
          data-testid="odontogram-dentition"
          @update:model-value="(v) => chooseDentition(v as Dentition)"
        />
        <span
          class="text-caption text-subtle"
          data-testid="odontogram-dentition-hint"
        >
          {{ dentitionHint }}
        </span>
        <div class="flex flex-wrap items-center gap-2">
          <SegmentedControl
            :model-value="chartView"
            :options="chartViewOptions"
            data-testid="odontogram-view"
            @update:model-value="(v) => chooseChartView(v as ChartView)"
          />
          <UButton
            icon="i-lucide-columns-2"
            size="xs"
            color="neutral"
            variant="ghost"
            data-testid="odontogram-compare-open"
            @click="compareOpen = true"
          >
            {{ t('odontogram.compare.open') }}
          </UButton>
          <UButton
            icon="i-lucide-printer"
            size="xs"
            color="neutral"
            variant="ghost"
            :to="`/odontogram/${patientId}/print`"
            target="_blank"
            data-testid="odontogram-print"
          >
            {{ t('odontogram.print.open') }}
          </UButton>
        </div>
        <div
          class="flex flex-wrap items-center gap-2"
          data-testid="odontogram-indices"
        >
          <UTooltip
            v-if="showCpod"
            :text="t('odontogram.indices.cpodHelp')"
          >
            <span
              class="inline-flex items-baseline gap-1.5 rounded-token-md border border-subtle px-2 py-0.5 text-caption"
              data-testid="odontogram-index-cpod"
            >
              <span class="font-semibold text-default">{{ t('odontogram.indices.cpod') }} {{ indices.cpod.total }}</span>
              <span class="text-subtle">{{ t('odontogram.indices.cpodParts', indices.cpod) }}</span>
            </span>
          </UTooltip>
          <UTooltip
            v-if="showCeod"
            :text="t('odontogram.indices.ceodHelp')"
          >
            <span
              class="inline-flex items-baseline gap-1.5 rounded-token-md border border-subtle px-2 py-0.5 text-caption"
              data-testid="odontogram-index-ceod"
            >
              <span class="font-semibold text-default">{{ t('odontogram.indices.ceod') }} {{ indices.ceod.total }}</span>
              <span class="text-subtle">{{ t('odontogram.indices.ceodParts', indices.ceod) }}</span>
            </span>
          </UTooltip>
        </div>
      </div>
    </div>

    <!-- What the eruption charted so far warns of: a primary tooth kept too
         long, a permanent one late. Advice, never a stop. -->
    <UAlert
      v-if="alerts.length"
      color="warning"
      variant="subtle"
      icon="i-lucide-baby"
      class="mb-4"
      :title="t('odontogram.eruption.alertsTitle')"
      data-testid="odontogram-eruption-alerts"
    >
      <template #description>
        <ul class="list-disc pl-4 space-y-0.5">
          <li
            v-for="alert in alerts"
            :key="`${alert.kind}-${alert.tooth}`"
          >
            {{ alert.kind === 'retained_primary'
              ? t('odontogram.eruption.alerts.retainedPrimary', { tooth: alert.tooth, successor: alert.successor, age: alert.usualAge })
              : t('odontogram.eruption.alerts.delayedEruption', { tooth: alert.tooth, age: alert.usualAge }) }}
          </li>
        </ul>
      </template>
    </UAlert>

    <!-- Timeline Slider (only in standalone 'full' mode; HistoryMode renders its own) -->
    <TimelineSlider
      v-if="mode === 'full' && timelineDates.length > 1"
      :dates="timelineDates"
      :current-date="viewingDate"
      :disabled="timelineLoading"
      class="mb-4"
      @update:current-date="handleTimelineDateChange"
    />

    <!-- Loading -->
    <div
      v-if="loading || treatmentsLoading || timelineLoading"
      class="flex items-center justify-center py-16"
    >
      <UIcon
        name="i-lucide-loader-2"
        class="w-8 h-8 animate-spin text-subtle"
      />
    </div>

    <!-- Load error — never fall through to a fabricated healthy mouth. -->
    <UAlert
      v-else-if="error"
      icon="i-lucide-triangle-alert"
      color="error"
      variant="subtle"
      :title="t('odontogram.messages.loadError')"
      :actions="[{
        label: t('common.retry'),
        color: 'error',
        variant: 'soft',
        onClick: () => loadAll(props.patientId)
      }]"
    />

    <!-- Chart -->
    <div
      v-else
      class="flex flex-col gap-4"
    >
      <div class="odontogram-wrapper">
        <!-- data-dense: an arch is anatomy, not a toolbar. Sixteen teeth
             sit side by side, so a cell's width is whatever the arch
             divides into — 24 px on an upright tablet — and growing each
             to 44 px would need 704 px and break the arch it is drawing.
             The pairing the marker requires is real and already here: a
             tap anywhere on the tooth opens a panel whose own rows are
             44 px, so the small target leads somewhere finger-sized
             rather than being the end of the interaction. -->
        <div
          v-if="chartView === 'anatomical'"
          data-dense
          class="odontogram-grid bg-surface rounded-lg border border-default p-4"
          :class="{ 'cursor-crosshair': isClickToApplyMode }"
        >
          <!-- Upper arch -->
          <div
            class="mb-6 arch-container"
            :class="{ 'arch-halo': hoveredArch === 'upper' }"
          >
            <div class="text-caption text-subtle text-center mb-2">
              {{ t('odontogram.quadrants.upper') }}
            </div>
            <div class="flex justify-center gap-1 relative">
              <div
                v-if="upperMidlineBridgeStatus"
                class="midline-bridge upper"
                :class="'status-' + upperMidlineBridgeStatus"
              />
              <ToothQuadrant
                :teeth="teethLayout.upperRight"
                :get-tooth-data="getToothData"
                :get-treatments="getFilteredTreatments"
                :readonly="isReadonly"
                :selected-tooth="selectedTooth"
                :show-lateral="showLateral"
                :hovered-tooth="hoveredTooth"
                :highlighted-teeth="highlightedTeeth"
                :pending-treatment="pendingTreatment"
                :get-group-id="getToothGroupId"
                :get-group-status="getToothGroupStatus"
                :get-group-type="getToothGroupType"
                :multi-selected-teeth="multiToothSelection.teeth"
                :dimmed-teeth="dimmedTeeth"
                :get-eruption-status="chartFacts.statusOf"
                @surface-click="handleSurfaceClick"
                @tooth-click="handleToothClick"
                @tooth-context-menu="handleToothContextMenu"
                @tooth-hover="hoveredTooth = $event"
                @edit-treatment="handleEditTreatment"
              />

              <div class="w-px bg-surface-sunken  mx-2" />

              <ToothQuadrant
                :teeth="teethLayout.upperLeft"
                :get-tooth-data="getToothData"
                :get-treatments="getFilteredTreatments"
                :readonly="isReadonly"
                :selected-tooth="selectedTooth"
                :show-lateral="showLateral"
                :hovered-tooth="hoveredTooth"
                :highlighted-teeth="highlightedTeeth"
                :pending-treatment="pendingTreatment"
                :get-group-id="getToothGroupId"
                :get-group-status="getToothGroupStatus"
                :get-group-type="getToothGroupType"
                :multi-selected-teeth="multiToothSelection.teeth"
                :dimmed-teeth="dimmedTeeth"
                :get-eruption-status="chartFacts.statusOf"
                @surface-click="handleSurfaceClick"
                @tooth-click="handleToothClick"
                @tooth-context-menu="handleToothContextMenu"
                @tooth-hover="hoveredTooth = $event"
                @edit-treatment="handleEditTreatment"
              />
            </div>
          </div>

          <div class="h-px bg-surface-sunken my-4" />

          <!-- Lower arch -->
          <div
            class="arch-container"
            :class="{ 'arch-halo': hoveredArch === 'lower' }"
          >
            <div class="flex justify-center gap-1 relative">
              <div
                v-if="lowerMidlineBridgeStatus"
                class="midline-bridge lower"
                :class="'status-' + lowerMidlineBridgeStatus"
              />
              <ToothQuadrant
                :teeth="teethLayout.lowerRight"
                :get-tooth-data="getToothData"
                :get-treatments="getFilteredTreatments"
                :readonly="isReadonly"
                :selected-tooth="selectedTooth"
                :show-lateral="showLateral"
                :hovered-tooth="hoveredTooth"
                :highlighted-teeth="highlightedTeeth"
                :pending-treatment="pendingTreatment"
                :get-group-id="getToothGroupId"
                :get-group-status="getToothGroupStatus"
                :get-group-type="getToothGroupType"
                :multi-selected-teeth="multiToothSelection.teeth"
                :dimmed-teeth="dimmedTeeth"
                :get-eruption-status="chartFacts.statusOf"
                @surface-click="handleSurfaceClick"
                @tooth-click="handleToothClick"
                @tooth-context-menu="handleToothContextMenu"
                @tooth-hover="hoveredTooth = $event"
                @edit-treatment="handleEditTreatment"
              />

              <div class="w-px bg-surface-sunken  mx-2" />

              <ToothQuadrant
                :teeth="teethLayout.lowerLeft"
                :get-tooth-data="getToothData"
                :get-treatments="getFilteredTreatments"
                :readonly="isReadonly"
                :selected-tooth="selectedTooth"
                :show-lateral="showLateral"
                :hovered-tooth="hoveredTooth"
                :highlighted-teeth="highlightedTeeth"
                :pending-treatment="pendingTreatment"
                :get-group-id="getToothGroupId"
                :get-group-status="getToothGroupStatus"
                :get-group-type="getToothGroupType"
                :multi-selected-teeth="multiToothSelection.teeth"
                :dimmed-teeth="dimmedTeeth"
                :get-eruption-status="chartFacts.statusOf"
                @surface-click="handleSurfaceClick"
                @tooth-click="handleToothClick"
                @tooth-context-menu="handleToothContextMenu"
                @tooth-hover="hoveredTooth = $event"
                @edit-treatment="handleEditTreatment"
              />
            </div>
            <div class="text-caption text-subtle text-center mt-2">
              {{ t('odontogram.quadrants.lower') }}
            </div>
          </div>
        </div>
        <!-- data-dense: the same reasoning as the anatomical arch — a box is a
             tooth, and a tap on it leads to finger-sized panels. -->
        <div
          v-else
          data-dense
          class="bg-surface rounded-lg border border-default p-4"
          :class="{ 'cursor-crosshair': isClickToApplyMode }"
          data-testid="odontogram-box-chart"
        >
          <ToothBoxChart
            :dentition="dentitionMode"
            :get-treatments="getFilteredTreatments"
            :get-condition="(tooth: number) => getToothRecord(tooth)?.general_condition"
            :dimmed-teeth="boxDimmedTeeth"
            :readonly="isReadonly"
            :selected-tooth="selectedTooth"
            :hovered-tooth="hoveredTooth"
            :highlighted-teeth="[...highlightedTeeth, ...multiToothSelection.teeth]"
            @surface-click="handleSurfaceClick"
            @tooth-click="handleToothClick"
            @tooth-context-menu="handleToothContextMenu"
            @tooth-hover="hoveredTooth = $event"
          />
        </div>
      </div>

      <!-- Globals strip (boca completa / arcada) — sits between the chart and the
           treatment bar so the dentist sees active global treatments without
           scrolling. -->
      <GlobalTreatmentsStrip
        :treatments="displayTreatments"
        :highlighted-ids="highlightedGlobalIds"
        @treatment-hover="handleGlobalHover"
        @arch-hover="handleArchHover"
      />

      <!-- Treatment Bar -->
      <TreatmentBar
        v-if="!isReadonly"
        v-model:selected-treatment="selectedTreatmentType"
        v-model:selected-catalog-item-id="selectedCatalogItemId"
        :selected-status="selectedTreatmentStatus"
        :selected-plan-id="planId"
        :plan-context-title="planTitle"
        :patient-id="patientId"
        :mode="treatmentBarMode"
        :hidden-categories="dentitionMode === 'permanent' ? ['pediatrica'] : []"
        :shown-dentition="dentitionMode"
        :disabled="isReadonly"
        @update:selected-status="selectedTreatmentStatus = $event"
        @treatment-select="selectedTreatmentType = $event"
        @treatment-applied="handleGlobalTreatmentApplied"
        @cancel="cancelClickToApplyMode"
      />

      <!-- Legend -->
      <OdontogramLegend />

      <!-- Treatment List (only in standalone 'full' mode; other modes' parents render their own) -->
      <TreatmentListSection
        v-if="mode === 'full'"
        :treatments="treatments"
      />

      <!-- History (only in standalone 'full' mode) -->
      <ChangeHistorySection
        v-if="mode === 'full'"
        :history="historyData"
        :treatments="treatments"
        :loading="historyLoading"
        :total="historyTotal"
        :loading-more="historyLoadingMore"
        @update:expanded="onHistoryExpanded"
        @load-more="onHistoryLoadMore"
      />
    </div>

    <!-- Surface selector popup -->
    <OdontogramCompare
      :open="compareOpen"
      :patient-id="patientId"
      :dentition="chosenDentition"
      :eruption-ages="odontogramData?.eruption_ages"
      @close="compareOpen = false"
    />

    <SurfaceSelectorPopup
      v-model:open="showSurfaceSelector"
      :tooth-number="selectedTooth || 0"
      :treatment-type="(selectedTreatmentType as ClinicalType) || 'filling_composite'"
      :status="selectedTreatmentStatus"
      @confirm="handleSurfaceConfirm"
      @cancel="selectedTooth = null"
    />

    <!-- Treatment edit modal -->
    <TreatmentEditModal
      v-model:open="showTreatmentEditModal"
      :treatment="editingTreatment"
      @update="handleTreatmentUpdate"
      @delete="handleTreatmentDelete"
      @perform="handleTreatmentPerform"
    />

    <!-- Multi-tooth confirmation popup -->
    <MultiToothConfirmPopup
      v-if="multiToothConfig"
      v-model:open="showMultiToothConfirm"
      :config="multiToothConfig"
      :teeth="multiToothSelection.teeth"
      :status="isDiagnosisMode ? 'existing' : isPlanningMode ? 'planned' : selectedTreatmentStatus"
      @confirm="confirmMultiToothSelection"
      @cancel="resetMultiToothSelection"
    />

    <!-- Free-mode selection summary bar (prompts user to confirm) -->
    <div
      v-if="multiToothConfig && multiToothConfig.selectionMode === 'free' && multiToothSelection.teeth.length > 0 && !showMultiToothConfirm"
      class="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 rounded-lg border border-default bg-surface shadow-lg px-4 py-2"
    >
      <UIcon
        name="i-lucide-link"
        class="w-4 h-4 text-primary"
      />
      <span class="text-sm font-medium">
        {{ t(multiToothConfig.labelKey) }}
      </span>
      <UBadge
        color="primary"
        variant="subtle"
      >
        {{ multiToothSelection.teeth.length }}
      </UBadge>
      <UButton
        size="xs"
        variant="ghost"
        @click="resetMultiToothSelection"
      >
        {{ t('common.cancel') }}
      </UButton>
      <UButton
        size="xs"
        color="primary"
        :disabled="!canConfirmFreeSelection()"
        @click="requestMultiToothConfirm"
      >
        {{ t('common.confirm') }}
      </UButton>
    </div>

    <!-- Confirm a whole-quadrant placement. Named teeth, not just a count:
         eight treatments created by mistake have no bulk undo. -->
    <UModal
      :open="batchQuadrant !== null"
      @update:open="(v) => { if (!v) batchQuadrant = null }"
    >
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-h3">
              {{ t('odontogram.batch.confirmTitle', { quadrant: batchQuadrant }) }}
            </h3>
          </template>

          <p class="text-sm">
            {{ t('odontogram.batch.confirmBody', {
              treatment: selectedTreatmentType
                ? t(`odontogram.treatments.types.${selectedTreatmentType}`)
                : '',
              count: batchTeeth.length,
              teeth: batchTeeth.join(', ')
            }) }}
          </p>

          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                variant="ghost"
                color="neutral"
                @click="batchQuadrant = null"
              >
                {{ t('actions.cancel') }}
              </UButton>
              <UButton
                :loading="batchApplying"
                @click="confirmBatchApply"
              >
                {{ t('odontogram.batch.confirmAction') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <ToothEruptionModal
      :tooth-number="eruptionTooth"
      :patient-id="patientId"
      :status="eruptionTooth === null ? null : (chartFacts.statusOf?.(eruptionTooth) ?? null)"
      @close="eruptionTooth = null"
      @changed="onEruptionChanged"
    />
  </div>
</template>

<style scoped>
/* Armed-treatment chip: the badge plus its release button read as one
   control, so the ✕ is unmistakably "put this down", not "delete something". */
.armed-chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding-right: 2px;
  border-radius: 999px;
  background: var(--color-primary-soft, rgba(59, 130, 246, 0.12));
}

.odontogram-wrapper {
  container-type: inline-size;
  /* Was `overflow: hidden`, which silently amputated the chart. The zoom
     ladder below bottoms out at 0.5, and even there the arches need
     ~491px; a tablet held upright gives this wrapper ~472px inside the
     plan detail, so the last molar of each quadrant — 18, 28, 48, 38 —
     was cut off with no way to reach it.

     Scrolling sideways is the floor of the fix rather than shrinking
     further: these are anatomy cells being tapped with a finger, and
     making them smaller to dodge a scrollbar trades a real problem for
     a worse one. The extra zoom steps below mean the common tablet
     widths still fit without scrolling at all. */
  overflow-x: auto;
  overflow-y: hidden;
}

/* Arch halo: highlights the upper or lower arch when the user hovers a global_arch
   chip in the globals strip. Paints a subtle blue outline around the full arch. */
.arch-container {
  position: relative;
  border-radius: 12px;
  transition: background 0.2s ease, box-shadow 0.2s ease;
}

.arch-container.arch-halo {
  background: rgba(59, 130, 246, 0.08);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.35), 0 4px 12px rgba(59, 130, 246, 0.15);
}

:root.dark .arch-container.arch-halo {
  background: rgba(59, 130, 246, 0.18);
}

.odontogram-grid {
  zoom: 1;
  /* Centred *and* scrollable. The arches are centred, and a centred flex
     row that outgrows its container spills equally off both sides — but
     `scrollLeft` cannot go negative, so the left spill (the upper-right
     and lower-right quadrants, 18/17/16…) becomes unreachable no matter
     how far you pan. Sizing the grid to its content and centring it with
     auto margins instead keeps it centred while there is room and
     collapses the margins to zero once there is not, so everything the
     chart draws stays inside the scrollable area. */
  width: max-content;
  margin-inline: auto;
}

/* Container queries - respond to actual container width, not viewport.
   The ladder starts at 1060px, not 1000: unzoomed the arches measure
   ~1047px, so a container between those two figures could not fit the
   chart and no step had kicked in yet — which under the old
   `overflow: hidden` clipped the outer molars on a plain desktop too. */
@container (max-width: 1060px) {
  .odontogram-grid {
    zoom: 0.9;
  }
}

@container (max-width: 900px) {
  .odontogram-grid {
    zoom: 0.8;
  }
}

@container (max-width: 800px) {
  .odontogram-grid {
    zoom: 0.7;
  }
}

@container (max-width: 700px) {
  .odontogram-grid {
    zoom: 0.6;
  }
}

@container (max-width: 600px) {
  .odontogram-grid {
    zoom: 0.5;
  }
}

/* Below 520px the 0.5 step no longer fits — the arches want ~491px — so
   the ladder has to keep going or the outer molars fall off the edge.
   A tablet in portrait lands in the first of these. */
@container (max-width: 520px) {
  .odontogram-grid {
    zoom: 0.45;
  }
}

@container (max-width: 460px) {
  .odontogram-grid {
    zoom: 0.4;
  }
}

/* Midline bridge connector: absolute overlay so the vertical divider keeps
   its original 17px footprint and teeth columns stay aligned across arches. */
.midline-bridge {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: 56px;
  height: 12px;
  border-radius: 2px;
  background: #F59E0B;
  pointer-events: none;
  z-index: 1;
}

.midline-bridge.upper {
  top: 88px;
}

.midline-bridge.lower {
  top: 78px;
}

.midline-bridge.status-planned {
  background: repeating-linear-gradient(
    90deg,
    #F59E0B 0,
    #F59E0B 4px,
    transparent 4px,
    transparent 8px
  );
}

.midline-bridge.status-existing {
  background: #F59E0B;
}
</style>
