<script setup lang="ts">
/**
 * PlanDetailView - Expanded view of a treatment plan
 *
 * Features:
 * - Odontogram with plan treatments highlighted
 * - Treatment list with hover linking
 * - Actions: activate, generate budget, add treatments
 * - Two-column layout on larger screens
 */

import type { BadgeProps, DropdownMenuItem } from '@nuxt/ui'
import type { ApiResponse, PlannedTreatmentItem, TreatmentPhase, TreatmentPlanDetail } from '~~/app/types'
import { phaseLabelKey, phaseRank } from '~~/app/config/treatmentPhases'
import { PERMISSIONS } from '~~/app/config/permissions'

import ConfirmPlanModal from './modals/ConfirmPlanModal.vue'
import ReopenPlanModal from './modals/ReopenPlanModal.vue'
import type { PlanHistoryEntry } from '../../composables/usePlanHistory'
import ClosePlanModal from './modals/ClosePlanModal.vue'
import ReactivatePlanModal from './modals/ReactivatePlanModal.vue'
import ContactLogModal from './modals/ContactLogModal.vue'
import PlanItemDetailModal from './modals/PlanItemDetailModal.vue'
import PlanItemCollectPrompt from './modals/PlanItemCollectPrompt.vue'
import PlanDiagnosisCard from './PlanDiagnosisCard.vue'
import PlanNextActionBar from './PlanNextActionBar.vue'
import { planItemName } from './planItemName'

const props = withDefaults(defineProps<{
  plan: TreatmentPlanDetail
  patientId: string
  readonly?: boolean
  /** Standalone mode: show patient link */
  standalone?: boolean
}>(), {
  standalone: false
})

const emit = defineEmits<{
  'updated': []
  'generate-budget': []
  'schedule': []
  'cancelled': []
}>()

const { t, locale } = useI18n()
const toast = useToast()
const api = useApi()
const { can } = usePermissions()

const {
  completeItem,
  reopenItem,
  completeSession,
  cancelSession,
  removeItem,
  reorderItems,
  changeItemDoctor,
  fetchPlan,
  loading,
  confirmPlan,
  reopenPlan,
  closePlan,
  reactivatePlan,
  logContact
} = useTreatmentPlans()

// ============================================================================
// Workflow modals — owned by this view so any parent (standalone page,
// patient ficha clinical tab, sidebar mini-views) gets the same flow
// without re-wiring events.
// ============================================================================

const showConfirmModal = ref(false)
const showReopenModal = ref(false)
const showCloseModal = ref(false)
const showReactivateModal = ref(false)
const showContactLogModal = ref(false)
const transitioning = ref(false)

const planSummary = computed(() => {
  const total = props.plan.items.reduce((acc, item) => {
    const price = item.treatment?.price_snapshot
    return acc + (typeof price === 'number' ? price : Number(price) || 0)
  }, 0)
  return {
    number: props.plan.plan_number,
    count: props.plan.items.length,
    total
  }
})

async function refreshPlan() {
  await fetchPlan(props.plan.id)
  emit('updated')
  await nextTick()
}

async function onConfirmPlan() {
  transitioning.value = true
  try {
    const result = await confirmPlan(props.plan.id, props.plan.patient_id, () => {
      showConfirmModal.value = false
      pendingItemIntent.value = null
    })
    if (result) {
      showConfirmModal.value = false
      await refreshPlan()
      emit('updated')
      // Carry out what they asked for before the dialog interrupted them.
      const intent = pendingItemIntent.value
      pendingItemIntent.value = null
      if (intent?.type === 'complete') {
        await completeItemNow(intent.itemId, { noteBody: null })
      } else if (intent?.type === 'collect') {
        openItemId.value = intent.itemId
      }
    }
  } finally {
    transitioning.value = false
  }
}

async function onReopenPlan() {
  transitioning.value = true
  try {
    const result = await reopenPlan(props.plan.id)
    if (result) {
      showReopenModal.value = false
      await refreshPlan()
    }
  } finally {
    transitioning.value = false
  }
}

async function onClosePlanSubmit(payload: { closure_reason: string, closure_note?: string }) {
  transitioning.value = true
  try {
    const result = await closePlan(props.plan.id, payload)
    if (result) {
      showCloseModal.value = false
      await refreshPlan()
      emit('cancelled')
    }
  } finally {
    transitioning.value = false
  }
}

async function onReactivatePlan() {
  transitioning.value = true
  try {
    const result = await reactivatePlan(props.plan.id)
    if (result) {
      showReactivateModal.value = false
      await refreshPlan()
    }
  } finally {
    transitioning.value = false
  }
}

async function onLogContact(payload: { channel: string, note?: string }) {
  transitioning.value = true
  try {
    const ok = await logContact(props.plan.id, payload)
    if (ok) showContactLogModal.value = false
  } finally {
    transitioning.value = false
  }
}

// Cross-module composable provided by the clinical_notes layer. Frontend
// auto-imports resolve to that layer's implementation.
const { createNote: createTreatmentNoteRaw } = useClinicalNotes()

async function createTreatmentNote(treatmentId: string, body: string) {
  await createTreatmentNoteRaw({
    note_type: 'treatment',
    owner_type: 'treatment',
    owner_id: treatmentId,
    body
  })
}

// ============================================================================
// Lock state — the banner that says the plan's shape is settled.
//
// It used to key off the budget: a plan with any non-cancelled budget was
// "bloqueado". That disagreed with the rule the screen actually enforces
// (`effectiveReadonly`, below), in both directions — an `active` plan with
// no budget was locked and said nothing, and the banner kept shouting at a
// `completed` plan where there is nothing left to lock.
//
// It also shouted in amber. A plan in progress with a signed budget is the
// healthy, everyday state, not a warning; painting it the colour of a
// problem every single day is how a warning stops being read.
// ============================================================================

/** Structural edits are off: true for everything that is not a draft. */
const isLocked = computed(() => !props.readonly && props.plan.status !== 'draft')

/**
 * Three sentences, because "settled", "finished" and "closed" are not the
 * same lock — and only the last one has a button. Telling a *completed*
 * plan to "reactivate" pointed at a control that is only drawn for a closed
 * one; the way back from completed is reopening a treatment.
 */
const lockedCopy = computed(() => {
  const status = props.plan.status
  const number = props.plan.budget?.budget_number

  if (status === 'closed') {
    return {
      title: t('clinical.plans.locked.overTitle'),
      subtitle: t('clinical.plans.locked.closedSubtitle')
    }
  }
  if (status === 'completed') {
    return {
      title: t('clinical.plans.locked.overTitle'),
      subtitle: t('clinical.plans.locked.completedSubtitle')
    }
  }
  return {
    title: t('clinical.plans.locked.title'),
    subtitle: t(
      number ? 'clinical.plans.locked.subtitle' : 'clinical.plans.locked.subtitleNoBudget',
      { number }
    )
  }
})

/** The link is only worth offering while the budget is still a live document. */
const liveBudgetId = computed(() =>
  props.plan.budget_id && props.plan.budget?.status !== 'cancelled' ? props.plan.budget_id : null
)

/**
 * Structural edits belong to a draft, and to nothing else.
 *
 * This used to key off the *budget* (`isLocked`), which left an `active`
 * plan with no budget fully editable — a plan under way that anyone could
 * rewrite. The plan's own status is the rule now: draft edits, everything
 * else asks to reopen first.
 */
const effectiveReadonly = computed(() => props.readonly || props.plan.status !== 'draft')

/** Confirmed and under way: what the clinic has committed to doing. */
const inProgress = computed(() =>
  props.plan.status === 'pending' || props.plan.status === 'active'
)

