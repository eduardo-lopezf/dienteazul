<script setup lang="ts">
/**
 * PlanTreatmentList - Display treatment items in a plan
 *
 * Features:
 * - Hover linking with odontogram (highlight items when tooth hovered)
 * - Complete/remove item actions
 * - Pending and completed sections
 * - Drag & drop reorder (mouse + keyboard Alt+↑/↓)
 */

import type { PlannedTreatmentItem, TreatmentPhase } from '~~/app/types'
import { VueDraggable } from 'vue-draggable-plus'
import { phaseLabelKey, phaseRank } from '~~/app/config/treatmentPhases'
import type { CollectionState, CollectionStatus } from '../../composables/usePlanCollections'
import CompletionNudgeModal from './notes/CompletionNudgeModal.vue'
import { planItemName } from './planItemName'
import PlanItemDoctorChip from './PlanItemDoctorChip.vue'
import PlanItemSessionRow from '../treatment-plans/PlanItemSessionRow.vue'

const props = defineProps<{
  items: PlannedTreatmentItem[]
  highlightedItems?: string[]
  readonly?: boolean
  /**
   * When true, the "mark complete" action stays available even if `readonly` is true.
   * Use for plans locked by an active budget — structural edits are blocked but
   * completing items is still a valid clinical action.
   */
  allowComplete?: boolean
  /** Plan status — drives empty-state guidance copy (draft shows 3-step onboarding). */
  planStatus?: string
  /** Doctor of the parent plan. Drives "override" detection on each item chip. */
  planProfessionalId?: string | null
  /**
   * Collection state per session id, from `payments`. Passed down rather than
   * fetched here: the parent makes one call for the whole plan.
   */
  collections?: Record<string, CollectionState>
  /**
   * Per-treatment collection state, keyed by treatment id. Used for the
   * "closed" badge — work done with nothing left to charge.
   */
  treatmentCollections?: Record<string, CollectionState>
  /** Per-phase money totals, keyed by phase (empty string = unphased). */
  phaseMoney?: Map<string, { planned: number, earned: number, collected: number, pending: number }>
  /**
   * The clinic asks for a signed informed consent for this plan and it has
   * none: what was performed meanwhile is marked as lacking it.
   */
  consentMissing?: boolean
}>()

const completeEnabled = computed(() => !props.readonly || props.allowComplete)

const emit = defineEmits<{
  'item-hover': [itemId: string | null]
  /**
   * The row was tapped. Everything a treatment *opens* — its notes, its
   * recall, its charge — moved into a dialog the host owns, so the row is
   * left with only what changes the plan.
   */
  'item-open': [itemId: string]
  /**
   * Fired after the clinician confirms item completion. ``noteBody`` is the
   * rich-text HTML to persist as a plan_item-level clinical note; when ``null``
   * the backend emits ``item_completed_without_note`` for audit/compliance.
   */
  'item-complete': [itemId: string, payload: { noteBody: string | null }]
  'item-remove': [itemId: string]
  /** Fired after the user reorders pending items (drag or keyboard). */
  'reorder': [itemIds: string[]]
  /** Fired when the user picks a different doctor for a single item. */
  'item-doctor-change': [itemId: string, professionalId: string | null]
  /** Fired when the user completes a specific session of a multi-session item. */
  'session-complete': [itemId: string, sessionId: string]
  /** Fired when the user cancels a specific session. */
  'session-cancel': [itemId: string, sessionId: string]
}>()

const { t, locale } = useI18n()

// Confirmation modal state
const showConfirmModal = ref(false)
const itemToComplete = ref<PlannedTreatmentItem | null>(null)

function openConfirmModal(item: PlannedTreatmentItem) {
  itemToComplete.value = item
  showConfirmModal.value = true
}

function handleNudgeConfirm(payload: { itemId: string, noteBody: string | null }) {
  emit('item-complete', payload.itemId, { noteBody: payload.noteBody })
  showConfirmModal.value = false
  itemToComplete.value = null
}

function cancelComplete() {
  showConfirmModal.value = false
  itemToComplete.value = null
}

// Pending items, grouped by stage of care.
//
// A course of care is phased, and reading it as one flat click-ordered list
// is what made a plan hard to explain to a patient. Each group is its own
// writable array so VueDraggable can mutate it during a drag; dragging stays
// *within* a phase on purpose — moving a treatment to another stage is a
// clinical decision (change its phase), not a drag.
interface PendingGroup {
  /** `null` for items whose catalog entry never declared a phase. */
  phase: TreatmentPhase | null
  items: PlannedTreatmentItem[]
}

