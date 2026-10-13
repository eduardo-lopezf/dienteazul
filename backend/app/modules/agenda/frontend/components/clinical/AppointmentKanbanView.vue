<script setup lang="ts">
import type { Appointment, AppointmentStatus } from '~~/app/types'
import { formatLocalDate, formatWallClockTime, isoPartsToDateKey, parseIsoParts } from '../../utils/date'

interface Cabinet {
  id?: string
  name: string
  color: string
}

interface ProfessionalWithColor {
  id: string
  first_name: string
  last_name: string
  color: string
}

const props = defineProps<{
  appointments: Appointment[]
  cabinets: Cabinet[]
  professionals: ProfessionalWithColor[]
  currentDate: Date
  isLoading?: boolean
}>()

const emit = defineEmits<{
  'appointment-click': [appointment: Appointment]
  'professional-filter': [professionalId: string | null]
}>()

const { t, locale } = useI18n()
const toast = useToast()
const { fetchAppointments, transition, assignCabinet } = useAppointments()
const completionFollowup = useCompletionFollowup()
const completionCheck = useCompletionCheck()
const { canTransition, statusColour, statusLabel } = useAppointmentStatus()
// Manual 30-second tick — @vueuse/core is not a dependency in this repo.
const now = ref(new Date())

// Professional pill filter: click a pill to focus the board on one pro;
// click the same pill again to clear. Single-select (not multi) to keep
// the strip unambiguous.
const pillFilteredId = ref<string | null>(null)
const stripRef = ref<{ refresh?: () => Promise<void> } | null>(null)

function onPillClick(professionalId: string) {
  pillFilteredId.value = pillFilteredId.value === professionalId
    ? null
    : professionalId
  emit('professional-filter', pillFilteredId.value)
}

// Columns: 5 operational buckets, not 7 per-status columns. Grouping
// sched+confirmed and no_show+cancelled keeps the board readable on a
// regular-width screen.
interface ColumnDef {
  id: 'upcoming' | 'waiting' | 'in_chair' | 'done' | 'missed'
  labelKey: string
  icon: string
  statuses: AppointmentStatus[]
  dropPrimary: AppointmentStatus
  dropAlternatives?: AppointmentStatus[]
  collapsedByDefault?: boolean
}

const COLUMNS: readonly ColumnDef[] = [
  {
    id: 'upcoming',
    labelKey: 'appointments.kanban.upcoming',
    icon: 'i-lucide-calendar',
    statuses: ['scheduled', 'confirmed'],
    dropPrimary: 'scheduled'
  },
  {
    id: 'waiting',
    labelKey: 'appointments.kanban.waiting',
    icon: 'i-lucide-armchair',
    statuses: ['checked_in'],
    dropPrimary: 'checked_in'
  },
  {
    id: 'in_chair',
    labelKey: 'appointments.kanban.inChair',
    icon: 'i-lucide-stethoscope',
    statuses: ['in_treatment'],
    dropPrimary: 'in_treatment'
  },
  {
    id: 'done',
    labelKey: 'appointments.kanban.done',
    icon: 'i-lucide-check-check',
    statuses: ['completed'],
    dropPrimary: 'completed',
    collapsedByDefault: true
  },
  {
    id: 'missed',
    labelKey: 'appointments.kanban.missed',
    icon: 'i-lucide-user-x',
    statuses: ['no_show', 'cancelled'],
    dropPrimary: 'no_show',
    dropAlternatives: ['cancelled'],
    collapsedByDefault: true
  }
]

const collapsedColumns = ref<Set<string>>(
  new Set(COLUMNS.filter(c => c.collapsedByDefault).map(c => c.id))
)

