<script setup lang="ts">
/**
 * ToothDiagnosisModal — the card a tooth opens when clicked with no
 * treatment armed (or right-clicked): the anatomical chart (`ToothQuadrant`,
 * the main chart's layout, shrunk to the card's width) to pick the teeth, and the findings of a diagnosis (`utils/toothFindings`), each a
 * switch with the icon the chart draws it with.
 *
 * The clicked tooth comes picked; clicking others on the card's chart adds
 * or drops them, so brackets on a whole arch is one press. A switch applies
 * to every picked tooth: on all of them already, it comes off; otherwise it
 * goes on the ones that lack it. Surface findings (caries) need one tooth.
 *
 * Presses are pending (`FindingDraft`): the card's chart and switches show
 * them, *Aceptar* hands them to the chart to save, *Cancelar* (or closing
 * the card) drops them. *Deshacer* / *Rehacer* (Ctrl+Z, Ctrl+Shift+Z or
 * Ctrl+Y) step through the presses; *Limpiar* takes every finding the card
 * may remove off the picked teeth at once, as one pending step that can
 * itself be undone, and says how many are not its to remove. Caries and
 * *Erupción…* save what is pending first,
 * since they leave the card. The chart charts, so its own state (undo,
 * toasts, history) stays the one source.
 */
import type { ToothTreatmentView } from '~~/app/types'
import { getToothNameKey } from '~~/app/config/odontogramConstants'
import type { EruptionStatus, TeethLayout } from '../../utils/dentitionLayout'
import { nomColor } from '../../utils/nomColors'
import {
  MAIN_FINDINGS,
  OTHER_FINDINGS,
  clearDraft,
  draftChanges,
  draftViews,
  selectionSummary,
  toggleDraft,
  type FindingChange,
  type FindingDraft,
  type TeethFacts,
  type ToothFinding
} from '../../utils/toothFindings'
import { getTreatmentIcon } from './TreatmentIcons'

const props = withDefaults(defineProps<{
  /** The tooth clicked, or `null` while closed. */
  toothNumber: number | null
  /** What is charted on a tooth now. */
  getTreatments: (tooth: number) => ToothTreatmentView[]
  getEruptionStatus: (tooth: number) => EruptionStatus | null
  /** The teeth the chart shows, quadrant by quadrant, and those dimmed. */
  layout: TeethLayout
  dimmedTeeth?: number[]
  /** The tooth record's condition and position, as the chart reads them. */
  getToothData: (tooth: number) => { generalCondition: string, isDisplaced: boolean, isRotated: boolean }
  /** The pending changes are being saved: the card waits. */
  saving?: boolean
}>(), {
  dimmedTeeth: () => [],
  saving: false
})

const emit = defineEmits<{
  /** Closed without saving: what is pending is dropped. */
  cancel: []
  /** Save the changes, then close. */
  accept: [changes: FindingChange[]]
  /** Save the changes, then mark surfaces of the tooth. */
  surface: [finding: ToothFinding, tooth: number, changes: FindingChange[]]
  /** Save the changes, then open the tooth's eruption card. */
  eruption: [tooth: number, changes: FindingChange[]]
}>()

const { t } = useI18n()

/** The teeth the switches apply to, in the order they were picked. */
const picked = ref<number[]>([])
/** Presses not saved yet. */
const draft = ref<FindingDraft>(new Map())
/** Earlier drafts, for *Deshacer*; undone ones, for *Rehacer*. */
const past = ref<FindingDraft[]>([])
const future = ref<FindingDraft[]>([])
watch(() => props.toothNumber, (tooth) => {
  picked.value = tooth === null ? [] : [tooth]
  draft.value = new Map()
  past.value = []
  future.value = []
}, { immediate: true })

/** A new draft: the old one can be gone back to, nothing is redone. */
function commitDraft(next: FindingDraft) {
  past.value = [...past.value, draft.value]
  future.value = []
  draft.value = next
}

function undo() {
  const previous = past.value.at(-1)
  if (!previous || props.saving) return
  past.value = past.value.slice(0, -1)
  future.value = [...future.value, draft.value]
  draft.value = previous
}

function redo() {
  const next = future.value.at(-1)
  if (!next || props.saving) return
  future.value = future.value.slice(0, -1)
  past.value = [...past.value, draft.value]
  draft.value = next
}