/**
 * Completing and charging belong to a plan in progress; a draft is a
 * proposal. Offered on a draft too, because refusing in silence teaches
 * nobody — pressing either opens the confirm dialog (`pendingItemIntent`).
 */
const canCompleteItems = computed(() =>
  !props.readonly
  && can(PERMISSIONS.treatmentPlans.write)
  && (isDraft.value || inProgress.value)
)

/**
 * A tooth was clicked on a chart this view has frozen.
 *
 * The locked banner sits at the top of the page and the odontogram is a
 * scroll below it, so the first thing a user does on a plan in progress is
 * click a tooth and watch nothing happen. The chart cannot explain itself —
 * it is handed `view-only` and never learns why — so the answer is composed
 * here, where the plan's status and the caller's rights are known.
 *
 * The branches follow the buttons that are actually on screen: the toast
 * never offers `Reabrir` unless the header is offering it too, because a
 * toast that proposes an action the user cannot take is worse than silence.
 */
function handleReadonlyChartClick(toothNumber: number) {
  // A stable id merges repeat clicks into the one toast instead of stacking
  // a column of them (Nuxt UI `mergeDuplicate`).
  const id = 'plan-chart-locked'

  // A plan under way is closed for editing but open for **adding**: the
  // caries found today is not a change to what the patient agreed, and the
  // chart is where a dentist points at it. What it costs is priced later by
  // an addendum; the signed budget is never touched.
  //
  // Offered as a second action rather than by unlocking the chart, because
  // an unlocked chart also deletes, and deleting is the thing being
  // protected.
  const canAdd
    = !props.readonly
      && can(PERMISSIONS.treatmentPlans.write)
      && (props.plan.status === 'pending' || props.plan.status === 'active')
  const addAction = canAdd
    ? [{
        label: t('clinical.plans.chartLocked.addHere', { tooth: toothNumber }),
        icon: 'i-lucide-plus',
        color: 'primary' as const,
        variant: 'soft' as const,
        onClick: () => openAddTreatment(toothNumber)
      }]
    : []

  if (props.readonly) {
    toast.add({
      id,
      title: t('clinical.plans.chartLocked.title'),
      description: t('clinical.plans.chartLocked.noPermission'),
      color: 'neutral',
      icon: 'i-lucide-lock'
    })
    return
  }

  if (planPermissions.value.can_reopen) {
    toast.add({
      id,
      title: t('clinical.plans.chartLocked.title'),
      description: t('clinical.plans.chartLocked.reopenToEdit'),
      color: 'warning',
      icon: 'i-lucide-lock',
      actions: [
        ...addAction,
        {
          label: t('treatmentPlans.actions.reopen'),
          icon: 'i-lucide-undo-2',
          color: 'warning' as const,
          variant: 'soft' as const,
          // Opens the same confirmation modal as the header button. Reopening
          // throws away a budget the patient may have seen, so the toast is a
          // shortcut to the decision, never the decision itself.
          onClick: () => { showReopenModal.value = true }
        }
      ]
    })
    return
  }

  const inProgress = props.plan.status === 'pending' || props.plan.status === 'active'
  toast.add({
    id,
    title: t('clinical.plans.chartLocked.title'),
    description: inProgress
      ? t('clinical.plans.chartLocked.reopenNotYours')
      : t('clinical.plans.chartLocked.closed'),
    color: 'neutral',
    icon: 'i-lucide-lock',
    // Adding does not need the reopen right: it takes nothing away from
    // what the patient agreed to.
    actions: addAction
  })
}

// ============================================================================
// ============================================================================
// Change log
// ============================================================================

const {
  entries: historyEntries,
  permissions: planPermissions,
  fetchHistory
} = usePlanHistory()

// Derived from the badge's own prop rather than restated as a string: the
// palette is Nuxt UI's, and a plain `string` here is what let a typo reach
// the template.
type HistoryColor = BadgeProps['color']

const HISTORY_COLORS: Record<string, HistoryColor> = {
  confirmed: 'info',
  started: 'success',
  completed: 'success',
  reopened: 'warning',
  reassigned: 'warning',
  closed: 'error',
  reactivated: 'info',
  item_added: 'neutral',
  item_removed: 'neutral',
  item_reopened: 'warning'
}

function historyColor(action: string): HistoryColor {
  return HISTORY_COLORS[action] || 'neutral'
}

/** The one detail that makes an entry worth reading, if it has one. */
function historyDetail(entry: PlanHistoryEntry): string {
  const p = entry.payload || {}
  if (entry.action === 'reassigned') {
    return [p.from, p.to].filter(Boolean).join(' → ')
  }
  if (entry.action === 'reopened' && p.cancelled_budget) {
    return String(p.cancelled_budget)
  }
  if (entry.action === 'closed') {
    return [p.reason, p.note].filter(Boolean).join(' · ')
  }
  return String(p.treatment || p.budget || p.budget_number || '')
}

function formatHistoryDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(locale.value, {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return iso
  }
}

// Reloaded on every transition, not just on mount: the actions on this
// page are exactly the ones that write to the log, so a stale panel
// would be missing the entry the user just caused.
watch(
  () => [props.plan.id, props.plan.status],
  () => fetchHistory(props.plan.id),
  { immediate: true }
)

// Cancel plan — delegated to the parent's ClosePlanModal. The legacy in-line
// modal kept for status-only cancellation (without closure_reason); the new
// flow surfaces ``request-close`` so the page collects a reason.
// ============================================================================

const canCancelPlan = computed(() =>
  !props.readonly
  && (
    props.plan.status === 'draft'
    || props.plan.status === 'active'
    || props.plan.status === 'pending'
  )
)

function openCancelModal() {
  // Delegates to the unified ClosePlanModal owned by this view.
  showCloseModal.value = true
}

// ============================================================================
// Visual feedback: pulse right-column card when first item lands on a draft plan
// ============================================================================

const listPulse = ref(false)
watch(
  () => props.plan.items.length,
  (next, prev) => {
    // Only celebrate the first treatment on a draft plan to keep feedback focused.
    if (prev === 0 && next > 0 && props.plan.status === 'draft') {
      toast.add({
        title: t('clinical.plans.addedToPlan'),
        color: 'success',
        icon: 'i-lucide-check-circle'
      })
      listPulse.value = true
      setTimeout(() => {
        listPulse.value = false
      }, 900)
    }
  }
)

// ============================================================================
// Hover linking state
// ============================================================================

const hoveredToothNumber = ref<number | null>(null)
const hoveredItemId = ref<string | null>(null)
/** Treatment id currently under hover in the globals strip (chart → list). */
const hoveredGlobalTreatmentId = ref<string | null>(null)

function itemTeeth(item: { treatment?: { teeth?: Array<{ tooth_number: number }> } }): number[] {
  return (item.treatment?.teeth ?? []).map(t => t.tooth_number)
}

function itemGlobalTreatmentId(item: { treatment?: { id: string, scope?: string } | null }): string | null {
  const scope = item.treatment?.scope
  if (scope === 'global_mouth' || scope === 'global_arch') {
    return item.treatment?.id ?? null
  }
  return null
}

// Items of the hovered tooth (any of whose members touches that tooth).
const highlightedItems = computed(() => {
  const fromTooth = hoveredToothNumber.value
    ? props.plan.items
        .filter(item => itemTeeth(item).includes(hoveredToothNumber.value!))
        .map(item => item.id)
    : []
  const fromGlobal = hoveredGlobalTreatmentId.value
    ? props.plan.items
        .filter(item => item.treatment?.id === hoveredGlobalTreatmentId.value)
        .map(item => item.id)
    : []
  return [...fromTooth, ...fromGlobal]
})

// Teeth of the hovered item (from Treatment.teeth[]).
const highlightedTeeth = computed(() => {
  if (!hoveredItemId.value) return []
  const item = props.plan.items.find(i => i.id === hoveredItemId.value)
  return item ? itemTeeth(item) : []
})