function toggleCollapsed(id: string) {
  const next = new Set(collapsedColumns.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedColumns.value = next
}

// Only keep appointments for the currently selected day. Compares the
// appointment's *wall-clock* date against the selected day: routing
// ``start_time`` through ``new Date()`` first shifted early-morning and
// late-evening cards into the neighbouring day whenever the browser and
// the stored offset disagreed, which is exactly the edge case this
// filter exists to protect.
function isSameDay(iso: string, target: Date): boolean {
  return isoPartsToDateKey(parseIsoParts(iso)) === formatLocalDate(target)
}

const dayAppointments = computed(() =>
  props.appointments.filter(apt => isSameDay(apt.start_time, props.currentDate))
)

function appointmentsForColumn(col: ColumnDef): Appointment[] {
  const list = dayAppointments.value.filter(a => col.statuses.includes(a.status))
  if (col.id === 'waiting') {
    // Longest-waiting first — most urgent in the chair.
    return [...list].sort((a, b) =>
      new Date(a.current_status_since).getTime()
        - new Date(b.current_status_since).getTime()
    )
  }
  if (col.id === 'done') {
    return [...list].sort((a, b) =>
      new Date(b.current_status_since).getTime()
        - new Date(a.current_status_since).getTime()
    )
  }
  return [...list].sort((a, b) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )
}

// Cabinet sub-grouping inside "in chair" — answers "which cabinets are
// occupied right now?" at a glance. Each cabinet block shows either the
// patient card or a "Libre" placeholder. The computed ``state`` drives
// the accent colour: green (free + active), blue (in use), gray
// (inactive).
type CabinetState = 'free' | 'in_use' | 'inactive'

const inChairByCabinet = computed(() => {
  const grouped = new Map<string, Appointment | null>()
  for (const c of props.cabinets) {
    grouped.set(c.name, null)
  }
  for (const apt of dayAppointments.value) {
    if (apt.status === 'in_treatment' && apt.cabinet) {
      grouped.set(apt.cabinet, apt)
    }
  }
  return Array.from(grouped.entries()).map(([cabName, apt]) => {
    const cabinet = props.cabinets.find(c => c.name === cabName) ?? {
      name: cabName,
      color: '#6B7280'
    }
    const isActive = (cabinet as { is_active?: boolean }).is_active !== false
    const state: CabinetState = !isActive
      ? 'inactive'
      : apt !== null
        ? 'in_use'
        : 'free'
    return { cabinet, appointment: apt, state }
  })
})

const CABINET_STATE_ACCENT: Record<CabinetState, string> = {
  free: '#22C55E',
  in_use: '#2563EB',
  inactive: '#9CA3AF'
}

// Next upcoming appointment per cabinet (to show when the cabinet is free).
function nextForCabinet(cabinetName: string): Appointment | null {
  const later = dayAppointments.value
    .filter(a => a.cabinet === cabinetName && ['scheduled', 'confirmed'].includes(a.status))
    .sort((a, b) =>
      new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
    )
  return later[0] ?? null
}

// ---------------------------------------------------------------------
// Drag-and-drop (Pointer Events).
//
// This used to be HTML5 drag-and-drop (`draggable`, `dataTransfer`),
// which Chrome on Android does not implement for touch at all — moving
// a card between columns was impossible on a tablet, not merely
// awkward. Pointer Events cover mouse, finger and stylus in one path.
//
// The drop target is found by hit-testing under the pointer rather than
// by `dragover` on each column, because a captured pointer delivers
// every move to the card, not to whatever is underneath it.
// ---------------------------------------------------------------------
interface DragState {
  appointmentId: string
  targetColumnId: string | null
  targetCabinetName: string | null
  /** Card label, drawn under the pointer while dragging. */
  label: string
  x: number
  y: number
}
const drag = ref<DragState | null>(null)

const { isTouch, isPortrait } = useDevice()

/** How long a finger must rest on a card before it starts dragging. */
const LONG_PRESS_MS = 300
/** Movement that cancels a pending long press — the user is scrolling. */
const LONG_PRESS_SLOP_PX = 10
/** Movement past which a mouse press is a drag, not a click. */
const DRAG_SLOP_PX = 5

let longPressTimer: ReturnType<typeof setTimeout> | null = null
let pressOrigin: { x: number, y: number } | null = null
/** Where the card was picked up, to tell a drag from a plain click. */
let dragOrigin: { x: number, y: number } | null = null
/** The gesture in progress picked the card up, by holding or by moving. */
let pickedUp = false
/**
 * Set on the release of a gesture that picked a card up. The browser still
 * fires a click on that card afterwards, and it would open the appointment
 * the user only meant to move — or to put back where it was.
 */
const suppressClick = ref(false)

function onCardClick(apt: Appointment) {
  if (suppressClick.value) return
  emit('appointment-click', apt)
}
let capturedEl: HTMLElement | null = null
let capturedPointerId: number | null = null

/**
 * Once a touch drag is under way the browser must not also scroll. A
 * non-passive `touchmove` blocker is the only thing that stops it: the
 * long press guarantees the finger was still, so no scroll has been
 * claimed yet and preventDefault still bites.
 */
function blockTouchScroll(e: TouchEvent) {
  e.preventDefault()
}

function armTouchScrollBlock() {
  document.addEventListener('touchmove', blockTouchScroll, { passive: false })
}

function releaseTouchScrollBlock() {
  document.removeEventListener('touchmove', blockTouchScroll)
}

function cancelLongPress() {
  if (longPressTimer !== null) {
    clearTimeout(longPressTimer)
    longPressTimer = null
  }
  pressOrigin = null
}

function beginDrag(apt: Appointment, event: PointerEvent) {
  dragOrigin = { x: event.clientX, y: event.clientY }
  drag.value = {
    appointmentId: apt.id,
    targetColumnId: null,
    targetCabinetName: null,
    label: apt.patient ? `${apt.patient.first_name} ${apt.patient.last_name}` : (apt.title || t('appointments.noPatient', 'Sin paciente')),
    x: event.clientX,
    y: event.clientY
  }
}

/**
 * Press on a card. Dispatches on pointer capability into the pair
 * below, named for what they serve rather than for a device — see
 * `useSlotGridDrag` for the convention and ADR 0022 for the rule.
 *
 * Capturing the pointer is shared: it has to happen for both, and a
 * second copy would only be a second thing to forget.
 */
function onCardPointerDown(apt: Appointment, event: PointerEvent) {
  const el = event.currentTarget as HTMLElement | null
  if (el) {
    capturedEl = el
    capturedPointerId = event.pointerId
    el.setPointerCapture(event.pointerId)
  }

  if (isTouch.value) {
    pressCardByTouch(apt, event)
  } else {
    pressCardWithMouse(apt, event)
  }
}

/**
 * Mouse and trackpad: the cursor was already over the card, so the
 * press can only have meant "pick this up". Drag starts immediately,
 * and no scroll is at stake.
 */
function pressCardWithMouse(apt: Appointment, event: PointerEvent) {
  beginDrag(apt, event)
}

/**
 * Finger and stylus: the press might still be the start of a scroll
 * through a long column, so wait it out. Only once the long press has
 * fired — which proves the finger was still, so the browser has not
 * claimed a scroll — is it safe to block scrolling and start dragging.
 */
function pressCardByTouch(apt: Appointment, event: PointerEvent) {
  pressOrigin = { x: event.clientX, y: event.clientY }
  longPressTimer = setTimeout(() => {
    longPressTimer = null
    armTouchScrollBlock()
    beginDrag(apt, event)
    // Held long enough to lift the card: whatever the release does next,
    // it is not a tap.
    pickedUp = true
  }, LONG_PRESS_MS)
}

/** Resolve what sits under the pointer into a column and cabinet. */
function hitTest(x: number, y: number): { col: ColumnDef | null, cabinetName: string | null } {
  const el = document.elementFromPoint(x, y)
  const columnEl = el?.closest<HTMLElement>('[data-kanban-column]')
  const cabinetEl = el?.closest<HTMLElement>('[data-kanban-cabinet]')
  const col = COLUMNS.find(c => c.id === columnEl?.dataset.kanbanColumn) ?? null
  return { col, cabinetName: cabinetEl?.dataset.kanbanCabinet ?? null }
}

function onDragPointerMove(event: PointerEvent) {
  if (pressOrigin) {
    const moved = Math.hypot(event.clientX - pressOrigin.x, event.clientY - pressOrigin.y)
    if (moved > LONG_PRESS_SLOP_PX) cancelLongPress()
  }

  const state = drag.value
  if (!state) return

  // A mouse lifts the card on press, so only movement says it was dragged
  // rather than clicked.
  if (dragOrigin && Math.hypot(event.clientX - dragOrigin.x, event.clientY - dragOrigin.y) > DRAG_SLOP_PX) {
    pickedUp = true
  }

  const apt = props.appointments.find(a => a.id === state.appointmentId)
  if (!apt) return

  const { col, cabinetName } = hitTest(event.clientX, event.clientY)
  const droppable = col && canDropOn(apt, col)

  drag.value = {
    ...state,
    x: event.clientX,
    y: event.clientY,
    targetColumnId: droppable ? col.id : null,
    targetCabinetName: droppable ? cabinetName : null
  }
}

function endPointerGesture() {
  cancelLongPress()
  releaseTouchScrollBlock()
  dragOrigin = null
  if (capturedEl && capturedPointerId !== null && capturedEl.hasPointerCapture(capturedPointerId)) {
    capturedEl.releasePointerCapture(capturedPointerId)
  }
  capturedEl = null
  capturedPointerId = null
}

async function onDragPointerUp() {
  const state = drag.value
  if (pickedUp) {
    pickedUp = false
    suppressClick.value = true
    setTimeout(() => {
      suppressClick.value = false
    }, 300)
  }
  endPointerGesture()
  if (!state) return

  const col = COLUMNS.find(c => c.id === state.targetColumnId)
  if (!col) {
    // Released outside any valid column — treat as a cancelled drag.
    drag.value = null
    return
  }
  await commitDrop(col, state.targetCabinetName ?? undefined)
}

function onDragPointerCancel() {
  pickedUp = false
  endPointerGesture()
  drag.value = null
}

onUnmounted(() => {
  cancelLongPress()
  releaseTouchScrollBlock()
})

function canDropOn(apt: Appointment, col: ColumnDef): boolean {
  if (col.statuses.includes(apt.status)) {
    // Moving inside the same column does nothing unless it's a cabinet
    // change inside "in chair".
    return col.id === 'in_chair'
  }
  const targets: AppointmentStatus[] = [col.dropPrimary, ...(col.dropAlternatives ?? [])]
  return targets.some(t => canTransition(apt.status, t))
}

function cabinetIdByName(name: string): string | null {
  return props.cabinets.find(c => c.name === name)?.id ?? null
}

async function commitDrop(col: ColumnDef, cabinetName?: string) {
  if (!drag.value) return
  const aptId = drag.value.appointmentId
  const apt = props.appointments.find(a => a.id === aptId)
  drag.value = null
  if (!apt) return

  // Case A: moving within "in chair" — the patient is already being
  // treated, we're just physically moving them to another cabinet.
  if (col.id === 'in_chair' && col.statuses.includes(apt.status)) {
    if (cabinetName && cabinetName !== apt.cabinet) {
      const cabId = cabinetIdByName(cabinetName)
      if (cabId) await safeAssign(aptId, cabId)
    }
    return
  }

  // Case B: transition to another column.
  const target = [col.dropPrimary, ...(col.dropAlternatives ?? [])].find(t =>
    canTransition(apt.status, t)
  )
  if (!target) return

  try {
    // When dropping on a specific cabinet inside "in chair", assign the
    // cabinet FIRST and then transition — the transition to in_treatment
    // requires a cabinet (backend rule from #51). If the second step
    // fails we leave the cabinet assignment in place per the product
    // decision: less confusing than an auto-unassign rollback.
    if (col.id === 'in_chair' && cabinetName && cabinetName !== apt.cabinet) {
      const cabId = cabinetIdByName(cabinetName)
      if (cabId) await safeAssign(aptId, cabId)
    }
    if (target === 'completed' && !(await completionCheck.confirm(apt))) return
    await transition(aptId, target)
    if (target === 'completed') {
      completionFollowup.trigger(apt)
    }
  } catch {
    toast.add({ title: t('appointments.transitionFailed'), color: 'error' })
  }
}

async function safeAssign(aptId: string, cabinetId: string | null) {
  try {
    await assignCabinet(aptId, cabinetId)
  } catch {
    toast.add({ title: t('appointments.conflict'), color: 'error' })
    throw new Error('cabinet_assign_failed')
  }
}

// ---------------------------------------------------------------------
// Live refresh. Polling is suspended when the tab is hidden — no point
// hammering the API when nobody's looking. Comes back instantly on focus.
// ---------------------------------------------------------------------
const POLL_INTERVAL_MS = 30_000
let pollTimer: ReturnType<typeof setInterval> | null = null
let tickTimer: ReturnType<typeof setInterval> | null = null

function startPolling() {
  stopPolling()
  pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible') {
      void refreshDay()
    }
  }, POLL_INTERVAL_MS)
  // Re-evaluate column subtitles ("waiting 12 min") without refetching.
  tickTimer = setInterval(() => {
    now.value = new Date()
  }, 30_000)
}
function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  if (tickTimer !== null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}
async function refreshDay() {
  const start = new Date(props.currentDate)
  start.setHours(0, 0, 0, 0)
  const end = new Date(props.currentDate)
  end.setHours(23, 59, 59, 999)
  await fetchAppointments(start, end)
}

