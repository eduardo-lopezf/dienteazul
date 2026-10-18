<script setup lang="ts">
import type { Appointment, Professional } from '~~/app/types'
import type { BlockedSegment } from '../../composables/useBlockedSegments'
import { calculateOverlapGroups } from '../../composables/calculateOverlapGroups'
import { formatLocalDate } from '../../utils/date'

const notesIndicator = useAppointmentNotesIndicator()

interface ProfessionalWithColor extends Professional {
  color: string
}

const props = defineProps<{
  appointments: Appointment[]
  professionals: ProfessionalWithColor[]
  currentDate: Date
  isLoading?: boolean
  highlightedAppointmentId?: string | null
}>()

const emit = defineEmits<{
  'slot-click': [professionalId: string, time: string]
  'slot-drag-create': [professionalId: string, startTime: string, endTime: string]
  'appointment-click': [appointment: Appointment]
  'appointment-move': [appointmentId: string, newProfessionalId: string, newStartTime: string, newEndTime: string]
  'appointment-resize': [appointmentId: string, newEndTime: string]
  'highlight-cleared': []
}>()

// Clear highlight after animation completes (5 seconds)
watch(() => props.highlightedAppointmentId, (newId) => {
  if (newId) {
    setTimeout(() => {
      emit('highlight-cleared')
    }, 5000)
  }
}, { immediate: true })

const { t } = useI18n()

// Time slots configuration. Narrowed to actual clinic hours via
// schedules module; 8–21 fallback when that module is uninstalled.
const startHour = ref(8)
const endHour = ref(21)
const SLOT_MINUTES = 15
const SLOTS_PER_HOUR = 60 / SLOT_MINUTES

const { compute: computeCalendarBounds } = useCalendarBounds()
const { compute: computeBlockedSegments } = useBlockedSegments({
  startHour,
  endHour,
  slotMinutes: SLOT_MINUTES
})

const blockedSegments = ref<BlockedSegment[]>([])

async function refreshAvailability() {
  const bounds = await computeCalendarBounds({ start: props.currentDate, end: props.currentDate })
  startHour.value = bounds.startHour
  endHour.value = bounds.endHour

  blockedSegments.value = await computeBlockedSegments({
    start: props.currentDate,
    end: props.currentDate,
    professionals: props.professionals
  })
}

watch(
  () => [props.currentDate, props.professionals.map(p => p.id).join(',')],
  () => { void refreshAvailability() },
  { immediate: true }
)

// `effective`, not `density`: see AppointmentCalendar — the preference
// can say "compact" while a coarse pointer forces the touch scale, and
// the drag maths must agree with the CSS variable that is drawn.
const { effective: _calendarDensity } = useDensity()
function getSlotHeight() {
  return _calendarDensity.value === 'compact' ? 18 : 28
}

const calendarRef = ref<HTMLElement | null>(null)

/** Slot of a `HH:MM` wall-clock time on this grid. */
function slotOfTime(iso: string): number {
  return getSlotIndex(iso.split('T')[1]?.substring(0, 5) ?? '08:00')
}

// Rows grow where a booked appointment needs the room to be read.
const slotRows = useSlotRows({
  slotCount: () => (endHour.value - startHour.value) * SLOTS_PER_HOUR,
  baseHeight: getSlotHeight,
  spans: () =>
    [...appointmentsByProfIndex.value.values()].flat().map(appointment => ({
      start: slotOfTime(appointment.start_time),
      end: slotOfTime(appointment.end_time)
    }))
})

const { isPortrait } = useDevice()