// Global treatment ids to highlight in the strip when hovering a list item.
const highlightedGlobalIds = computed(() => {
  if (!hoveredItemId.value) return []
  const item = props.plan.items.find(i => i.id === hoveredItemId.value)
  if (!item) return []
  const globalId = itemGlobalTreatmentId(item)
  return globalId ? [globalId] : []
})

// ============================================================================
// Computed
// ============================================================================

// Pending items count
const pendingCount = computed(() =>
  props.plan.items.filter(i => i.status === 'pending').length
)

// Can create budget: a confirmed plan without a live budget. `pending`
// counts: confirming no longer makes the budget itself — `budget` does
// when it hears of it — so a plan can be confirmed and still lack one.
// Budgets are that App's to write, hence its permission: with the App
// off nobody holds it and the action is not offered.
const canGenerateBudget = computed(() => {
  const validStatus = ['pending', 'active', 'completed'].includes(props.plan.status)
  const noActiveBudget = !props.plan.budget || props.plan.budget.status === 'cancelled'
  return validStatus && noActiveBudget && can(PERMISSIONS.budget.write)
})

// ============================================================================
// Progress stepper — maps plan status to a 3-step user journey.
// ============================================================================

type StepState = 'current' | 'complete' | 'upcoming'

interface Step {
  key: 'plan' | 'confirm' | 'inProgress'
  label: string
  icon: string
  state: StepState
}

const steps = computed<Step[]>(() => {
  const status = props.plan.status
  // Map the 5 backend states to the 3-step stepper:
  //   draft     → step 1 (Planificar) current
  //   pending   → step 2 (Confirmar)  current — awaiting patient acceptance
  //   active    → step 3 (En curso)   current — treatment underway
  //   completed → all complete
  //   closed    → frozen, last reached step stays current visually
  const isDraft = status === 'draft'
  const isPending = status === 'pending'
  const isActive = status === 'active'
  const isCompleted = status === 'completed'

  return [
    {
      key: 'plan',
      label: t('clinical.plans.steps.plan'),
      icon: 'i-lucide-clipboard-list',
      state: isDraft ? 'current' : 'complete'
    },
    {
      key: 'confirm',
      label: t('clinical.plans.steps.confirm'),
      icon: 'i-lucide-check-circle-2',
      state: isDraft
        ? 'upcoming'
        : (isPending ? 'current' : 'complete')
    },
    {
      key: 'inProgress',
      label: t('clinical.plans.steps.inProgress'),
      icon: 'i-lucide-stethoscope',
      state: isActive
        ? 'current'
        : (isCompleted ? 'complete' : 'upcoming')
    }
  ]
})

const isDraft = computed(() => props.plan.status === 'draft')
const canConfirm = computed(() => isDraft.value && pendingCount.value > 0)

// ============================================================================
// Actions
// ============================================================================

const odontogramRef = ref<{ refetchTreatments: () => Promise<void> } | null>(null)
const notesTimelineRef = ref<{ refresh: () => Promise<void> } | null>(null)

/**
 * What the user asked for on a draft plan, kept while they answer the
 * confirm dialog. Completing and charging both need a plan the clinic has
 * committed to; the dialog explains that, and the intent is carried out on
 * the other side rather than making them press twice.
 */
const pendingItemIntent = ref<{ type: 'complete' | 'collect', itemId: string } | null>(null)

function askToConfirmPlan(type: 'complete' | 'collect', itemId: string) {
  pendingItemIntent.value = { type, itemId }
  openItemId.value = null
  showConfirmModal.value = true
}

/**
 * Editing or removing a treatment of a plan in progress.
 *
 * Reopening throws away a budget the patient may have seen, so it is for an
 * administrator or a professional the case is assigned to — the same server
 * answer the header button is gated on. Without it, say so: a dialog that
 * offers a door the person cannot open is worse than a refusal.
 */
function handleItemEditBlocked() {
  if (planPermissions.value.can_reopen) {
    showReopenModal.value = true
    return
  }
  toast.add({
    id: 'plan-item-locked',
    title: t('clinical.plans.item.locked.title'),
    description: t('clinical.plans.item.locked.noPermission'),
    color: 'error',
    icon: 'i-lucide-lock'
  })
}

// --- The informed consent the clinic asks for -----------------------------
// A plan is not confirmed without it. One already under way — confirmed
// before the clinic asked, or whose letter was revoked — keeps going, so
// performing a treatment asks for the letter first and, if it is done
// anyway, the plan says in red that the letter is missing.
const consentMissing = computed(() => props.plan.informed_consent_missing === true)
const performedWithoutConsent = computed(() =>
  consentMissing.value && props.plan.items.some(item => item.status === 'completed')
)
const consentUrl = computed(() => `/patients/${props.plan.patient_id}?tab=consents&plan=${props.plan.id}`)
/** What was about to be marked as performed, waiting on "there is no letter". */
const awaitingConsent = shallowRef<(() => Promise<void>) | null>(null)
const showConsentPrompt = computed({
  get: () => awaitingConsent.value !== null,
  set: (open) => { if (!open) awaitingConsent.value = null }
})

async function completeWithoutConsent() {
  const proceed = awaitingConsent.value
  awaitingConsent.value = null
  await proceed?.()
}

async function handleCompleteItem(
  itemId: string,
  payload: { noteBody: string | null }
) {
  // A draft is a proposal: nothing is completed or charged against it until
  // the clinic confirms the plan.
  if (isDraft.value) {
    askToConfirmPlan('complete', itemId)
    return
  }
  // Ask for the letter first. Going on without it is allowed, and shown.
  if (consentMissing.value) {
    awaitingConsent.value = () => completeItemNow(itemId, payload)
    return
  }
  await completeItemNow(itemId, payload)
}

/**
 * The completion itself, with the gate above already answered.
 *
 * Separate because `onConfirmPlan` calls it straight after confirming, and
 * at that moment this view still holds the pre-confirm props — asking
 * `isDraft` again would bounce the user back into the dialog they just
 * answered.
 */
async function completeItemNow(
  itemId: string,
  payload: { noteBody: string | null }
) {
  // Clinical-note capture moved to the clinical_notes module — orchestrate
  // both calls from the client so neither module imports the other.
  const item = props.plan.items.find(i => i.id === itemId)
  await completeItem(props.plan.id, itemId, {})
  if (payload.noteBody && item?.treatment_id) {
    await createTreatmentNote(item.treatment_id, payload.noteBody)
  }
  await odontogramRef.value?.refetchTreatments()
  await notesTimelineRef.value?.refresh()
  emit('updated')

  // The patient is still in the chair; this is the cheapest moment to ask.
  // Both answers are real — a clinic that bills monthly leaves it pending
  // every day — so neither is the dismissal.
  await refreshCollections()
  const settled = itemCollection(item ?? null)
  collectPrompt.value = {
    open: true,
    name: item ? itemDisplayName(item) : '',
    amount: Number(settled?.pending ?? item?.treatment?.price_snapshot ?? 0)
  }
}

// Undoing a completion. The dialog has already asked; the charge is dropped
// server-side, so the money is refetched like after any completion.
async function handleReopenItem(itemId: string) {
  const result = await reopenItem(props.plan.id, itemId)
  if (!result) return
  await odontogramRef.value?.refetchTreatments()
  await notesTimelineRef.value?.refresh()
  emit('updated')
  await refreshCollections()
}

async function handleRemoveItem(itemId: string) {
  // Removal cascades into the odontogram and the budget line, and the
  // control is a bare trash icon in a list row.
  if (!window.confirm(t('clinical.plans.confirms.removeItem'))) return
  await removeItem(props.plan.id, itemId)
  await odontogramRef.value?.refetchTreatments()
  emit('updated')
}