function onVisibilityChange() {
  if (document.visibilityState === 'visible') void refreshDay()
}

onMounted(() => {
  startPolling()
  document.addEventListener('visibilitychange', onVisibilityChange)
})
onBeforeUnmount(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', onVisibilityChange)
})

// ---------------------------------------------------------------------
// Column header counters. Show what the user cares about operationally
// at a glance: how many are waiting, average wait time, cabinets free.
// ---------------------------------------------------------------------
function avgWaitMinutes(): number | null {
  const waiting = appointmentsForColumn(COLUMNS[1]!)
  if (waiting.length === 0) return null
  const total = waiting.reduce((acc, apt) => {
    return acc + (now.value.getTime() - new Date(apt.current_status_since).getTime())
  }, 0)
  return Math.round(total / waiting.length / 60_000)
}

function cabinetsFreeCount(): number {
  return inChairByCabinet.value.filter(x => x.appointment === null).length
}

function cabinetsBusyCount(): number {
  return inChairByCabinet.value.filter(x => x.appointment !== null).length
}

function headerSubtitle(col: ColumnDef): string {
  const items = appointmentsForColumn(col)
  if (col.id === 'waiting') {
    const avg = avgWaitMinutes()
    if (avg === null) return t('appointments.kanban.subtitleEmpty')
    return t('appointments.kanban.subtitleWaiting', { count: items.length, avg })
  }
  if (col.id === 'in_chair') {
    return t('appointments.kanban.subtitleInChair', {
      busy: cabinetsBusyCount(),
      free: cabinetsFreeCount()
    })
  }
  return t('appointments.kanban.subtitleCount', { count: items.length })
}