const pendingGroups = ref<PendingGroup[]>([])

function syncPendingFromProps() {
  const pending = props.items
    .filter(i => i.status === 'pending')
    .slice()
    .sort((a, b) => a.sequence_order - b.sequence_order)

  const byPhase = new Map<string, PlannedTreatmentItem[]>()
  for (const item of pending) {
    const key = item.phase ?? ''
    const bucket = byPhase.get(key)
    if (bucket) bucket.push(item)
    else byPhase.set(key, [item])
  }

  pendingGroups.value = [...byPhase.entries()]
    .sort(([a], [b]) => phaseRank(a || null) - phaseRank(b || null))
    .map(([phase, items]) => ({ phase: (phase || null) as TreatmentPhase | null, items }))
}

watch(() => props.items, syncPendingFromProps, { immediate: true, deep: true })

/** Flat pending list in display order — phase order first, manual order within. */
const localPending = computed(() => pendingGroups.value.flatMap(g => g.items))

/**
 * A single unphased group is the pre-phase status quo: show no header, so
 * plans built before any of this look exactly as they did.
 */
const showPhaseHeaders = computed(() =>
  pendingGroups.value.length > 1 || pendingGroups.value[0]?.phase != null
)

/** Running 1..n numbering across groups, so the list reads as one sequence. */
function groupOffset(groupIndex: number): number {
  let offset = 0
  for (let i = 0; i < groupIndex; i++) offset += pendingGroups.value[i]!.items.length
  return offset
}

function phaseLabel(phase: TreatmentPhase | null): string {
  return phase ? t(phaseLabelKey(phase)) : t('clinical.plans.phases.unassigned')
}

function sessionCollection(sessionId: string): CollectionState | undefined {
  return props.collections?.[sessionId]
}

function sessionStatus(sessionId: string): CollectionStatus | undefined {
  const state = props.collections?.[sessionId]
  if (!props.collections) return undefined
  if (!state) return 'not_earned'
  if (Number(state.pending) <= 0) return 'collected'
  return Number(state.collected) > 0 ? 'partial' : 'pending'
}

/**
 * What the phase header shows on the money side. Only the part that is
 * actually chargeable — pending — because that is the number a dentist acts
 * on when the patient is leaving the box. The full price of the phase is
 * already the sum of the rows below it.
 */
function phasePending(phase: TreatmentPhase | null): number {
  return props.phaseMoney?.get(phase ?? '')?.pending ?? 0
}

const { format: formatCurrency } = useCurrency()

const completedItems = computed(() =>
  props.items
    .filter(i => i.status === 'completed')
    .slice()
    .sort((a, b) => a.sequence_order - b.sequence_order)
)

function emitReorder() {
  // Build full ordering: pending (phase order, then manual order within each
  // phase) first, completed last in their original order.
  const ids = [
    ...localPending.value.map(i => i.id),
    ...completedItems.value.map(i => i.id)
  ]
  emit('reorder', ids)
}

/** Alt+↑/↓ moves an item within its own phase, mirroring what a drag allows. */
function moveItem(groupIndex: number, index: number, delta: -1 | 1) {
  const group = pendingGroups.value[groupIndex]
  if (!group) return
  const next = index + delta
  if (next < 0 || next >= group.items.length) return
  const arr = [...group.items]
  const tmp = arr[index]!
  arr[index] = arr[next]!
  arr[next] = tmp
  group.items = arr
  emitReorder()
}

function handleKeydown(e: KeyboardEvent, groupIndex: number, index: number) {
  if (!e.altKey) return
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveItem(groupIndex, index, -1)
  } else if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveItem(groupIndex, index, 1)
  }
}

// Check if item is highlighted
function isHighlighted(itemId: string): boolean {
  return props.highlightedItems?.includes(itemId) ?? false
}

/**
 * Closed = done, and nothing left to charge for it.
 *
 * Derived rather than stored so it cannot drift from the ledger: a refund
 * recorded in Finanzas puts money back on the treatment and the badge goes
 * away with no second write anywhere. Absent `payments` means no badge —
 * "nothing pending" and "we cannot see the money" are not the same claim.
 */
function isClosed(item: PlannedTreatmentItem): boolean {
  if (item.status !== 'completed' || !props.treatmentCollections) return false
  const state = item.treatment_id ? props.treatmentCollections[item.treatment_id] : undefined
  if (!state) return false
  return Number(state.earned) > 0 && Number(state.pending) <= 0
}

