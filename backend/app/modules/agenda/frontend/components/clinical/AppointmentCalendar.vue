<script setup lang="ts">
import type { Appointment, Professional } from '~~/app/types'
import type { BlockedSegment } from '../../composables/useBlockedSegments'
import { formatLocalDate } from '../../utils/date'

const notesIndicator = useAppointmentNotesIndicator()

interface Cabinet {
  name: string
  color: string
}

interface ProfessionalWithColor extends Professional {
  color: string
}

const props = defineProps<{
  appointments: Appointment[]
  cabinets?: Cabinet[]
  professionals?: ProfessionalWithColor[]
  currentWeekStart: Date
  isLoading?: boolean
  highlightedAppointmentId?: string | null
}>()

const emit = defineEmits<{
  'slot-click': [date: Date, time: string]
  'slot-drag-create': [date: Date, startTime: string, endTime: string]
  'appointment-click': [appointment: Appointment]
  'appointment-move': [appointmentId: string, newDate: string, newStartTime: string, newEndTime: string]
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

const { t, locale } = useI18n()

// Time slots configuration. START_HOUR/END_HOUR default to 8–21 and
// get narrowed to the actual clinic opening hours when the schedules
// module is installed (the composable is 404-tolerant — if schedules
// is uninstalled it silently falls back to 8–21).
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

async function refreshBounds() {
  const weekEnd = new Date(props.currentWeekStart)
  weekEnd.setDate(weekEnd.getDate() + 6)
  const bounds = await computeCalendarBounds({
    start: props.currentWeekStart,
    end: weekEnd
  })
  startHour.value = bounds.startHour
  endHour.value = bounds.endHour

  // Clinic-level blocked overlay (no professional filter — week view shows
  // all appointments globally). Recomputed after bounds because slot indexes
  // depend on startHour/endHour.
  blockedSegments.value = await computeBlockedSegments({
    start: props.currentWeekStart,
    end: weekEnd
  })
}

watch(() => props.currentWeekStart, () => {
  void refreshBounds()
}, { immediate: true })

// `effective`, not `density`: the preference can still say "compact"
// while a coarse pointer forces the touch scale, and the CSS variable
// follows `effective`. Reading the preference here would put the drag
// maths 10 px per slot out of step with what is drawn.
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
    allAppointmentsWithDayIndex.value.map(({ appointment }) => ({
      start: slotOfTime(appointment.start_time),
      end: slotOfTime(appointment.end_time)
    }))
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
  columnCount: () => weekDays.value.length,
  gutterColumns: 1,
  containerRef: calendarRef,

  onCreateRange: (dayIndex, startSlot, endSlot) => {
    const day = weekDays.value[dayIndex]
    if (day) emit('slot-drag-create', day, slotIndexToTime(startSlot), slotIndexToTime(endSlot))
  },

  onCreatePoint: (dayIndex, slot) => {
    const day = weekDays.value[dayIndex]
    if (day) emit('slot-click', day, slotIndexToTime(slot))
  },

  onMove: (appointmentId, dayIndex, startSlot, endSlot) => {
    const appointment = props.appointments.find(a => a.id === appointmentId)
    const day = weekDays.value[dayIndex]
    if (!appointment || !day) return

    const newDate = formatLocalDate(day)
    const newStartTime = slotIndexToTime(startSlot)
    const oldDate = appointment.start_time.split('T')[0]
    const oldStartTime = appointment.start_time.split('T')[1]?.substring(0, 5) ?? ''

    if (newDate === oldDate && newStartTime === oldStartTime) return
    emit('appointment-move', appointmentId, newDate, newStartTime, slotIndexToTime(endSlot))
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

// A selection is about one specific block; carrying it across a week
// change would leave an off-screen block holding `touch-action: none`.
watch(() => props.currentWeekStart, () => clearSelection())

/** Slot bounds of an appointment, for handing to the drag composable. */
function appointmentSlots(appointment: Appointment): { start: number, end: number } {
  const startTime = appointment.start_time.split('T')[1]?.substring(0, 5) ?? '08:00'
  const endTime = appointment.end_time.split('T')[1]?.substring(0, 5) ?? '08:15'
  return { start: getSlotIndex(startTime), end: getSlotIndex(endTime) }
}

function startAppointmentDrag(
  type: 'move' | 'resize',
  appointment: Appointment,
  event: PointerEvent
) {
  const { start, end } = appointmentSlots(appointment)
  const aptDate = appointment.start_time.split('T')[0]
  const dayIndex = weekDays.value.findIndex(d => formatLocalDate(d) === aptDate)
  onAppointmentPointerDown(
    { type, appointmentId: appointment.id, columnIndex: dayIndex, startSlot: start, endSlot: end },
    event
  )
}

/**
 * Tap-to-create. A finger gets no drag on empty space (see
 * useSlotGridDrag), so the click is what opens the modal; a mouse
 * already emitted from the drag's own release and must not fire twice.
 */
function onCellClick(dayIndex: number, slotIndex: number) {
  if (!isTouch.value) return
  const day = weekDays.value[dayIndex]
  if (day) emit('slot-click', day, slotIndexToTime(slotIndex))
}

/**
 * `touch-action: none` is what stops the browser scrolling instead of
 * dragging — but only on the selected block, so the grid stays
 * scrollable everywhere the user has not pointed at yet.
 */
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

// Generate days of the week
const weekDays = computed(() => {
  const days: Date[] = []
  for (let i = 0; i < 7; i++) {
    const day = new Date(props.currentWeekStart)
    day.setDate(day.getDate() + i)
    days.push(day)
  }
  return days
})

// Format day header
function formatDayHeader(date: Date): string {
  const dayName = date.toLocaleDateString(locale.value, { weekday: 'short' })
  const dayNum = date.getDate()
  return `${dayName} ${dayNum}`
}

// Check if date is today
function isToday(date: Date): boolean {
  const today = new Date()
  return date.toDateString() === today.toDateString()
}

// Calculate appointment position and height
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

function getAppointmentStyle(appointment: Appointment): Record<string, string> {
  // Check if this appointment is being dragged
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

// Get the day index for drag preview
function getAppointmentDayIndex(appointment: Appointment): number {
  if (dragState.value?.appointmentId === appointment.id && dragState.value.type === 'move') {
    return dragState.value.currentColumnIndex
  }
  const aptDate = appointment.start_time.split('T')[0]
  return weekDays.value.findIndex(d => formatLocalDate(d) === aptDate)
}

// Get cabinet color
function getCabinetColor(cabinetName: string): string {
  const cabinet = props.cabinets?.find(c => c.name === cabinetName)
  return cabinet?.color || '#6B7280' // Default gray
}

// Get professional by ID
function getProfessional(professionalId: string | null): ProfessionalWithColor | undefined {
  return props.professionals?.find(p => p.id === professionalId)
}

// Get professional initials
function getProfessionalInitials(professionalId: string | null): string {
  const prof = getProfessional(professionalId)
  if (!prof) return '?'
  const first = prof.first_name.charAt(0).toUpperCase()
  const last = prof.last_name.charAt(0).toUpperCase()
  return `${first}${last}`
}

// Get professional color
function getProfessionalColor(professionalId: string | null): string {
  const prof = getProfessional(professionalId)
  return prof?.color || '#6B7280'
}

// Get professional full name
function getProfessionalFullName(professionalId: string | null): string {
  const prof = getProfessional(professionalId)
  if (!prof) return 'Desconocido'
  return `${prof.first_name} ${prof.last_name}`
}

// Get appointment style with cabinet color
// Per DESIGN §7.3: fill at alpha 0.12 in cabinet colour, 3 px left border in full colour.
function getAppointmentColorStyle(appointment: Appointment): Record<string, string> {
  const color = getCabinetColor(appointment.cabinet)
  // Convert hex to rgba with alpha for fill tint
  const r = parseInt(color.slice(1, 3), 16)
  const g = parseInt(color.slice(3, 5), 16)
  const b = parseInt(color.slice(5, 7), 16)
  return {
    '--cabinet-color': color,
    'backgroundColor': `rgba(${r}, ${g}, ${b}, 0.12)`,
    'borderLeftColor': color,
    'borderLeftWidth': '3px'
  }
}

// Get status-based styling
// Calendar block: fill = professional colour alpha 0.12 (inline), left border 3 px in full
// professional colour (inline). Status modulates text colour and opacity only.
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
    case 'confirmed':
      return 'i-lucide-check'
    case 'checked_in':
      return 'i-lucide-door-open'
    case 'in_treatment':
      return 'i-lucide-stethoscope'
    case 'completed':
      return 'i-lucide-check-check'
    case 'cancelled':
      return 'i-lucide-x'
    case 'no_show':
      return 'i-lucide-user-x'
    default:
      return ''
  }
}

// Tap or click an appointment. Suppressed right after a drag so
// releasing a moved appointment does not also open it.
function handleAppointmentClick(appointment: Appointment, event: Event) {
  if (dragState.value || wasDragging.value) return
  event.stopPropagation()
  emit('appointment-click', appointment)
}

// Check if two appointments overlap in time
function appointmentsOverlap(apt1: Appointment, apt2: Appointment): boolean {
  const start1 = new Date(apt1.start_time).getTime()
  const end1 = new Date(apt1.end_time).getTime()
  const start2 = new Date(apt2.start_time).getTime()
  const end2 = new Date(apt2.end_time).getTime()

  return start1 < end2 && end1 > start2
}

// Group overlapping appointments and calculate their positions
function calculateOverlapGroups(dayAppointments: Appointment[]): Map<string, { index: number, total: number }> {
  const result = new Map<string, { index: number, total: number }>()

  if (dayAppointments.length === 0) return result

  // Sort by start time
  const sorted = [...dayAppointments].sort((a, b) =>
    new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
  )

  // Find all overlapping groups
  const groups: Appointment[][] = []

  for (const apt of sorted) {
    // Find a group this appointment overlaps with
    let addedToGroup = false

    for (const group of groups) {
      // Check if this appointment overlaps with any in the group
      const overlapsWithGroup = group.some(existing => appointmentsOverlap(apt, existing))

      if (overlapsWithGroup) {
        group.push(apt)
        addedToGroup = true
        break
      }
    }

    if (!addedToGroup) {
      groups.push([apt])
    }
  }

  // Merge groups that have overlapping appointments
  let merged = true
  while (merged) {
    merged = false
    for (let i = 0; i < groups.length; i++) {
      for (let j = i + 1; j < groups.length; j++) {
        // Check if any appointment in group i overlaps with any in group j
        const shouldMerge = groups[i]!.some(apt1 =>
          groups[j]!.some(apt2 => appointmentsOverlap(apt1, apt2))
        )

        if (shouldMerge) {
          groups[i]!.push(...groups[j]!)
          groups.splice(j, 1)
          merged = true
          break
        }
      }
      if (merged) break
    }
  }

  // Assign positions within each group
  for (const group of groups) {
    const total = group.length
    // Sort by start time within group for consistent positioning
    group.sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())

    group.forEach((apt, index) => {
      result.set(apt.id, { index, total })
    })
  }

  return result
}