async function handleReorder(itemIds: string[]) {
  await reorderItems(props.plan.id, itemIds)
  emit('updated')
}

async function handleItemDoctorChange(itemId: string, professionalId: string | null) {
  await changeItemDoctor(props.plan.id, itemId, professionalId)
  emit('updated')
}

async function handleSessionComplete(itemId: string, sessionId: string) {
  const complete = async () => {
    await completeSession(props.plan.id, itemId, sessionId, {})
    await odontogramRef.value?.refetchTreatments()
    emit('updated')
  }
  // A session is work performed too: the same question first.
  if (consentMissing.value) {
    awaitingConsent.value = complete
    return
  }
  await complete()
}

async function handleSessionCancel(itemId: string, sessionId: string) {
  await cancelSession(props.plan.id, itemId, sessionId, {})
  emit('updated')
}

// The legacy "Activate plan" CTA used to fire ``update_status`` with
// ``status='active'`` — an invalid transition under the new state
// machine (must go through ``pending``). Both the in-page CTA and
// this open handler now delegate to the page-level ConfirmPlanModal
// via the ``request-confirm`` event.
function openActivateModal() {
  // Big body CTA + any other "confirm plan" entry point.
  showConfirmModal.value = true
}

function handleGenerateBudget() {
  emit('generate-budget')
}

/**
 * Put a price on what was added after the plan was confirmed.
 *
 * The server decides whether that means a second document or lines joining
 * a draft, and says which in `created` — the toast has to be honest about
 * it, because "se ha creado un presupuesto" when none was is how a
 * receptionist goes looking for a document that does not exist.
 */
const addendumPending = ref(false)

/**
 * Adding one treatment to a plan already under way.
 *
 * Reuses the builder's own search panel, so the catalog, the templates and
 * the wording are the ones the dentist already knows. The tooth comes from
 * the chart tap that opened it, which is what makes a per-tooth treatment
 * land somewhere instead of arriving blank.
 */
const addToothNumber = ref<number | null>(null)
const addSearchOpen = ref(false)

function openAddTreatment(toothNumber: number) {
  addToothNumber.value = toothNumber
  addSearchOpen.value = true
}

async function addTreatmentToPlan(item: { id: string }) {
  const tooth = addToothNumber.value
  addSearchOpen.value = false
  if (tooth === null) return
  try {
    await api.post(
      `/api/v1/treatment_plan/treatment-plans/${props.plan.id}/catalog-items`,
      { lines: [{ catalog_item_id: item.id, tooth_numbers: [tooth], surfaces: [], phase: null, notes: null }] }
    )
    toast.add({
      id: 'plan-item-added',
      title: t('clinical.plans.addTreatment.added', { tooth }),
      description: t('clinical.plans.addTreatment.needsBudget'),
      color: 'success',
      icon: 'i-lucide-plus'
    })
    emit('updated')
  } catch {
    toast.add({
      id: 'plan-item-added',
      title: t('clinical.plans.addTreatment.failed'),
      color: 'error',
      icon: 'i-lucide-triangle-alert'
    })
  }
}

async function handleBudgetAddendum() {
  if (addendumPending.value) return
  addendumPending.value = true
  try {
    const response = await api.post<ApiResponse<{
      budget_id: string
      budget_number: string
      created: boolean
      item_count: number
    }>>(`/api/v1/budget/plans/${props.plan.id}/addendum`)
    const result = response.data
    if (!result) return

    toast.add({
      id: 'plan-addendum',
      title: t(result.created
        ? 'clinical.plans.addendum.created'
        : 'clinical.plans.addendum.extended', { number: result.budget_number }),
      description: t('clinical.plans.addendum.description', { count: result.item_count }),
      color: 'success',
      icon: 'i-lucide-file-plus-2',
      actions: [{
        label: t('clinical.plans.nextAction.viewBudget'),
        onClick: () => navigateTo(`/budgets/${result.budget_id}`)
      }]
    })
    emit('updated')
  } catch {
    toast.add({
      id: 'plan-addendum',
      title: t('clinical.plans.addendum.failed'),
      color: 'error',
      icon: 'i-lucide-triangle-alert'
    })
  } finally {
    addendumPending.value = false
  }
}

// ============================================================================
// Plan templates
//
// Two directions: pull a recurring shape into this plan, and push this plan
// back out as a shape worth repeating. The second is what makes templates
// stick — a clinic's real templates are its own, not the ones shipped.
// ============================================================================

const { applyTemplate, createFromPlan, loading: templatesLoading } = usePlanTemplates()

// ============================================================================
// Proposals from the chart
//
// The findings are already charted. Offering them as plan items is the one
// step that removes duplicate entry of a clinical fact rather than just
// speeding it up.
// ============================================================================

const { proposals, loading: proposalsLoading, fetchProposals, acceptProposals }
  = usePlanProposals()

// ============================================================================
// Money
//
// The plan owns none of it. `payments` answers
// `POST /payments/summary/by-treatments`, and one call here feeds both the
// per-session chips and the per-phase totals — see `usePlanCollections`.
// ============================================================================

const {
  sessions: sessionCollections,
  treatments: treatmentCollections,
  available: collectionsAvailable,
  fetchFor: fetchCollections,
  phaseTotals
} = usePlanCollections()

// ---------------------------------------------------------------------------
// One treatment, up close
//
// Tapping a row opens it. Everything a treatment *opens* — notes, recall, the
// charge — lives there rather than as three more icons in a row that already
// holds a name, a doctor, a price and two actions.
// ---------------------------------------------------------------------------

const openItemId = ref<string | null>(null)
const openItem = computed(
  () => props.plan.items.find(i => i.id === openItemId.value) ?? null
)

const patientName = computed(() =>
  props.plan.patient
    ? `${props.plan.patient.first_name} ${props.plan.patient.last_name}`.trim()
    : null
)

function itemCollection(item: { treatment_id?: string | null } | null) {
  if (!item?.treatment_id || !collectionsAvailable.value) return undefined
  return treatmentCollections.value[item.treatment_id]
}

function itemCollectionStatus(item: { treatment_id?: string | null } | null) {
  const state = itemCollection(item)
  if (!state) return undefined
  if (Number(state.earned) <= 0) return 'not_earned' as const
  if (Number(state.pending) <= 0) return 'collected' as const
  return Number(state.collected) > 0 ? ('partial' as const) : ('pending' as const)
}

/**
 * The charge prompt shown right after a treatment is ticked off. It carries
 * its own copy of name and amount because the item it describes has already
 * moved on by the time it renders — completion refetches the plan.
 */
const collectPrompt = ref<{
  open: boolean
  name: string
  amount: number
}>({ open: false, name: '', amount: 0 })

function itemDisplayName(item: PlannedTreatmentItem): string {
  return planItemName(item, locale.value, t)
}

const phaseMoney = computed(() => phaseTotals(props.plan.items))

/**
 * What the plan is worth, and how that splits by stage of care. Handed to the
 * schedule card in the slot ctx: only the plan knows its phases, and a
 * payment schedule that does not add up to the treatment is how a clinic
 * discovers two years in that it agreed to collect less than it is doing.
 */
/**
 * Treatments the catalog gives no price for. `planTotal` counts them as
 * zero — the only arithmetic there is — and confirming turns that figure
 * into the budget the patient signs, so the dialog says how many went in
 * at nothing.
 */
const unpricedCount = computed(
  () => props.plan.items.filter(item => item.treatment?.price_snapshot == null).length
)

const planTotal = computed(() =>
  props.plan.items.reduce((sum, item) => {
    const price = Number(item.treatment?.price_snapshot ?? 0)
    return sum + (Number.isFinite(price) ? price : 0)
  }, 0)
)