/**
 * How wide the grid insists on being, which is what decides whether it
 * scrolls sideways.
 *
 * A professional's column wants 200 px: that is what an appointment card
 * needs for a time, a patient and a treatment. A clinic with more
 * professionals than fit simply scrolls to reach them, which on a
 * landscape screen costs nothing.
 *
 * Held upright there is no sideways room to spend. The portrait default
 * lands on this view precisely because a seven-day week does not fit
 * across a tablet — but 200 px x five professionals is 1080, and against
 * the ~620 px an upright tablet has that put nearly half the day off the
 * right edge. So portrait asks for the narrowest column a card is still
 * readable in and lets the columns share what width exists; past that it
 * scrolls, rather than shrinking them into illegibility.
 *
 * Orientation changes the layout, never the interaction
 * ([ADR 0022](../../../../../../docs/adr/0022-touch-adaptation-is-capability-driven.md)).
 */
const COLUMN_WIDTH = 200
const COLUMN_WIDTH_PORTRAIT = 104
const TIME_GUTTER = 80

const gridMinWidth = computed(() => {
  const perColumn = isPortrait.value ? COLUMN_WIDTH_PORTRAIT : COLUMN_WIDTH
  return `${perColumn * props.professionals.length + TIME_GUTTER}px`
})

const {
  dragState,
  createDragState,
  selectedId,
  wasDragging,
  isTouch,
  onCellPointerDown,
  onAppointmentPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  clearSelection
} = useSlotGridDrag({
  slotHeight: getSlotHeight,
  slotTop: slotRows.top,
  maxSlotIndex: () => (endHour.value - startHour.value) * SLOTS_PER_HOUR - 1,
  columnCount: () => props.professionals.length,
  gutterColumns: 1,
  containerRef: calendarRef,

  onCreateRange: (profIndex, startSlot, endSlot) => {
    const prof = props.professionals[profIndex]
    if (prof) emit('slot-drag-create', prof.id, slotIndexToTime(startSlot), slotIndexToTime(endSlot))
  },

  onCreatePoint: (profIndex, slot) => {
    const prof = props.professionals[profIndex]
    if (prof) emit('slot-click', prof.id, slotIndexToTime(slot))
  },

  onMove: (appointmentId, profIndex, startSlot, endSlot) => {
    const appointment = props.appointments.find(a => a.id === appointmentId)
    const prof = props.professionals[profIndex]
    if (!appointment || !prof) return

    const newStartTime = slotIndexToTime(startSlot)
    const oldStartTime = appointment.start_time.split('T')[1]?.substring(0, 5) ?? ''
    if (newStartTime === oldStartTime && prof.id === (appointment.professional_id ?? '')) return

    emit('appointment-move', appointmentId, prof.id, newStartTime, slotIndexToTime(endSlot))
  },

  onResize: (appointmentId, endSlot) => {
    const appointment = props.appointments.find(a => a.id === appointmentId)
    if (!appointment) return

    const newEndTime = slotIndexToTime(endSlot)
    const oldEndTime = appointment.end_time.split('T')[1]?.substring(0, 5) ?? ''
    if (newEndTime === oldEndTime) return
    emit('appointment-resize', appointmentId, newEndTime)
  }
})

// A selection is about one specific block; carrying it across a day
// change would leave an off-screen block holding `touch-action: none`.
watch(() => props.currentDate, () => clearSelection())

function startAppointmentDrag(
  type: 'move' | 'resize',
  appointment: Appointment,
  event: PointerEvent
) {
  const startTime = appointment.start_time.split('T')[1]?.substring(0, 5) ?? '08:00'
  const endTime = appointment.end_time.split('T')[1]?.substring(0, 5) ?? '08:15'
  const profIndex = props.professionals.findIndex(p => p.id === (appointment.professional_id ?? ''))
  onAppointmentPointerDown(
    {
      type,
      appointmentId: appointment.id,
      columnIndex: profIndex,
      startSlot: getSlotIndex(startTime),
      endSlot: getSlotIndex(endTime)
    },
    event
  )
}

/** Tap-to-create; a finger gets no drag on empty space. */
function onCellClick(profIndex: number, slotIndex: number) {
  if (!isTouch.value) return
  const prof = props.professionals[profIndex]
  if (prof) emit('slot-click', prof.id, slotIndexToTime(slotIndex))
}