// Computed overlap positions for all days
const overlapPositions = computed(() => {
  const positions = new Map<string, { index: number, total: number }>()

  for (let dayIndex = 0; dayIndex < 7; dayIndex++) {
    const day = weekDays.value[dayIndex]
    if (!day) continue

    const dateStr = formatLocalDate(day)
    const dayAppointments = props.appointments.filter((apt) => {
      if (apt.status === 'cancelled') return false
      const aptDate = apt.start_time.split('T')[0]
      return aptDate === dateStr
    })

    const dayPositions = calculateOverlapGroups(dayAppointments)
    dayPositions.forEach((pos, id) => positions.set(id, pos))
  }

  return positions
})

// Get overlap style for an appointment
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

// All appointments flat for drag preview rendering
const allAppointmentsWithDayIndex = computed(() => {
  return props.appointments
    .filter(apt => apt.status !== 'cancelled')
    .map(apt => ({
      appointment: apt,
      dayIndex: getAppointmentDayIndex(apt)
    }))
    .filter(item => item.dayIndex >= 0 && item.dayIndex < 7)
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Loading overlay -->
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

    <!-- Calendar grid -->
    <div
      v-else
      ref="calendarRef"
      class="flex-1 overflow-auto ring-1 ring-[var(--color-border)] rounded-token-lg"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
    >
      <!-- data-dense: the grid is a time canvas, not a toolbar. It opts
           out of the global touch minimum sizes so a 15-minute slot
           stays 15 minutes tall. See main.css "Touch adaptation". -->
      <div
        data-dense
        class="min-w-[800px]"
      >
        <!-- Day headers -->
        <div class="grid grid-cols-8 border-b border-default bg-surface-muted sticky top-0 z-10">
          <div class="p-2 text-center text-caption text-subtle border-r border-subtle">
            <!-- Empty -->
          </div>
          <div
            v-for="day in weekDays"
            :key="day.toISOString()"
            class="p-2 text-center border-r border-subtle last:border-r-0"
            :class="{ 'bg-[var(--color-primary-soft)]': isToday(day) }"
          >
            <span
              class="text-ui"
              :class="isToday(day) ? 'text-[var(--color-primary-soft-text)]' : 'text-default'"
            >
              {{ formatDayHeader(day) }}
            </span>
          </div>
        </div>

        <!-- Time rows -->
        <div class="relative">
          <div
            v-for="(slot, slotIndex) in timeSlots"
            :key="slot"
            class="grid grid-cols-8 border-b border-[var(--color-border-subtle)]"
            :class="{ 'border-[var(--color-border)]': slotIndex % SLOTS_PER_HOUR === 0 }"
            :style="{ height: `${slotRows.heights.value[slotIndex]}px` }"
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
              v-for="(day, dayIdx) in weekDays"
              :key="`${day.toISOString()}-${slot}`"
              class="border-r border-[var(--color-border-subtle)] last:border-r-0 cursor-cell bg-[var(--color-surface)] hover:bg-[var(--color-primary-soft)]/50 transition-colors relative"
              :class="{
                'border-[var(--color-border)]': slotIndex % SLOTS_PER_HOUR === 0
              }"
              @pointerdown="onCellPointerDown(dayIdx, slotIndex, $event)"
              @click="onCellClick(dayIdx, slotIndex)"
            />
          </div>

          <!-- Appointments overlay -->
          <div class="absolute inset-0 pointer-events-none">
            <div class="grid grid-cols-8 h-full">
              <!-- Time column spacer -->
              <div class="border-r border-default" />

              <!-- Day columns with appointments -->
              <div
                v-for="(day, dayIndex) in weekDays"
                :key="`appointments-${day.toISOString()}`"
                class="relative border-r border-subtle last:border-r-0"
              >
                <!-- Blocked availability overlay (schedules module).
                     Per-day clinic_closed ranges — paints late-start
                     mornings, early-close evenings, midday gaps, and
                     fully-closed days. -->
                <div
                  v-for="(seg, segIdx) in blockedSegments.filter(s => s.dateKey === formatLocalDate(day))"
                  :key="`blocked-${day.toISOString()}-${segIdx}`"
                  class="absolute inset-x-0 pointer-events-none z-10 schedules-blocked"
                  :title="seg.reason || 'Clínica cerrada'"
                  :style="{
                    top: `${slotRows.top(seg.startSlot)}px`,
                    height: `${slotRows.span(seg.startSlot, seg.endSlot)}px`
                  }"
                />

                <!-- Ghost block during drag-to-create -->
                <div
                  v-if="createDragState && createDragState.columnIndex === dayIndex"
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
                  v-for="{ appointment } in allAppointmentsWithDayIndex.filter(a => a.dayIndex === dayIndex)"
                  :key="appointment.id"
                  class="group absolute rounded overflow-hidden pointer-events-auto select-none shadow-sm"
                  :class="[
                    getStatusClass(appointment.status),
                    dragState?.appointmentId === appointment.id ? 'cursor-grabbing ring-2 ring-primary-500' : 'cursor-grab hover:ring-2 hover:ring-primary-500',
                    selectedId === appointment.id ? 'ring-2 ring-primary-500 shadow-token-md z-40' : '',
                    highlightedAppointmentId === appointment.id ? 'ring-4 ring-warning-500 animate-pulse z-50' : ''
                  ]"
                  :style="{
                    ...getAppointmentStyle(appointment),
                    ...getAppointmentColorStyle(appointment),
                    ...getOverlapStyle(appointment),
                    ...getTouchActionStyle(appointment)
                  }"
                  @click="handleAppointmentClick(appointment, $event)"
                  @pointerdown="startAppointmentDrag('move', appointment, $event)"
                >
                  <!-- Content -->
                  <div class="px-1.5 h-full flex flex-col py-0.5 relative">
                    <!-- Professional badge -->
                    <div
                      v-if="professionals && professionals.length > 0"
                      class="absolute top-0.5 right-0.5 w-5 h-5 rounded-full flex items-center justify-center text-white text-[10px] font-bold shadow-sm"
                      :style="{ backgroundColor: getProfessionalColor(appointment.professional_id) }"
                      :title="getProfessionalFullName(appointment.professional_id)"
                    >
                      {{ getProfessionalInitials(appointment.professional_id) }}
                    </div>
                    <!-- Quick-action dropdown (shown on hover) -->
                    <div
                      class="absolute top-0.5 left-0.5 opacity-0 group-hover:opacity-100 transition-opacity z-20"
                      @click.stop
                      @pointerdown.stop
                    >
                      <AppointmentQuickActions
                        :appointment="appointment"
                        dense
                      />
                    </div>
                    <div class="flex items-center gap-1 min-h-[18px] pr-5 pl-5">
                      <UIcon
                        v-if="getStatusIcon(appointment.status)"
                        :name="getStatusIcon(appointment.status)"
                        class="w-3 h-3 flex-shrink-0"
                      />
                      <span class="text-xs font-medium truncate">
                        {{ appointment.patient ? `${appointment.patient.last_name}` : (appointment.title || t('appointments.noPatient')) }}
                      </span>
                      <UIcon
                        v-if="notesIndicator.has(appointment.id)"
                        name="i-lucide-sticky-note"
                        class="w-3 h-3 flex-shrink-0 text-primary"
                        :title="$t('appointments.hasNotes', 'Tiene notas')"
                      />
                    </div>
                    <div
                      v-if="appointment.treatment_type || appointment.cabinet"
                      class="text-xs opacity-60 truncate"
                    >
                      {{ appointment.cabinet }}{{ appointment.treatment_type ? ` · ${appointment.treatment_type}` : '' }}
                    </div>
                  </div>

                  <!-- Resize handle. 8 px is fine for a mouse and hopeless
                       for a finger, so a selected block grows it to 20 px
                       and paints it — by then the block has been
                       deliberately picked, and the grab bar is the only
                       affordance that needs to be reachable.
                       Capped at 40 % of the block: 20 px of a 36 px block is
                       nearly all of it, centre included, and a selected
                       quarter-hour could then only be resized, never moved. -->
                  <div
                    class="absolute bottom-0 left-0 right-0 cursor-ns-resize transition-colors"
                    :class="selectedId === appointment.id
                      ? 'h-5 max-h-[40%] bg-primary-500/20'
                      : 'h-2 max-h-[40%] hover:bg-black/10 dark:hover:bg-white/10'"
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