/**
 * The plan's own money, in one place.
 *
 * The sidebar card answers "what does this patient owe", which is the right
 * question at the counter and the wrong one with the plan open: a patient
 * owes what they owe across every plan, so the figure there could never be
 * read as "what this treatment has earned". These four can.
 *
 * `null` when `payments` did not answer — no module, or no permission to
 * read the ledger. The card then falls back to what it showed before.
 */
const planMoney = computed(() => {
  // An empty plan is worth nothing and has earned nothing, and that is an
  // answer rather than a missing one. `usePlanCollections` does not call
  // out for a plan with no treatments, so without this the card fell back
  // to the patient's whole debt — 560 MXN of other work, on a plan that
  // cannot owe a peso. Exactly the confusion these four figures exist for.
  if (props.plan.items.length === 0) {
    return { planned: 0, earned: 0, collected: 0, pending: 0 }
  }
  if (!collectionsAvailable.value) return null
  let earned = 0
  let collected = 0
  let pending = 0
  for (const totals of phaseMoney.value.values()) {
    earned += totals.earned
    collected += totals.collected
    pending += totals.pending
  }
  return { planned: planTotal.value, earned, collected, pending }
})

const phaseTotalsForSlot = computed(() =>
  [...phaseMoney.value.entries()]
    .sort(([a], [b]) => phaseRank(a || null) - phaseRank(b || null))
    .map(([phase, totals]) => ({
      phase: phase || null,
      label: phase
        ? t(phaseLabelKey(phase as TreatmentPhase))
        : t('clinical.plans.phases.unassigned'),
      amount: totals.planned
    }))
)

// One string per state of the plan's work. The sidebar slot watches it to
// refetch the patient's money after a completion or a reopen.
const itemsRevision = computed(() =>
  props.plan.items.map(i => `${i.id}:${i.status}:${(i.sessions ?? []).map(s => s.status).join('')}`).join('|')
)

async function refreshCollections() {
  await fetchCollections(props.plan.patient_id, props.plan.items)
}

// Money follows the plan: completing a session earns it, so the numbers are
// refetched whenever the item list changes rather than only on mount.
watch(
  itemsRevision,
  refreshCollections,
  { immediate: true }
)

const showProposals = ref(false)
const acceptedFindings = ref<string[]>([])

const proposableCount = computed(() => proposals.value.length)

async function openProposals() {
  await fetchProposals(props.plan.id)
  // Everything with a suggestion is pre-ticked: the dentist is reviewing a
  // list they already charted, not building one from scratch.
  acceptedFindings.value = proposals.value
    .filter(p => p.suggested_catalog_item !== null)
    .map(p => p.finding_id)
  showProposals.value = true
}

function toggleProposal(findingId: string) {
  const index = acceptedFindings.value.indexOf(findingId)
  if (index === -1) acceptedFindings.value.push(findingId)
  else acceptedFindings.value.splice(index, 1)
}

async function confirmProposals() {
  const items = await acceptProposals(props.plan.id, acceptedFindings.value)
  showProposals.value = false
  if (items) emit('updated')
}

// Loaded on mount for a draft plan so the button can say how many are waiting
// — a button that has to be pressed to find out it does nothing is worse than
// no button.
onMounted(() => {
  if (!effectiveReadonly.value && props.plan.status === 'draft') {
    fetchProposals(props.plan.id)
  }
})

const showApplyTemplate = ref(false)
const showSaveTemplate = ref(false)
const applyTemplateId = ref<string | null>(null)
const applyTemplateTeeth = ref<number[]>([])
const applyTemplateExcluded = ref<string[]>([])
const applyPicker = ref<{ blockingReason: string | null } | null>(null)
const saveTemplateName = ref('')

const canApplyTemplate = computed(() => !effectiveReadonly.value && isDraft.value)
const canSaveAsTemplate = computed(() => props.plan.items.length > 0)

function openApplyTemplate() {
  applyTemplateId.value = null
  applyTemplateTeeth.value = []
  applyTemplateExcluded.value = []
  showApplyTemplate.value = true
}

async function confirmApplyTemplate() {
  if (!applyTemplateId.value || applyPicker.value?.blockingReason) return
  const result = await applyTemplate(
    props.plan.id,
    applyTemplateId.value,
    applyTemplateTeeth.value,
    applyTemplateExcluded.value
  )
  showApplyTemplate.value = false
  if (result) emit('updated')
}

function openSaveTemplate() {
  saveTemplateName.value = props.plan.title || ''
  showSaveTemplate.value = true
}

async function confirmSaveTemplate() {
  if (!saveTemplateName.value.trim()) return
  await createFromPlan(props.plan.id, saveTemplateName.value.trim())
  showSaveTemplate.value = false
}

const moreMenuItems = computed<DropdownMenuItem[]>(() => {
  const items: DropdownMenuItem[] = []
  if (canSaveAsTemplate.value) {
    items.push({
      label: t('clinical.plans.templates.saveAs'),
      icon: 'i-lucide-bookmark-plus',
      onSelect: openSaveTemplate
    })
  }
  if (canCancelPlan.value) {
    items.push({
      label: t('clinical.plans.cancelPlan'),
      icon: 'i-lucide-ban',
      color: 'error',
      onSelect: openCancelModal
    })
  }
  return items
})
</script>