/** The picked teeth with nothing on them the card charts. */
function clear() {
  if (props.saving || !clearable.value.cleared) return
  commitDraft(clearable.value.next)
}

function onKeydown(e: KeyboardEvent) {
  if (props.toothNumber === null || !(e.ctrlKey || e.metaKey)) return
  const key = e.key.toLowerCase()
  if (key === 'z' && !e.shiftKey) {
    e.preventDefault()
    undo()
  } else if ((key === 'z' && e.shiftKey) || key === 'y') {
    e.preventDefault()
    redo()
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function togglePick(tooth: number) {
  picked.value = picked.value.includes(tooth)
    ? picked.value.filter(t => t !== tooth)
    : [...picked.value, tooth]
}

const sortedPicked = computed(() => [...picked.value].sort((a, b) => a - b))
const single = computed(() => (picked.value.length === 1 ? picked.value[0]! : null))

const facts = computed<TeethFacts>(() => ({
  viewsOf: props.getTreatments,
  statusOf: props.getEruptionStatus
}))

function summaryOf(finding: ToothFinding) {
  return selectionSummary(finding, picked.value, facts.value, draft.value)
}

/** The card's chart shows the teeth as they will be once saved. */
function previewTreatments(tooth: number) {
  return draftViews(tooth, facts.value, draft.value)
}

const pendingCount = computed(() => draft.value.size)

/** What *Limpiar* would take off the picked teeth, and what it cannot. */
const clearable = computed(() => clearDraft(picked.value, facts.value, draft.value))

function press(finding: ToothFinding) {
  if (finding.kind === 'surface') {
    if (single.value !== null) emit('surface', finding, single.value, draftChanges(draft.value))
    return
  }
  const next = toggleDraft(finding, picked.value, facts.value, draft.value)
  // A press that changes nothing (a locked finding) is not a step to undo.
  const same = next.size === draft.value.size
    && [...next].every(([key, on]) => draft.value.get(key) === on)
  if (same) return
  commitDraft(next)
}

function accept() {
  emit('accept', draftChanges(draft.value))
}

function isOn(finding: ToothFinding): boolean {
  const s = summaryOf(finding)
  return s.total > 0 && s.active === s.total
}

function disabled(finding: ToothFinding): boolean {
  if (props.saving) return true
  if (!picked.value.length) return true
  if (finding.kind === 'surface' && single.value === null) return true
  return summaryOf(finding).locked
}

function hint(finding: ToothFinding): string | undefined {
  if (finding.kind === 'surface') {
    return t(single.value === null ? 'odontogram.findings.oneToothHint' : 'odontogram.findings.surfaceHint')
  }
  if (summaryOf(finding).locked) return t('odontogram.findings.lockedHint')
  return undefined
}

/** The icon in the colour the chart will draw it in. */
function iconColor(finding: ToothFinding): string {
  return nomColor(finding.type ?? 'unerupted', finding.status ?? 'existing')
}

const title = computed(() => {
  if (single.value !== null) {
    return t('odontogram.findings.title', { tooth: single.value, name: t(getToothNameKey(single.value)) })
  }
  if (!picked.value.length) return t('odontogram.findings.noTeeth')
  return t('odontogram.findings.titleMany', { teeth: sortedPicked.value.join(', ') })
})

/** Upper arch above, lower below; the patient's right on the chart's left. */
const arches = computed(() => [
  { key: 'upper', quadrants: [props.layout.upperRight, props.layout.upperLeft] },
  { key: 'lower', quadrants: [props.layout.lowerRight, props.layout.lowerLeft] }
])

const groups = computed(() => [
  { key: 'main', title: t('odontogram.findings.main'), items: MAIN_FINDINGS },
  { key: 'other', title: t('odontogram.findings.other'), items: OTHER_FINDINGS }
])
</script>

<template>
  <UModal
    :open="toothNumber !== null"
    :ui="{ content: 'sm:max-w-5xl' }"
    @update:open="(open: boolean) => { if (!open) emit('cancel') }"
  >
    <template #content>
      <UCard
        v-if="toothNumber !== null"
        data-testid="tooth-diagnosis-modal"
        :ui="{ root: 'flex flex-col max-h-[calc(100dvh-2rem)]', body: 'overflow-y-auto min-h-0' }"
      >
        <template #header>
          <h2
            class="text-h2 text-default"
            data-testid="tooth-diagnosis-title"
          >
            {{ title }}
          </h2>
          <div class="flex items-start justify-between gap-2">
            <p class="text-caption text-subtle mt-1">
              {{ t('odontogram.findings.help') }}
            </p>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-sprout"
              class="shrink-0"
              :disabled="single === null || saving"
              :title="single === null ? t('odontogram.findings.oneToothHint') : undefined"
              data-testid="tooth-diagnosis-eruption"
              @click="single !== null && emit('eruption', single, draftChanges(draft))"
            >
              {{ t('odontogram.findings.eruption') }}
            </UButton>
          </div>
        </template>

        <div class="space-y-4">
          <div
            class="diagnosis-chart rounded-token-lg border border-subtle p-2"
            data-testid="tooth-diagnosis-chart"
          >
            <!-- data-dense: an arch is anatomy; sixteen teeth side by side
                 cannot each be 44 px on a tablet. The touch interaction is
                 real: a tap picks or drops the tooth, and what follows is
                 the finger-sized switches below. -->
            <div
              data-dense
              class="diagnosis-grid"
            >
              <div
                v-for="arch in arches"
                :key="arch.key"
                class="diagnosis-arch"
                :data-arch="arch.key"
              >
                <ToothQuadrant
                  v-for="(teeth, i) in arch.quadrants"
                  :key="i"
                  :teeth="teeth"
                  :get-tooth-data="getToothData"
                  :get-treatments="previewTreatments"
                  :readonly="false"
                  :selected-tooth="null"
                  :show-lateral="true"
                  :hovered-tooth="null"
                  :highlighted-teeth="[]"
                  :pending-treatment="null"
                  :multi-selected-teeth="picked"
                  :dimmed-teeth="dimmedTeeth"
                  :get-eruption-status="getEruptionStatus"
                  tooltips-blocked
                  :class="i === 0 ? 'diagnosis-quadrant-right' : ''"
                  @tooth-click="togglePick"
                  @surface-click="(tooth: number) => togglePick(tooth)"
                />
              </div>
            </div>
            <div class="flex items-center justify-between gap-2 mt-2 text-caption text-muted">
              <span data-testid="tooth-diagnosis-picked">
                {{ t('odontogram.findings.picked', { count: picked.length }, picked.length) }}
              </span>
              <UButton
                v-if="picked.length > 1"
                size="xs"
                color="neutral"
                variant="ghost"
                @click="picked = toothNumber === null ? [] : [toothNumber]"
              >
                {{ t('odontogram.findings.onlyThis', { tooth: toothNumber }) }}
              </UButton>
            </div>
          </div>

          <section
            v-for="group in groups"
            :key="group.key"
            class="space-y-2"
          >
            <h3 class="text-sm font-medium text-muted">
              {{ group.title }}
            </h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
              <UButton
                v-for="finding in group.items"
                :key="finding.key"
                :color="isOn(finding) ? 'primary' : 'neutral'"
                :variant="isOn(finding) ? 'soft' : 'outline'"
                :disabled="disabled(finding)"
                :title="hint(finding)"
                :aria-pressed="finding.kind === 'surface' ? undefined : isOn(finding)"
                :data-testid="`tooth-finding-${finding.key}`"
                :data-active="isOn(finding)"
                class="justify-start"
                block
                @click="press(finding)"
              >
                <svg
                  viewBox="0 0 24 24"
                  class="finding-icon"
                  :style="{ color: iconColor(finding) }"
                  aria-hidden="true"
                  v-html="getTreatmentIcon(finding.icon)"
                />
                <span class="flex-1 text-left">{{ t(`odontogram.findings.items.${finding.key}`) }}</span>
                <UBadge
                  v-if="picked.length > 1 && summaryOf(finding).active > 0 && !isOn(finding)"
                  size="sm"
                  color="neutral"
                  variant="subtle"
                >
                  {{ summaryOf(finding).active }}/{{ picked.length }}
                </UBadge>
                <UIcon
                  v-if="isOn(finding)"
                  name="i-lucide-check"
                  class="size-4"
                />
              </UButton>
            </div>
          </section>
        </div>

        <template #footer>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-1">
              <UButton
                color="neutral"
                variant="outline"
                icon="i-lucide-undo-2"
                :disabled="!past.length || saving"
                :title="t('odontogram.findings.undoHint')"
                data-testid="tooth-diagnosis-undo"
                @click="undo"
              >
                {{ t('odontogram.findings.undo') }}
              </UButton>
              <UButton
                color="neutral"
                variant="outline"
                icon="i-lucide-redo-2"
                :disabled="!future.length || saving"
                :title="t('odontogram.findings.redoHint')"
                data-testid="tooth-diagnosis-redo"
                @click="redo"
              >
                {{ t('odontogram.findings.redo') }}
              </UButton>
              <UButton
                color="neutral"
                variant="outline"
                icon="i-lucide-eraser"
                :disabled="!clearable.cleared || saving"
                :title="t('odontogram.findings.clearHint')"
                data-testid="tooth-diagnosis-clear"
                @click="clear"
              >
                {{ t('odontogram.findings.clear') }}
              </UButton>
            </div>
            <div class="flex items-center gap-2 ms-auto">
              <!-- A blank tooth is not always the card's to give: what came
                   from a catalog item, a plan or several teeth at once stays,
                   and saying so beats a button that silently leaves it. -->
              <span
                v-if="clearable.locked"
                class="text-caption text-muted"
                data-testid="tooth-diagnosis-locked"
              >
                {{ t('odontogram.findings.clearLocked', { count: clearable.locked }, clearable.locked) }}
              </span>
              <span
                v-if="pendingCount"
                class="text-caption text-muted"
                data-testid="tooth-diagnosis-pending"
              >
                {{ t('odontogram.findings.pending', { count: pendingCount }, pendingCount) }}
              </span>
              <UButton
                color="error"
                variant="solid"
                :disabled="saving"
                data-testid="tooth-diagnosis-cancel"
                @click="emit('cancel')"
              >
                {{ t('actions.cancel') }}
              </UButton>
              <UButton
                color="success"
                variant="solid"
                :loading="saving"
                data-testid="tooth-diagnosis-accept"
                @click="accept"
              >
                {{ t('odontogram.findings.accept') }}
              </UButton>
            </div>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>

<style scoped>
.finding-icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
}

/* The arches keep the main chart's size and shrink, in steps, to the width
   the card has (`zoom`, like `OdontogramChart`'s ladder): ~1050 px at full
   size, so a tablet in landscape draws them nearly whole and one upright at
   about two thirds. Sized to their content and centred with auto margins,
   so if they still do not fit they scroll instead of losing the molars. */
.diagnosis-chart {
  container-type: inline-size;
  overflow-x: auto;
}

.diagnosis-grid {
  width: max-content;
  margin-inline: auto;
  /* Room for the lower teeth's numbers, which sit under their cells. */
  padding-bottom: 20px;
  display: flex;
  flex-direction: column;
  /* The upper teeth's numbers hang under their cells, as on the main chart
     (whose upper arch has 24 px below it). */
  gap: 32px;
}

.diagnosis-arch {
  display: flex;
  justify-content: center;
}

.diagnosis-quadrant-right {
  padding-right: 8px;
  margin-right: 8px;
  border-right: 1px solid var(--color-border-strong);
}

@container (max-width: 1060px) { .diagnosis-grid { zoom: 0.9; } }
@container (max-width: 950px) { .diagnosis-grid { zoom: 0.8; } }
@container (max-width: 850px) { .diagnosis-grid { zoom: 0.72; } }
@container (max-width: 760px) { .diagnosis-grid { zoom: 0.64; } }
@container (max-width: 680px) { .diagnosis-grid { zoom: 0.56; } }
@container (max-width: 600px) { .diagnosis-grid { zoom: 0.48; } }
@container (max-width: 520px) { .diagnosis-grid { zoom: 0.42; } }
@container (max-width: 460px) { .diagnosis-grid { zoom: 0.36; } }

/* Picked teeth: the multi-selection outline, without its pulse. */
.diagnosis-chart :deep(.tooth-cell.in-multi-selection) {
  animation: none;
  background: var(--color-primary-soft);
}
</style>