/** `touch-action: none` only on the selected block, so the grid scrolls. */
function getTouchActionStyle(appointment: Appointment): Record<string, string> {
  return selectedId.value === appointment.id ? { touchAction: 'none' } : {}
}

// Generate time slots
const timeSlots = computed(() => {
  const slots: string[] = []
  for (let hour = startHour.value; hour < endHour.value; hour++) {
    for (let quarter = 0; quarter < SLOTS_PER_HOUR; quarter++) {
      const minutes = quarter * SLOT_MINUTES
      slots.push(`${hour.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`)
    }
  }
  return slots
})

// Calculate slot index from time string
function getSlotIndex(timeStr: string): number {
  const parts = timeStr.split(':').map(Number)
  const hours = parts[0] ?? 0
  const minutes = parts[1] ?? 0
  return (hours - startHour.value) * SLOTS_PER_HOUR + Math.floor(minutes / SLOT_MINUTES)
}

function slotIndexToTime(slotIndex: number): string {
  const totalMinutes = startHour.value * 60 + slotIndex * SLOT_MINUTES
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`
}

// Get appointment style
function getAppointmentStyle(appointment: Appointment): Record<string, string> {
  if (dragState.value?.appointmentId === appointment.id) {
    return {
      top: `${dragState.value.currentTop}px`,
      height: `${dragState.value.currentHeight}px`,
      minHeight: `${getSlotHeight()}px`,
      opacity: '0.8',
      zIndex: '50'
    }
  }

  const startTime = appointment.start_time.split('T')[1]?.substring(0, 5) ?? '08:00'
  const endTime = appointment.end_time.split('T')[1]?.substring(0, 5) ?? '08:15'

  const startSlot = getSlotIndex(startTime)
  const endSlot = getSlotIndex(endTime)
  const spanSlots = Math.max(1, endSlot - startSlot)

  const height = slotRows.span(startSlot, startSlot + spanSlots)
  const topOffset = slotRows.top(startSlot)

  return {
    top: `${topOffset}px`,
    height: `${height}px`,
    minHeight: `${getSlotHeight()}px`
  }
}

// Tint + rail for an appointment block (DESIGN §7.3): fill alpha 0.12, left border 3 px.
function getProfessionalFill(hex: string): Record<string, string> {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return {
    backgroundColor: `rgba(${r}, ${g}, ${b}, 0.12)`,
    borderLeftColor: hex,
    borderLeftWidth: '3px'
  }
}

// Status styling — fill tinted from professional colour (inline), status modulates text/opacity.
function getStatusClass(status: Appointment['status']): string {
  const baseClass = 'bg-surface ring-1 ring-[var(--color-border)]'
  switch (status) {
    case 'scheduled':
    case 'confirmed':
      return `${baseClass} text-default`
    case 'checked_in':
    case 'in_treatment':
      return `${baseClass} text-default`
    case 'completed':
      return `${baseClass} text-muted opacity-70`
    case 'cancelled':
      return `${baseClass} text-subtle line-through opacity-50`
    case 'no_show':
      return `${baseClass} text-subtle opacity-60`
    default:
      return baseClass
  }
}

function getStatusIcon(status: Appointment['status']): string {
  switch (status) {
    case 'confirmed': return 'i-lucide-check'
    case 'checked_in': return 'i-lucide-door-open'
    case 'in_treatment': return 'i-lucide-stethoscope'
    case 'completed': return 'i-lucide-check-check'
    case 'cancelled': return 'i-lucide-x'
    case 'no_show': return 'i-lucide-user-x'
    default: return ''
  }
}

// Tap or click an appointment. Suppressed right after a drag so
// releasing a moved appointment does not also open it.
function handleAppointmentClick(appointment: Appointment, event: Event) {
  if (dragState.value || wasDragging.value) return
  event.stopPropagation()
  emit('appointment-click', appointment)
}

// Pre-bucket the current day's appointments by professional id. One pass over
// props.appointments instead of N (one per professional column).
const appointmentsByProfId = computed(() => {
  const dateStr = formatLocalDate(props.currentDate)
  const map = new Map<string, Appointment[]>()
  for (const apt of props.appointments) {
    if (apt.status === 'cancelled') continue
    if (apt.start_time.split('T')[0] !== dateStr) continue
    // '' is the unassigned column the page adds (see `dayViewColumns`).
    const profId = apt.professional_id ?? ''
    let bucket = map.get(profId)
    if (!bucket) {
      bucket = []
      map.set(profId, bucket)
    }
    bucket.push(apt)
  }
  return map
})

// Per-id overlap position {index,total}. Independent of drag state so it does
// not recompute on every pointer move.
const overlapPositions = computed(() => {
  const positions = new Map<string, { index: number, total: number }>()
  for (const bucket of appointmentsByProfId.value.values()) {
    const profPositions = calculateOverlapGroups(bucket)
    profPositions.forEach((pos, id) => positions.set(id, pos))
  }
  return positions
})

function getOverlapStyle(appointment: Appointment): Record<string, string> {
  const pos = overlapPositions.value.get(appointment.id)
  if (!pos || pos.total <= 1) {
    return { left: '2px', right: '2px' }
  }
  const widthPercent = 100 / pos.total
  const leftPercent = pos.index * widthPercent
  return {
    left: `calc(${leftPercent}% + 1px)`,
    width: `calc(${widthPercent}% - 2px)`,
    right: 'auto'
  }
}

// Day's appointments keyed by the column index the template iterates. Splits
// the dragged appointment into its current column so the template still finds
// it; no per-column .filter() in the v-for.
const appointmentsByProfIndex = computed(() => {
  const map = new Map<number, Appointment[]>()
  const dragId = dragState.value?.appointmentId
  const dragType = dragState.value?.type
  const dragProfIdx = dragState.value?.currentColumnIndex
  for (let i = 0; i < props.professionals.length; i++) {
    const profId = props.professionals[i]!.id
    map.set(i, appointmentsByProfId.value.get(profId)?.slice() ?? [])
  }
  if (dragId && dragType === 'move' && typeof dragProfIdx === 'number') {
    const dragged = props.appointments.find(a => a.id === dragId)
    if (dragged) {
      const originalIdx = props.professionals.findIndex(p => p.id === (dragged.professional_id ?? ''))
      if (originalIdx !== dragProfIdx) {
        const fromBucket = map.get(originalIdx)
        if (fromBucket) {
          const idx = fromBucket.findIndex(a => a.id === dragId)
          if (idx >= 0) fromBucket.splice(idx, 1)
        }
        const toBucket = map.get(dragProfIdx)
        if (toBucket) toBucket.push(dragged)
      }
    }
  }
  return map
})
</script>

<template>
  <div class="flex flex-col h-full">
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

    <!-- No professionals message -->
    <div
      v-else-if="professionals.length === 0"
      class="flex items-center justify-center py-12 text-muted"
    >
      {{ t('appointments.noProfessionals') }}
    </div>

    <!-- Calendar grid -->
    <div
      v-else
      ref="calendarRef"
      class="flex-1 overflow-auto ring-1 ring-[var(--color-border)] rounded-token-lg"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
    >
      <!-- data-dense: see AppointmentCalendar — the grid is a time canvas
           and opts out of the global touch minimum sizes. -->
      <div
        data-dense
        class="min-w-[600px]"
        :style="{ minWidth: gridMinWidth }"
      >
        <!-- Professional headers -->
        <div
          class="grid border-b border-default bg-surface-muted sticky top-0 z-10"
          :style="{ gridTemplateColumns: `80px repeat(${professionals.length}, 1fr)` }"
        >
          <div class="p-2 text-center text-caption text-subtle border-r border-subtle" />
          <div
            v-for="prof in professionals"
            :key="prof.id"
            class="p-2 text-center border-r border-subtle last:border-r-0"
          >
            <div class="flex items-center justify-center gap-2">
              <span
                class="w-6 h-6 rounded-full flex items-center justify-center text-white text-[10px] font-semibold"
                :style="{ backgroundColor: prof.color }"
              >
                {{ prof.first_name.charAt(0) }}{{ prof.last_name.charAt(0) }}
              </span>
              <span class="text-ui text-default">
                {{ prof.first_name }} {{ prof.last_name }}
              </span>
            </div>
          </div>
        </div>

        <!-- Time rows -->
        <div class="relative">
          <div
            v-for="(slot, slotIndex) in timeSlots"
            :key="slot"
            class="grid border-b border-[var(--color-border-subtle)]"
            :class="{ 'border-[var(--color-border)]': slotIndex % SLOTS_PER_HOUR === 0 }"
            :style="{
              gridTemplateColumns: `80px repeat(${professionals.length}, 1fr)`,
              height: `${slotRows.heights.value[slotIndex]}px`
            }"
          >
            <div class="p-1 text-right border-r border-subtle flex items-center justify-end pr-2">
              <span
                v-if="slotIndex % SLOTS_PER_HOUR === 0"
                class="text-caption text-subtle tnum"
              >
                {{ slot }}
              </span>
            </div>
            <div
              v-for="(prof, profIdx) in professionals"
              :key="`${prof.id}-${slot}`"
              class="border-r border-[var(--color-border-subtle)] last:border-r-0 cursor-cell hover:bg-[var(--color-primary-soft)]/50 transition-colors relative"
              :class="{ 'border-[var(--color-border)]': slotIndex % SLOTS_PER_HOUR === 0 }"
              @pointerdown="onCellPointerDown(profIdx, slotIndex, $event)"
              @click="onCellClick(profIdx, slotIndex)"
            />
          </div>

          <!-- Appointments overlay -->
          <div class="absolute inset-0 pointer-events-none">
            <div
              class="grid h-full"
              :style="{ gridTemplateColumns: `80px repeat(${professionals.length}, 1fr)` }"
            >
              <div class="border-r border-subtle" />

              <!-- Professional columns -->
              <div
                v-for="(prof, profIndex) in professionals"
                :key="`appointments-${prof.id}`"
                class="relative border-r border-subtle last:border-r-0"
              >
                <!-- Blocked availability overlay (schedules module) -->
                <div
                  v-for="(seg, segIdx) in blockedSegments.filter(s => s.professionalId === prof.id)"
                  :key="`blocked-${prof.id}-${segIdx}`"
                  class="absolute inset-x-0 pointer-events-none z-10 schedules-blocked"
                  :title="seg.reason || (seg.state === 'clinic_closed' ? 'Clínica cerrada' : 'No disponible')"
                  :style="{
                    top: `${slotRows.top(seg.startSlot)}px`,
                    height: `${slotRows.span(seg.startSlot, seg.endSlot)}px`
                  }"
                />

                <!-- Ghost block during drag-to-create -->
                <div
                  v-if="createDragState && createDragState.columnIndex === profIndex"
                  class="absolute left-1 right-1 rounded border-2 border-dashed border-[var(--color-primary)] bg-[var(--color-primary-soft)] pointer-events-none z-40 flex items-start p-1"
                  :style="{
                    top: `${slotRows.top(createDragState.startSlot)}px`,
                    height: `${slotRows.span(createDragState.startSlot, createDragState.startSlot + Math.max(1, createDragState.currentSlot - createDragState.startSlot + 1))}px`,
                    minHeight: `${getSlotHeight()}px`
                  }"
                >
                  <span
                    v-if="createDragState.currentSlot > createDragState.startSlot"
                    class="text-xs text-primary-700 dark:text-primary-300 font-medium leading-none"
                  >
                    {{ slotIndexToTime(createDragState.startSlot) }} – {{ slotIndexToTime(createDragState.currentSlot + 1) }}
                  </span>
                </div>

                <div
                  v-for="appointment in (appointmentsByProfIndex.get(profIndex) ?? [])"
                  :key="appointment.id"
                  v-memo="[
                    appointment.id,
                    appointment.start_time,
                    appointment.end_time,
                    appointment.status,
                    dragState?.appointmentId === appointment.id,
                    highlightedAppointmentId === appointment.id,
                    prof.color
                  ]"
                  class="group absolute rounded overflow-hidden pointer-events-auto select-none shadow-sm border-l-4"
                  :class="[
                    getStatusClass(appointment.status),
                    dragState?.appointmentId === appointment.id ? 'cursor-grabbing ring-2 ring-primary-500' : 'cursor-grab hover:ring-2 hover:ring-primary-500',
                    selectedId === appointment.id ? 'ring-2 ring-primary-500 shadow-token-md z-40' : '',
                    highlightedAppointmentId === appointment.id ? 'ring-4 ring-warning-500 animate-pulse z-50' : ''
                  ]"
                  :style="{
                    ...getAppointmentStyle(appointment),
                    ...getOverlapStyle(appointment),
                    ...getProfessionalFill(prof.color),
                    ...getTouchActionStyle(appointment)
                  }"
                  @click="handleAppointmentClick(appointment, $event)"
                  @pointerdown="startAppointmentDrag('move', appointment, $event)"
                >
                  <!-- Content -->
                  <div class="px-1.5 h-full flex flex-col py-0.5 relative">
                    <!-- Quick-action dropdown (shown on hover) -->
                    <div
                      class="absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 transition-opacity z-20"
                      @click.stop
                      @pointerdown.stop
                    >
                      <AppointmentQuickActions
                        :appointment="appointment"
                        dense
                      />
                    </div>
                    <div class="flex items-center gap-1 min-h-[18px] pr-6">
                      <UIcon
                        v-if="getStatusIcon(appointment.status)"
                        :name="getStatusIcon(appointment.status)"
                        class="w-3 h-3 flex-shrink-0"
                      />
                      <span class="text-xs font-medium truncate">
                        {{ appointment.patient ? `${appointment.patient.first_name} ${appointment.patient.last_name}` : (appointment.title || t('appointments.noPatient')) }}
                      </span>
                      <UIcon
                        v-if="notesIndicator.has(appointment.id)"
                        name="i-lucide-sticky-note"
                        class="w-3 h-3 flex-shrink-0 text-primary"
                        :title="t('appointments.hasNotes', 'Tiene notas')"
                      />
                    </div>
                    <div
                      v-if="appointment.treatment_type"
                      class="text-xs opacity-60 truncate"
                    >
                      {{ appointment.treatment_type }}
                    </div>
                  </div>

                  <!-- Resize handle. See AppointmentCalendar: 8 px works
                       for a mouse, so a selected block grows it to 20 px
                       and paints it for the finger that picked it. -->
                  <div
                    class="absolute bottom-0 left-0 right-0 cursor-ns-resize transition-colors"
                    :class="selectedId === appointment.id
                      ? 'h-5 bg-primary-500/20'
                      : 'h-2 hover:bg-black/10 dark:hover:bg-white/10'"
                    @pointerdown.stop="startAppointmentDrag('resize', appointment, $event)"
                  >
                    <div
                      class="absolute bottom-0.5 left-1/2 -translate-x-1/2 rounded bg-current"
                      :class="selectedId === appointment.id
                        ? 'w-10 h-1 opacity-70'
                        : 'w-8 h-0.5 opacity-30'"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.schedules-blocked {
  background-image: repeating-linear-gradient(
    45deg,
    rgba(148, 163, 184, 0.18),
    rgba(148, 163, 184, 0.18) 6px,
    rgba(148, 163, 184, 0.32) 6px,
    rgba(148, 163, 184, 0.32) 12px
  );
}
</style>