<template>
  <div class="space-y-4">
    <!-- Header: title + stepper + actions -->
    <div class="plan-header">
      <div class="plan-header-title">
        <h2 class="text-h1 text-default">
          {{ plan.title || plan.plan_number }}
        </h2>
        <NuxtLink
          v-if="standalone && plan.patient"
          :to="`/patients/${patientId}`"
          class="inline-flex items-center gap-1 text-caption text-primary-accent hover:underline mt-0.5"
        >
          <UIcon
            name="i-lucide-user"
            class="w-3.5 h-3.5"
          />
          {{ plan.patient.first_name }} {{ plan.patient.last_name }}
        </NuxtLink>
      </div>

      <!-- Progress stepper -->
      <ol class="plan-stepper">
        <li
          v-for="(step, idx) in steps"
          :key="step.key"
          class="plan-step"
          :class="`plan-step-${step.state}`"
        >
          <span class="plan-step-marker">
            <UIcon
              v-if="step.state === 'complete'"
              name="i-lucide-check"
              class="w-3.5 h-3.5"
            />
            <span v-else>{{ idx + 1 }}</span>
          </span>
          <span class="plan-step-label">{{ step.label }}</span>
          <span
            v-if="idx < steps.length - 1"
            class="plan-step-connector"
          />
        </li>
      </ol>

      <!-- Action buttons: ghost/disabled for draft, live for active/completed. -->
      <div
        v-if="!readonly"
        class="plan-header-actions"
      >
        <UButton
          v-if="canGenerateBudget"
          variant="soft"
          size="sm"
          icon="i-lucide-file-plus"
          :loading="loading"
          @click="handleGenerateBudget"
        >
          {{ t('clinical.plans.generateBudget') }}
        </UButton>
        <UButton
          v-else-if="isDraft"
          variant="soft"
          size="sm"
          icon="i-lucide-file-plus"
          color="neutral"
          disabled
          :title="t('clinical.plans.ghostHint')"
        >
          {{ t('clinical.plans.generateBudget') }}
        </UButton>

        <UButton
          v-if="plan.status === 'active'"
          variant="soft"
          size="sm"
          icon="i-lucide-calendar-plus"
          @click="emit('schedule')"
        >
          {{ t('treatmentPlans.scheduleAppointment') }}
        </UButton>
        <UButton
          v-else-if="isDraft"
          variant="soft"
          size="sm"
          icon="i-lucide-calendar-plus"
          color="neutral"
          disabled
          :title="t('clinical.plans.ghostHint')"
        >
          {{ t('treatmentPlans.scheduleAppointment') }}
        </UButton>

        <!-- Workflow transitions for plans past draft. The big CTA in
             the body owns the draft → pending action so it's not
             duplicated up here. -->
        <!-- Shown for `active` as well as `pending` since attendance
             started moving plans on, and gated on the server's answer
             rather than a role check here: reopening throws away a
             budget the patient may have seen, so it is for an
             administrator or a professional the case is assigned to. -->
        <UButton
          v-if="planPermissions.can_reopen"
          variant="soft"
          color="warning"
          size="sm"
          icon="i-lucide-undo-2"
          @click="showReopenModal = true"
        >
          {{ t('treatmentPlans.actions.reopen') }}
        </UButton>
        <UButton
          v-if="plan.status === 'closed'"
          variant="solid"
          color="primary"
          size="sm"
          icon="i-lucide-rotate-ccw"
          @click="showReactivateModal = true"
        >
          {{ t('treatmentPlans.actions.reactivate') }}
        </UButton>

        <UDropdownMenu
          v-if="moreMenuItems.length > 0"
          :items="moreMenuItems"
        >
          <UButton
            variant="ghost"
            color="neutral"
            icon="i-lucide-more-horizontal"
            size="sm"
            :aria-label="t('common.actions')"
          />
        </UDropdownMenu>
      </div>
    </div>

    <!-- What moves the plan on. Server-computed, one step at a time; see
         PlanNextActionBar. Renders in the patient record too, where the
         same buttons work — `readonly` there means no write access, not
         "embedded". -->
    <!-- Work was performed and the letter the clinic asks for is not on
         file. Red, and it stays until the letter is signed. -->
    <UAlert
      v-if="performedWithoutConsent"
      color="error"
      variant="subtle"
      icon="i-lucide-file-warning"
      :title="t('treatmentPlans.consentMissing.title')"
      :description="t('treatmentPlans.consentMissing.description')"
      :actions="readonly ? undefined : [{ label: t('treatmentPlans.consentRequired.action'), to: consentUrl }]"
      data-testid="plan-consent-missing"
    />

    <PlanNextActionBar
      :action="plan.next_action"
      :budget-id="plan.budget_id ?? null"
      :readonly="readonly"
      :can-generate-budget="canGenerateBudget"
      :can-write="can(PERMISSIONS.treatmentPlans.write)"
      :can-budget="can(PERMISSIONS.budget.write)"
      @confirm="openActivateModal"
      @generate-budget="handleGenerateBudget"
      @budget-addendum="handleBudgetAddendum"
      @schedule="emit('schedule')"
    />

    <!-- What was found and how it is expected to go: the diagnosis and
         prognosis a clinical record asks a plan for. -->
    <PlanDiagnosisCard
      :plan="plan"
      :readonly="readonly"
      @updated="emit('updated')"
    />

    <!-- The plan's shape is settled. A statement of the rule, not an alarm:
         the way to edit anyway is in the treatment's own dialog and in the
         chart's toast, both of which offer Reabrir where it is allowed. -->
    <div
      v-if="isLocked"
      class="plan-locked-banner"
    >
      <UIcon
        name="i-lucide-lock"
        class="w-4 h-4 shrink-0 mt-0.5"
      />
      <div class="plan-locked-text">
        <div class="plan-locked-title">
          {{ lockedCopy.title }}
        </div>
        <div class="plan-locked-subtitle">
          {{ lockedCopy.subtitle }}
        </div>
      </div>
      <UButton
        v-if="liveBudgetId"
        :to="`/budgets/${liveBudgetId}`"
        size="xs"
        color="neutral"
        variant="soft"
        icon="i-lucide-external-link"
        trailing
        class="plan-locked-action shrink-0"
      >
        {{ t('clinical.plans.locked.viewBudget') }}
      </UButton>
    </div>

    <!-- Two-column layout.
         Tailwind's ``lg:`` (1024px) used to drive this layout but
         many laptops + browsers with DevTools or side panels open
         report a viewport below 1024px, collapsing the grid to a
         single column — odontogram filled full width and the
         treatment list + clinical notes slid below it. The custom
         ``min-[960px]:`` breakpoint covers most desktops/laptops
         (13″ MacBook = 1280px, even with the dock taking 64px the
         viewport is ≥1216px; a 1280px window with a 320px DevTools
         pane still has 960px left) while keeping the stacked
         layout for genuine tablet widths. -->
    <div class="grid grid-cols-1 min-[960px]:grid-cols-5 gap-4">
      <!-- Left column: Odontogram (wider) -->
      <UCard class="min-[960px]:col-span-3 self-start">
        <template #header>
          <div class="flex items-center gap-2">
            <UIcon
              name="i-lucide-scan"
              class="w-5 h-5 text-primary-accent"
            />
            <span class="text-ui text-default">{{ t('clinical.plans.odontogram') }}</span>
          </div>
        </template>

        <OdontogramChart
          ref="odontogramRef"
          :patient-id="patientId"
          :mode="effectiveReadonly ? 'view-only' : 'planning'"
          :plan-id="plan.id"
          :plan-title="plan.title || plan.plan_number"
          :highlighted-teeth-prop="highlightedTeeth"
          :highlighted-global-ids="highlightedGlobalIds"
          @tooth-hover="hoveredToothNumber = $event"
          @global-hover="hoveredGlobalTreatmentId = $event"
          @treatments-changed="emit('updated')"
          @readonly-interaction="handleReadonlyChartClick"
        />
      </UCard>

      <!-- Right column: Treatment list + clinical notes, stacked and auto-height. -->
      <div class="min-[960px]:col-span-2 flex flex-col gap-4 self-start">
        <!-- Money surface owned by `payments`. The plan hands over what it
             knows (which patient, which plan, which budget) and renders
             nothing of its own here. -->
        <ModuleSlot
          name="treatment_plan.detail.sidebar"
          :ctx="{
            planId: plan.id,
            patientId,
            patientName: plan.patient
              ? `${plan.patient.first_name} ${plan.patient.last_name}`.trim()
              : null,
            budgetId: plan.budget_id ?? null,
            planStatus: plan.status,
            itemsRevision,
            planTotal,
            planMoney,
            phaseTotals: phaseTotalsForSlot
          }"
        />

        <UCard
          class="plan-list-card"
          :class="{ 'plan-list-pulse': listPulse }"
        >
          <template #header>
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <UIcon
                  name="i-lucide-list-checks"
                  class="w-5 h-5"
                />
                <span class="font-medium">{{ t('clinical.plans.treatments') }}</span>
              </div>
              <UBadge
                v-if="pendingCount > 0"
                color="primary"
                variant="subtle"
              >
                {{ pendingCount }} {{ t('clinical.plans.pending') }}
              </UBadge>
            </div>
          </template>

          <PlanTreatmentList
            :items="plan.items"
            :highlighted-items="highlightedItems"
            :readonly="effectiveReadonly"
            :allow-complete="canCompleteItems"
            :plan-status="plan.status"
            :plan-professional-id="plan.assigned_professional_id ?? null"
            :collections="collectionsAvailable ? sessionCollections : undefined"
            :treatment-collections="collectionsAvailable ? treatmentCollections : undefined"
            :phase-money="phaseMoney"
            :consent-missing="consentMissing"
            @item-hover="hoveredItemId = $event"
            @item-open="openItemId = $event"
            @item-complete="handleCompleteItem"
            @item-remove="handleRemoveItem"
            @session-complete="handleSessionComplete"
            @session-cancel="handleSessionCancel"
            @reorder="handleReorder"
            @item-doctor-change="handleItemDoctorChange"
          />

          <!-- Sticky confirm-plan CTA: only in draft, adapts to whether items exist. -->
          <template
            v-if="!readonly && isDraft"
            #footer
          >
            <div class="confirm-cta">
              <!-- A template is the fastest way out of an empty plan, so it
                   sits where the dentist is already looking. -->
              <UButton
                v-if="canApplyTemplate"
                variant="soft"
                color="primary"
                size="sm"
                block
                icon="i-lucide-layout-template"
                @click="openApplyTemplate"
              >
                {{ t('clinical.plans.templates.apply') }}
              </UButton>
              <!-- Only when there is something to propose. -->
              <UButton
                v-if="canApplyTemplate && proposableCount > 0"
                variant="soft"
                color="warning"
                size="sm"
                block
                icon="i-lucide-scan-search"
                @click="openProposals"
              >
                {{ t('clinical.plans.proposals.open', { count: proposableCount }) }}
              </UButton>
              <div
                v-if="!canConfirm"
                class="confirm-cta-empty"
              >
                <UIcon
                  name="i-lucide-info"
                  class="w-4 h-4"
                />
                <span>{{ t('clinical.plans.confirmCta.empty') }}</span>
              </div>
              <template v-else>
                <div class="confirm-cta-text">
                  <div class="confirm-cta-title">
                    {{ t('clinical.plans.confirmCta.titleWithItems') }}
                  </div>
                  <div class="confirm-cta-subtitle">
                    {{ t('clinical.plans.confirmCta.subtitleWithItems') }}
                  </div>
                </div>
                <UButton
                  color="primary"
                  size="lg"
                  block
                  icon="i-lucide-check-circle-2"
                  :loading="loading"
                  @click="openActivateModal"
                >
                  {{ t('treatmentPlans.actions.confirm') }}
                </UButton>
              </template>
            </div>
          </template>
        </UCard>

        <UCard>
          <template #header>
            <div class="flex items-center gap-2">
              <UIcon
                name="i-lucide-notebook-pen"
                class="w-5 h-5"
              />
              <span class="font-medium">{{ t('treatmentPlans.notes.title') }}</span>
            </div>
          </template>
          <PlanNotesTimeline
            ref="notesTimelineRef"
            :plan-id="plan.id"
            :patient-id="plan.patient_id"
            :items="plan.items"
            :readonly="readonly"
            @item-hover="hoveredItemId = $event"
          />
        </UCard>
      </div>
    </div>

    <!-- Workflow modals (PR1/PR2) — owned by this view so any parent
         (standalone page, patient ficha) gets the same flow. -->
    <!-- Performing a treatment on a plan with no signed consent: ask for
         the letter first; going on without it is the clinician's call. -->
    <UModal
      v-model:open="showConsentPrompt"
      :title="t('treatmentPlans.consentPrompt.title')"
      :description="t('treatmentPlans.consentPrompt.description')"
    >
      <template #footer>
        <div
          class="flex w-full flex-wrap justify-end gap-2"
          data-testid="plan-consent-prompt"
        >
          <UButton
            color="neutral"
            variant="ghost"
            @click="awaitingConsent = null"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            color="error"
            variant="soft"
            data-testid="plan-consent-proceed"
            @click="completeWithoutConsent"
          >
            {{ t('treatmentPlans.consentPrompt.proceed') }}
          </UButton>
          <UButton
            icon="i-lucide-file-signature"
            :to="consentUrl"
            data-testid="plan-consent-write"
          >
            {{ t('treatmentPlans.consentRequired.action') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <ConfirmPlanModal
      :open="showConfirmModal"
      :plan-number="planSummary.number"
      :item-count="planSummary.count"
      :total-estimated="planSummary.total"
      :loading="transitioning"
      :reason="pendingItemIntent ? t('clinical.plans.item.needsConfirm') : undefined"
      :unpriced-count="unpricedCount"
      @update:open="(v) => { showConfirmModal = v; if (!v) pendingItemIntent = null }"
      @confirm="onConfirmPlan"
      @cancel="showConfirmModal = false; pendingItemIntent = null"
    />
    <!-- The change log closes the page: a plan is a contract whose price
         moves with it, so "who changed this, and when" has to be
         answerable without reading the database. -->
    <UCard class="mt-6">
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon
            name="i-lucide-history"
            class="w-4 h-4 text-[var(--ui-text-muted)]"
          />
          <h3 class="font-medium">
            {{ t('treatmentPlans.history.title') }}
          </h3>
        </div>
      </template>

      <p
        v-if="!historyEntries.length"
        class="text-sm text-[var(--ui-text-muted)]"
      >
        {{ t('treatmentPlans.history.empty') }}
      </p>

      <ol
        v-else
        class="space-y-3"
      >
        <li
          v-for="entry in historyEntries"
          :key="entry.id"
          class="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm"
        >
          <UBadge
            :color="historyColor(entry.action)"
            variant="subtle"
            size="xs"
          >
            {{ t(`treatmentPlans.history.actions.${entry.action}`, entry.action) }}
          </UBadge>
          <span class="text-[var(--ui-text-toned)]">{{ historyDetail(entry) }}</span>
          <span class="text-xs text-[var(--ui-text-muted)] tnum">
            {{ entry.actor_name || t('treatmentPlans.history.system') }}
            · {{ formatHistoryDate(entry.created_at) }}
          </span>
        </li>
      </ol>
    </UCard>

    <!-- The builder's search panel, reused to add one treatment to a plan
         already under way. Opened from the chart, so it always knows the
         tooth. -->
    <PlanTreatmentSearch
      v-model:open="addSearchOpen"
      :tooth-number="addToothNumber"
      :surface="null"
      @select="addTreatmentToPlan"
    />

    <ReopenPlanModal
      :open="showReopenModal"
      :loading="transitioning"
      @update:open="(v) => (showReopenModal = v)"
      @confirm="onReopenPlan"
      @cancel="showReopenModal = false"
    />
    <ClosePlanModal
      :open="showCloseModal"
      :loading="transitioning"
      @update:open="(v) => (showCloseModal = v)"
      @confirm="onClosePlanSubmit"
      @cancel="showCloseModal = false"
    />
    <ReactivatePlanModal
      :open="showReactivateModal"
      :loading="transitioning"
      :closed-at="plan.closed_at ?? null"
      :previous-reason="plan.closure_reason ?? null"
      @update:open="(v) => (showReactivateModal = v)"
      @confirm="onReactivatePlan"
      @cancel="showReactivateModal = false"
    />
    <!-- One treatment, up close: what it is, what it is worth, and the three
         things you can open on it. -->
    <PlanItemDetailModal
      :open="openItemId !== null"
      :item="openItem"
      :plan-id="plan.id"
      :patient-id="patientId"
      :patient-name="patientName"
      :budget-id="plan.budget_id ?? null"
      :collection="itemCollection(openItem)"
      :collection-status="itemCollectionStatus(openItem)"
      :can-complete="canCompleteItems"
      :can-collect="inProgress"
      :can-edit-items="!readonly && isDraft"
      :can-request-edit="!readonly && inProgress"
      :can-reopen="!readonly && plan.status !== 'closed'"
      @update:open="(v) => { if (!v) openItemId = null }"
      @complete="(itemId) => handleCompleteItem(itemId, { noteBody: null })"
      @remove="handleRemoveItem"
      @collect-blocked="(itemId) => askToConfirmPlan('collect', itemId)"
      @edit-blocked="handleItemEditBlocked"
      @reopen="handleReopenItem"
      @collected="refreshCollections"
    />

    <PlanItemCollectPrompt
      v-model:open="collectPrompt.open"
      :treatment-name="collectPrompt.name"
      :amount="collectPrompt.amount"
      :patient-id="patientId"
      :patient-name="patientName"
      :budget-id="plan.budget_id ?? null"
      @collected="refreshCollections"
    />

    <ContactLogModal
      :open="showContactLogModal"
      :loading="transitioning"
      @update:open="(v) => (showContactLogModal = v)"
      @confirm="onLogContact"
      @cancel="showContactLogModal = false"
    />

    <!-- Apply a template to this plan -->
    <UModal v-model:open="showApplyTemplate">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-h3">
              {{ t('clinical.plans.templates.apply') }}
            </h3>
          </template>

          <PlanTemplatePicker
            ref="applyPicker"
            v-model="applyTemplateId"
            @change="(p) => {
              applyTemplateTeeth = p.toothNumbers
              applyTemplateExcluded = p.excludedItemIds
            }"
          />

          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                variant="ghost"
                color="neutral"
                @click="showApplyTemplate = false"
              >
                {{ t('actions.cancel') }}
              </UButton>
              <UButton
                :loading="templatesLoading"
                :disabled="!applyTemplateId || !!applyPicker?.blockingReason"
                @click="confirmApplyTemplate"
              >
                {{ t('clinical.plans.templates.apply') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- Save this plan as a reusable template -->
    <UModal v-model:open="showSaveTemplate">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-h3">
              {{ t('clinical.plans.templates.saveTitle') }}
            </h3>
          </template>

          <div class="space-y-3">
            <p class="text-caption text-muted">
              {{ t('clinical.plans.templates.saveHint') }}
            </p>
            <UFormField :label="t('clinical.plans.templates.saveName')">
              <UInput
                v-model="saveTemplateName"
                class="w-full"
                :placeholder="t('clinical.plans.templates.saveNamePlaceholder')"
              />
            </UFormField>
          </div>

          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                variant="ghost"
                color="neutral"
                @click="showSaveTemplate = false"
              >
                {{ t('actions.cancel') }}
              </UButton>
              <UButton
                :loading="templatesLoading"
                :disabled="!saveTemplateName.trim()"
                @click="confirmSaveTemplate"
              >
                {{ t('actions.save') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>

    <!-- Findings charted on this patient that nothing is planned for yet. -->
    <UModal v-model:open="showProposals">
      <template #content>
        <UCard>
          <template #header>
            <h3 class="text-h3">
              {{ t('clinical.plans.proposals.title') }}
            </h3>
            <p class="text-caption text-muted mt-1">
              {{ t('clinical.plans.proposals.hint') }}
            </p>
          </template>

          <div class="space-y-2">
            <label
              v-for="proposal in proposals"
              :key="proposal.finding_id"
              class="proposal-row"
              :class="{ 'is-unmatched': !proposal.suggested_catalog_item }"
            >
              <UCheckbox
                :model-value="acceptedFindings.includes(proposal.finding_id)"
                :disabled="!proposal.suggested_catalog_item"
                @update:model-value="toggleProposal(proposal.finding_id)"
              />
              <span class="proposal-finding">
                {{ t(`odontogram.treatments.types.${proposal.clinical_type}`) }}
                <template v-if="proposal.tooth_number">
                  · {{ t('clinical.tooth') }} {{ proposal.tooth_number }}
                </template>
              </span>
              <UIcon
                name="i-lucide-arrow-right"
                class="w-3.5 h-3.5 text-subtle shrink-0"
              />
              <span class="proposal-suggestion">
                {{ proposal.suggested_catalog_item
                  ? (proposal.suggested_catalog_item.names.es
                    || proposal.suggested_catalog_item.internal_code)
                  : t('clinical.plans.proposals.noSuggestion') }}
              </span>
            </label>
          </div>

          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                variant="ghost"
                color="neutral"
                @click="showProposals = false"
              >
                {{ t('actions.cancel') }}
              </UButton>
              <UButton
                :loading="proposalsLoading"
                :disabled="acceptedFindings.length === 0"
                @click="confirmProposals"
              >
                {{ t('clinical.plans.proposals.accept', { count: acceptedFindings.length }) }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<style scoped>
.plan-header {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 16px;
}

@media (max-width: 900px) {
  .plan-header {
    grid-template-columns: 1fr;
  }
}

.plan-header-title {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.plan-header-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* Stepper */
.plan-stepper {
  display: flex;
  align-items: center;
  gap: 8px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.plan-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #9CA3AF;
  position: relative;
}

.plan-step-marker {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  border: 1.5px solid currentColor;
  background: transparent;
  flex-shrink: 0;
}

.plan-step-label {
  font-weight: 500;
  white-space: nowrap;
}

.plan-step-connector {
  width: 20px;
  height: 1.5px;
  background: currentColor;
  opacity: 0.4;
}

.plan-step-current {
  color: #2563EB;
}

.plan-step-current .plan-step-marker {
  background: #2563EB;
  color: white;
  border-color: #2563EB;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.2);
}

.plan-step-complete {
  color: #16A34A;
}

.plan-step-complete .plan-step-marker {
  background: #16A34A;
  color: white;
  border-color: #16A34A;
}

.plan-step-upcoming {
  color: #9CA3AF;
}

:root.dark .plan-step-current {
  color: #60A5FA;
}

:root.dark .plan-step-current .plan-step-marker {
  background: #2563EB;
  border-color: #3B82F6;
}

:root.dark .plan-step-complete {
  color: #4ADE80;
}

/* Confirm CTA footer */
.confirm-cta {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.confirm-cta-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.confirm-cta-title {
  font-weight: 600;
  font-size: 14px;
  color: #1E40AF;
}

:root.dark .confirm-cta-title {
  color: #BFDBFE;
}

.confirm-cta-subtitle {
  font-size: 12px;
  color: #475569;
  line-height: 1.35;
}

:root.dark .confirm-cta-subtitle {
  color: #94A3B8;
}

.confirm-cta-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 13px;
  color: #64748B;
  background: #F1F5F9;
  border-radius: 8px;
}

:root.dark .confirm-cta-empty {
  background: rgba(100, 116, 139, 0.15);
  color: #CBD5E1;
}

/* One charted finding and the treatment proposed for it. */
.proposal-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}

.proposal-row:hover {
  background: var(--color-bg-muted, #F9FAFB);
}

.proposal-row.is-unmatched {
  opacity: 0.55;
  cursor: default;
}

.proposal-finding {
  min-width: 0;
  color: var(--color-text-muted, #6B7280);
}

.proposal-suggestion {
  min-width: 0;
  font-weight: 500;
}

/* First-item pulse on list card */
.plan-list-card {
  transition: box-shadow 0.3s ease;
}

.plan-list-pulse {
  animation: plan-list-pulse 0.9s ease-out;
}

@keyframes plan-list-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.55); }
  50%  { box-shadow: 0 0 0 8px rgba(34, 197, 94, 0.18); }
  100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}

/* The plan's shape is settled.
   Quiet on purpose, and in theme tokens rather than the hard-coded amber it
   used to carry: this is the state a plan spends most of its life in, and a
   banner the colour of a warning that is right every day teaches the eye to
   skip warnings. The hex values also ignored dark mode. */
.plan-locked-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 14px;
  background: var(--ui-bg-muted, transparent);
  border: 1px solid var(--ui-border);
  border-radius: 8px;
  color: var(--ui-text-muted);
  font-size: 13px;
  line-height: 1.4;
}

.plan-locked-text {
  flex: 1;
  min-width: 0;
}

.plan-locked-action {
  align-self: center;
}

:root.dark .plan-locked-banner {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.35);
  color: #FCD34D;
}

.plan-locked-title {
  font-weight: 600;
  color: var(--ui-text-toned);
}

.plan-locked-subtitle {
  font-size: 12px;
  opacity: 0.85;
}
</style>