function isDropHint(col: ColumnDef, cabinetName?: string): boolean {
  return !!drag.value
    && drag.value.targetColumnId === col.id
    && (drag.value.targetCabinetName ?? null) === (cabinetName ?? null)
}

function isInvalidHint(col: ColumnDef): boolean {
  if (!drag.value) return false
  const apt = props.appointments.find(a => a.id === drag.value!.appointmentId)
  if (!apt) return false
  return !canDropOn(apt, col)
}
</script>

<template>
  <div
    class="flex flex-col h-full w-full min-w-0"
    @pointermove="onDragPointerMove"
    @pointerup="onDragPointerUp"
    @pointercancel="onDragPointerCancel"
  >
    <!-- Drag ghost. Without something following the pointer a touch drag
         reads as "nothing happened" until the finger is lifted. -->
    <Teleport to="body">
      <div
        v-if="drag"
        class="pointer-events-none fixed z-[100] -translate-x-1/2 -translate-y-1/2 rounded-md bg-surface px-3 py-2 text-ui text-default shadow-token-lg ring-1 ring-[var(--color-primary)]"
        :style="{ left: `${drag.x}px`, top: `${drag.y}px` }"
      >
        {{ drag.label }}
      </div>
    </Teleport>
    <!-- Professionals strip (#51): one pill per working pro today, live
         state derived from appointments + schedules. -->
    <ProfessionalsStrip
      ref="stripRef"
      :current-date="currentDate"
      :professionals="professionals"
      :filtered-id="pillFilteredId"
      @pill-click="onPillClick"
    />

    <!-- Loading -->
    <div
      v-if="isLoading"
      class="flex items-center justify-center py-12"
    >
      <UIcon
        name="i-lucide-loader-2"
        class="w-8 h-8 animate-spin"
        :style="{ color: 'var(--color-primary)' }"
      />
    </div>

    <!-- Kanban scroll container: the scroll lives HERE so the header +
         filters above stay within the viewport.

         Landscape keeps the five columns side by side and scrolls
         sideways. Portrait wraps them into two and scrolls vertically:
         5 x 260 px needs 1320 px, which a portrait tablet has not got,
         and it was spending its 1280 px of height on empty column
         bodies to buy a sideways scroll nobody wants. -->
    <div
      v-else
      class="flex-1 min-h-0 min-w-0"
      :class="isPortrait ? 'overflow-y-auto overflow-x-hidden' : 'overflow-x-auto overflow-y-hidden'"
    >
      <div
        class="grid gap-3 pb-2"
        :class="isPortrait ? 'auto-rows-[minmax(220px,auto)]' : 'h-full'"
        :style="isPortrait
          ? { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }
          : { gridTemplateColumns: 'repeat(5, minmax(260px, 1fr))', minWidth: '1320px' }"
      >
        <div
          v-for="col in COLUMNS"
          :key="col.id"
          class="flex flex-col rounded-lg ring-1 ring-[var(--color-border)] bg-surface-muted min-h-0"
          :class="{
            'ring-2 ring-[var(--color-primary)]': drag && isDropHint(col),
            'opacity-60 ring-dashed ring-red-300': drag && isInvalidHint(col)
          }"
          :data-kanban-column="col.id"
        >
          <!-- Header -->
          <div
            class="flex items-center justify-between px-3 py-2 border-b border-default bg-surface rounded-t-lg cursor-pointer select-none"
            @click="toggleCollapsed(col.id)"
          >
            <div class="flex items-center gap-2 min-w-0">
              <UIcon
                :name="col.icon"
                class="w-4 h-4 shrink-0"
                :style="{ color: statusColour(col.dropPrimary) }"
              />
              <div class="min-w-0">
                <div class="text-ui text-default truncate">
                  {{ t(col.labelKey) }}
                </div>
                <div class="text-caption text-subtle truncate">
                  {{ headerSubtitle(col) }}
                </div>
              </div>
            </div>
            <UIcon
              :name="collapsedColumns.has(col.id) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-up'"
              class="w-4 h-4 text-subtle"
            />
          </div>

          <!-- Body -->
          <div
            v-if="!collapsedColumns.has(col.id)"
            class="flex-1 overflow-auto p-2 space-y-2"
          >
            <!-- Sub-grouping by cabinet inside "in chair" -->
            <template v-if="col.id === 'in_chair'">
              <div
                v-for="entry in inChairByCabinet"
                :key="entry.cabinet.name"
                class="rounded-md ring-1 ring-[var(--color-border)] bg-surface p-2 border-l-4 transition-shadow"
                :style="{ borderLeftColor: CABINET_STATE_ACCENT[entry.state] }"
                :class="{ 'ring-2 ring-[var(--color-primary)]': drag && isDropHint(col, entry.cabinet.name) }"
                :data-kanban-cabinet="entry.cabinet.name"
              >
                <div class="flex items-center gap-2 mb-1.5">
                  <span
                    class="w-2.5 h-2.5 rounded-full"
                    :style="{ backgroundColor: entry.cabinet.color }"
                  />
                  <span class="text-ui text-default truncate">{{ entry.cabinet.name }}</span>
                  <span
                    v-if="!entry.appointment"
                    class="ml-auto text-caption text-subtle italic"
                  >{{ entry.state === 'inactive' ? t('appointments.kanban.inactive') : t('appointments.kanban.free') }}</span>
                </div>
                <AppointmentCard
                  v-if="entry.appointment"
                  :appointment="entry.appointment"
                  :cabinets="cabinets"
                  :professionals="professionals"
                  :class="drag?.appointmentId === entry.appointment.id ? 'opacity-40' : ''"
                  @click="onCardClick(entry.appointment as Appointment)"
                  @pointerdown="onCardPointerDown(entry.appointment as Appointment, $event)"
                />
                <div
                  v-else-if="nextForCabinet(entry.cabinet.name)"
                  class="text-caption text-subtle italic px-1"
                >
                  {{ t('appointments.kanban.nextIn', {
                    time: formatWallClockTime(nextForCabinet(entry.cabinet.name)!.start_time, locale)
                  }) }}
                </div>
              </div>
            </template>

            <!-- Flat card list for every other column -->
            <template v-else>
              <AppointmentCard
                v-for="apt in appointmentsForColumn(col)"
                :key="apt.id"
                :appointment="apt"
                :cabinets="cabinets"
                :professionals="professionals"
                :class="drag?.appointmentId === apt.id ? 'opacity-40' : ''"
                @click="onCardClick(apt)"
                @pointerdown="onCardPointerDown(apt, $event)"
              />
              <div
                v-if="appointmentsForColumn(col).length === 0"
                class="text-center text-subtle text-sm py-6"
              >
                {{ t('appointments.kanban.empty') }}
              </div>
            </template>
          </div>

          <!-- Collapsed footer -->
          <div
            v-else
            class="px-3 py-2 text-caption text-subtle"
          >
            {{ statusLabel(col.dropPrimary) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