/** Shared with the item dialog and the charge prompt — see `planItemName`. */
function getItemName(item: PlannedTreatmentItem): string {
  return planItemName(item, locale.value, t)
}

function itemTeeth(item: PlannedTreatmentItem): number[] {
  return (item.treatment?.teeth ?? []).map(t => t.tooth_number)
}

function itemSurfaces(item: PlannedTreatmentItem): string[] {
  const first = item.treatment?.teeth?.[0]
  return (first?.surfaces as string[] | undefined) ?? []
}

function formatToothInfo(item: PlannedTreatmentItem): string {
  const teeth = itemTeeth(item)
  if (teeth.length === 0) return ''
  const label = teeth.length === 1
    ? `${t('clinical.tooth')} ${teeth[0]}`
    : `${t('clinical.tooth')} ${teeth.join(', ')}`
  const surfaces = itemSurfaces(item)
  return surfaces.length > 0 ? `${label} (${surfaces.join(', ')})` : label
}

function hasToothInfo(item: PlannedTreatmentItem): boolean {
  return itemTeeth(item).length > 0
}

function getItemPrice(item: PlannedTreatmentItem): number | undefined {
  const snap = item.treatment?.price_snapshot
  if (!snap) return undefined
  const parsed = Number(snap)
  return Number.isFinite(parsed) ? parsed : undefined
}

function isMultiSession(item: PlannedTreatmentItem): boolean {
  return (item.sessions?.length ?? 0) > 1
}

function sessionProgress(item: PlannedTreatmentItem): { done: number, total: number } {
  const sessions = item.sessions ?? []
  return {
    done: sessions.filter(s => s.status === 'completed').length,
    total: sessions.length
  }
}
</script>

<template>
  <div class="space-y-[var(--density-gap,0.5rem)]">
    <!-- Empty state: guided 3-step onboarding for draft plans; plain text otherwise. -->
    <div
      v-if="items.length === 0 && planStatus === 'draft'"
      class="empty-draft-guide"
    >
      <div class="empty-draft-title">
        <UIcon
          name="i-lucide-sparkles"
          class="w-4 h-4 text-primary-accent"
        />
        <span>{{ t('clinical.plans.emptyDraft.title') }}</span>
      </div>
      <ol class="empty-draft-steps">
        <li>
          <span class="step-num">1</span>
          <span>{{ t('clinical.plans.emptyDraft.step1') }}</span>
        </li>
        <li>
          <span class="step-num">2</span>
          <span>{{ t('clinical.plans.emptyDraft.step2') }}</span>
        </li>
        <li>
          <span class="step-num">3</span>
          <span>{{ t('clinical.plans.emptyDraft.step3') }}</span>
        </li>
      </ol>
      <div class="empty-draft-arrow">
        <UIcon
          name="i-lucide-arrow-down-left"
          class="w-5 h-5 animate-bounce"
        />
        <span>{{ t('clinical.plans.emptyDraft.step1') }}</span>
      </div>
    </div>

    <div
      v-else-if="items.length === 0"
      class="text-center py-6 text-muted"
    >
      <UIcon
        name="i-lucide-list"
        class="w-8 h-8 mx-auto mb-2 opacity-50"
      />
      <p>{{ t('clinical.plans.noItems') }}</p>
    </div>

    <!-- Pending items, one draggable list per stage of care. Dragging is
         confined to a phase; disabled when readonly or fewer than 2 items. -->
    <div
      v-for="(group, groupIndex) in pendingGroups"
      :key="group.phase ?? 'unphased'"
      class="space-y-[var(--density-gap,0.5rem)]"
    >
      <div
        v-if="showPhaseHeaders"
        class="phase-header"
      >
        <span class="phase-header-label">{{ phaseLabel(group.phase) }}</span>
        <span class="phase-header-count">{{ group.items.length }}</span>
        <!-- What is chargeable in this phase right now. Absent when nothing
             in it has been performed yet, or when the money view is off. -->
        <span
          v-if="phasePending(group.phase) > 0"
          class="phase-header-pending"
        >
          {{ t('clinical.plans.collection.phasePending', {
            amount: formatCurrency(phasePending(group.phase))
          }) }}
        </span>
      </div>

      <VueDraggable
        v-model="group.items"
        :disabled="readonly || group.items.length < 2"
        handle=".drag-handle"
        :animation="180"
        ghost-class="plan-item-ghost"
        drag-class="plan-item-drag"
        class="space-y-[var(--density-gap,0.5rem)]"
        @end="emitReorder"
      >
        <div
          v-for="(item, index) in group.items"
          :key="item.id"
          tabindex="0"
          class="plan-item p-[var(--density-card-padding-y,0.75rem)_var(--density-card-padding-x,0.75rem)] rounded-token-md border transition-colors cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
          :class="{
            'alert-surface-warning border-transparent': isHighlighted(item.id),
            'bg-surface border-default': !isHighlighted(item.id)
          }"
          :aria-label="t('clinical.plans.item.open', { name: getItemName(item) })"
          @click="emit('item-open', item.id)"
          @mouseenter="emit('item-hover', item.id)"
          @mouseleave="emit('item-hover', null)"
          @keydown="handleKeydown($event, groupIndex, index)"
        >
          <div class="space-y-1">
            <!-- Row 1: nombre del tratamiento a ancho completo, fuera del grid
                 para que nunca se vea estrujado por el contenido lateral. -->
            <div class="font-medium break-words">
              {{ getItemName(item) }}
            </div>

            <!-- Row 2: metadatos + acciones. La columna izquierda sigue
                 siendo flexible; la derecha encaja los iconos sin pelearse
                 con el nombre. -->
            <div class="grid grid-cols-[1fr_auto] items-center gap-2 w-full">
              <div class="flex items-center gap-2 flex-wrap min-w-0">
                <button
                  v-if="!readonly && group.items.length > 1"
                  type="button"
                  class="drag-handle shrink-0 text-subtle hover:text-default cursor-grab active:cursor-grabbing"
                  :title="t('clinical.plans.dragToReorder')"
                  :aria-label="t('clinical.plans.dragToReorder')"
                >
                  <UIcon
                    name="i-lucide-grip-vertical"
                    class="w-4 h-4"
                  />
                </button>
                <span class="text-subtle text-caption tnum w-6 text-center shrink-0">
                  {{ groupOffset(groupIndex) + index + 1 }}.
                </span>
                <!-- Doctor chip stays editable on pending items regardless of
                     the plan-lock state — reassignment is operational and does
                     not touch the patient-facing contract. -->
                <PlanItemDoctorChip
                  :professional-id="item.assigned_professional_id ?? null"
                  :plan-professional-id="planProfessionalId"
                  :readonly="item.status !== 'pending'"
                  @click.stop
                  @change="(professionalId) => emit('item-doctor-change', item.id, professionalId)"
                />
                <span
                  v-if="hasToothInfo(item)"
                  class="text-sm text-muted"
                >
                  {{ formatToothInfo(item) }}
                </span>
                <UBadge
                  v-if="isMultiSession(item)"
                  :color="sessionProgress(item).done > 0 ? 'primary' : 'neutral'"
                  variant="subtle"
                  size="xs"
                >
                  {{ t('clinical.plans.sessions.progress', sessionProgress(item)) }}
                </UBadge>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <span
                  v-if="getItemPrice(item) !== undefined"
                  class="font-medium text-sm"
                >
                  {{ formatCurrency(getItemPrice(item)) }}
                </span>
                <UButton
                  v-if="completeEnabled"
                  size="xs"
                  variant="ghost"
                  color="success"
                  icon="i-lucide-check"
                  :title="t('clinical.plans.markComplete')"
                  @click.stop="openConfirmModal(item)"
                />
                <UButton
                  v-if="!readonly"
                  size="xs"
                  variant="ghost"
                  color="error"
                  icon="i-lucide-trash-2"
                  :title="t('clinical.plans.removeItem')"
                  @click.stop="emit('item-remove', item.id)"
                />
              </div>
            </div>
          </div>

          <!-- Multi-session billing breakdown.
               Single-session items hide this entirely; the legacy "mark
               complete" button still drives the lifecycle for those. -->
          <div
            v-if="isMultiSession(item)"
            class="mt-2 pl-8 space-y-1"
            @click.stop
          >
            <PlanItemSessionRow
              v-for="session in item.sessions"
              :key="session.id"
              :session="session"
              :can-complete="completeEnabled"
              :collection="sessionCollection(session.id)"
              :collection-status="sessionStatus(session.id)"
              @complete="(sessionId) => emit('session-complete', item.id, sessionId)"
              @cancel="(sessionId) => emit('session-cancel', item.id, sessionId)"
            />
          </div>
        </div>
      </VueDraggable>
    </div>

    <!-- Completed items (collapsible) -->
    <UAccordion
      v-if="completedItems.length > 0"
      :items="[{
        label: `${t('common.completed')} (${completedItems.length})`,
        slot: 'completed'
      }]"
      class="mt-3"
    >
      <template #completed>
        <div class="space-y-2 pt-2">
          <div
            v-for="item in completedItems"
            :key="item.id"
            class="p-2 rounded bg-surface-muted text-muted cursor-pointer"
            role="button"
            tabindex="0"
            :aria-label="t('clinical.plans.item.open', { name: getItemName(item) })"
            @click="emit('item-open', item.id)"
            @keydown.enter="emit('item-open', item.id)"
            @mouseenter="emit('item-hover', item.id)"
            @mouseleave="emit('item-hover', null)"
          >
            <div class="flex items-center gap-2">
              <UIcon
                name="i-lucide-check-circle"
                class="w-4 h-4 text-success-accent shrink-0"
              />
              <!-- Indicator chip: the doctor assigned to this treatment.
                   We intentionally show ``assigned_professional_id`` (the
                   planned/responsible clinician) rather than ``completed_by``
                   — completion can be triggered by reception or an admin
                   on behalf of the clinician, and the relevant doctor for
                   the chart is the one who owns the treatment. -->
              <PlanItemDoctorChip
                :professional-id="item.assigned_professional_id ?? null"
                readonly
              />
              <UBadge
                v-if="consentMissing"
                color="error"
                variant="subtle"
                size="xs"
                icon="i-lucide-file-warning"
                class="shrink-0"
                data-testid="item-consent-missing"
              >
                {{ t('treatmentPlans.consentMissing.badge') }}
              </UBadge>
              <span class="line-through flex-1 min-w-0 break-words">
                {{ getItemName(item) }}
              </span>
              <UBadge
                v-if="isClosed(item)"
                color="neutral"
                variant="subtle"
                size="xs"
              >
                {{ t('clinical.plans.item.closed') }}
              </UBadge>
              <span
                v-if="hasToothInfo(item)"
                class="text-xs"
              >
                - {{ formatToothInfo(item) }}
              </span>
            </div>
          </div>
        </div>
      </template>
    </UAccordion>

    <!-- Completion nudge — prompt for a clinical note before flipping the item to completed -->
    <CompletionNudgeModal
      :open="showConfirmModal"
      :item="itemToComplete"
      @update:open="showConfirmModal = $event"
      @confirm="handleNudgeConfirm"
      @cancel="cancelComplete"
    />
  </div>
</template>

<style scoped>
/* Stage-of-care separator. Deliberately quiet — it orders the list, it is
   not a section the eye should land on before the treatments themselves. */
.phase-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 2px 4px;
  margin-top: 4px;
  border-bottom: 1px solid var(--color-border);
}

.phase-header-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted, #6B7280);
}

.phase-header-count {
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  color: var(--color-text-subtle, #9CA3AF);
}

.phase-header-pending {
  margin-left: auto;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #B45309;
  text-transform: none;
  letter-spacing: 0;
}

:root.dark .phase-header-pending {
  color: #FBBF24;
}

/* Onboarding empty state for a freshly created draft plan. */
.empty-draft-guide {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px 14px;
  border: 1px dashed #93C5FD;
  border-radius: 10px;
  background: linear-gradient(180deg, #EFF6FF 0%, #FFFFFF 100%);
}

:root.dark .empty-draft-guide {
  border-color: rgba(59, 130, 246, 0.45);
  background: linear-gradient(180deg, rgba(59, 130, 246, 0.08) 0%, rgba(24, 24, 27, 0) 100%);
}

.empty-draft-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: #1E40AF;
}

:root.dark .empty-draft-title {
  color: #93C5FD;
}

.empty-draft-steps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.empty-draft-steps li {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  line-height: 1.35;
  color: #334155;
}

:root.dark .empty-draft-steps li {
  color: #CBD5E1;
}

.step-num {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #3B82F6;
  color: white;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.empty-draft-arrow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  margin-top: 2px;
  font-size: 12px;
  font-weight: 500;
  color: #1D4ED8;
  background: #DBEAFE;
  border-radius: 8px;
}

:root.dark .empty-draft-arrow {
  background: rgba(59, 130, 246, 0.15);
  color: #BFDBFE;
}

/* Placeholder shown in the slot where the dragged item will land. */
.plan-item-ghost {
  opacity: 0.4;
  background: #EFF6FF;
  border-style: dashed !important;
}

:root.dark .plan-item-ghost {
  background: rgba(59, 130, 246, 0.1);
}

/* Visual style of the item while being dragged. */
.plan-item-drag {
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.15);
  transform: rotate(1deg);
}
</style>
