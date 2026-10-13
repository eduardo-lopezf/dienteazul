<script setup lang="ts">
import type { Appointment } from '~~/app/types'
import { formatDurationShort, formatWallClockTime, wallClockDate } from '../../utils/date'

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
  appointment: Appointment
  cabinets?: Cabinet[]
  professionals?: ProfessionalWithColor[]
  /** Layout variant. Defaults to 'kanban' (full). */
  variant?: 'kanban' | 'compact'
  /** When true, hide the quick-action dropdown. */
  hideQuickActions?: boolean
}>()

const emit = defineEmits<{
  click: [appointment: Appointment]
  transitioned: [appointment: Appointment, to: Appointment['status']]
}>()

const { t, locale } = useI18n()
const { statusColour, statusLabel, isTerminal } = useAppointmentStatus()
const notesIndicator = useAppointmentNotesIndicator()
const hasNotes = computed(() => notesIndicator.has(props.appointment.id))

// Manual 30-second tick (@vueuse/core is not a dependency of this repo).
const now = ref(new Date())
let tickHandle: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  tickHandle = setInterval(() => {
    now.value = new Date()
  }, 30_000)
})
onBeforeUnmount(() => {
  if (tickHandle !== null) clearInterval(tickHandle)
})

const variant = computed(() => props.variant ?? 'kanban')

const cabinet = computed(() => {
  return props.cabinets?.find(c => c.name === props.appointment.cabinet)
})

const professional = computed(() => {
  return props.professionals?.find(p => p.id === props.appointment.professional_id)
})

const professionalInitials = computed(() => {
  const p = professional.value
  if (!p) return '?'
  return `${p.first_name.charAt(0)}${p.last_name.charAt(0)}`.toUpperCase()
})

const patientName = computed(() => {
  const p = props.appointment.patient
  if (!p) return props.appointment.title || '—'
  return `${p.first_name} ${p.last_name}`.trim()
})

const startLabel = computed(() =>
  formatWallClockTime(props.appointment.start_time, locale.value)
)

const endLabel = computed(() =>
  formatWallClockTime(props.appointment.end_time, locale.value)
)

const plannedMinutes = computed(() => {
  const start = wallClockDate(props.appointment.start_time).getTime()
  const end = wallClockDate(props.appointment.end_time).getTime()
  return Math.max(1, Math.round((end - start) / 60_000))
})

const timerLabel = computed(() => {
  const apt = props.appointment
  const nowMs = now.value.getTime()
  // ``current_status_since`` is a real server instant, so it subtracts
  // straight from ``now``. ``start_time`` is a clinic wall clock: comparing
  // it as an instant made every card read "retrasada" by the browser↔UTC
  // gap (8 h on a UTC−6 desk for an appointment that had not started yet).
  const sinceMs = new Date(apt.current_status_since).getTime()
  const startMs = wallClockDate(apt.start_time).getTime()

  if (apt.status === 'scheduled' || apt.status === 'confirmed') {
    const diffMin = Math.round((startMs - nowMs) / 60_000)
    const duration = formatDurationShort(Math.abs(diffMin), t)
    if (diffMin >= 0) return t('appointments.timer.startsIn', { duration })
    return t('appointments.timer.startsInOverdue', { duration })
  }
  if (apt.status === 'checked_in') {
    const waiting = Math.max(0, Math.round((nowMs - sinceMs) / 60_000))
    return t('appointments.timer.waiting', { duration: formatDurationShort(waiting, t) })
  }
  if (apt.status === 'in_treatment') {
    const elapsed = Math.max(0, Math.round((nowMs - sinceMs) / 60_000))
    return t('appointments.timer.inTreatment', {
      elapsed,
      planned: plannedMinutes.value
    })
  }
  if (apt.status === 'completed') {
    const d = new Date(apt.current_status_since)
    return t('appointments.timer.completedAt', {
      time: d.toLocaleTimeString(locale.value, { hour: '2-digit', minute: '2-digit' })
    })
  }
  if (apt.status === 'cancelled') return t('appointments.timer.cancelledAt')
  if (apt.status === 'no_show') return t('appointments.timer.noShowAt')
  return ''
})

const timerTone = computed<'default' | 'warning' | 'danger'>(() => {
  const apt = props.appointment
  const nowMs = now.value.getTime()
  const sinceMs = new Date(apt.current_status_since).getTime()
  if (apt.status === 'checked_in') {
    const waiting = Math.round((nowMs - sinceMs) / 60_000)
    if (waiting >= 15) return 'danger'
    if (waiting >= 8) return 'warning'
  }
  if (apt.status === 'in_treatment') {
    const elapsed = Math.round((nowMs - sinceMs) / 60_000)
    if (elapsed > plannedMinutes.value) return 'danger'
  }
  return 'default'
})

const timerClass = computed(() => {
  if (timerTone.value === 'danger') return 'text-red-600 dark:text-red-400 font-semibold'
  if (timerTone.value === 'warning') return 'text-amber-600 dark:text-amber-400'
  return 'text-muted'
})

const cardStyle = computed(() => ({
  borderLeftColor: statusColour(props.appointment.status),
  borderLeftWidth: '4px',
  borderLeftStyle: 'solid' as const
}))
</script>

<template>
  <div
    class="group relative bg-surface ring-1 ring-[var(--color-border)] rounded-md shadow-xs hover:shadow-sm transition-all cursor-pointer"
    :class="[
      variant === 'compact' ? 'p-1.5 text-xs' : 'p-3 text-sm',
      isTerminal(appointment.status) && appointment.status !== 'completed' ? 'opacity-70' : '',
      appointment.status === 'cancelled' ? 'line-through' : ''
    ]"
    :style="cardStyle"
    :data-appointment-id="appointment.id"
    @click="emit('click', appointment)"
  >
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0 flex-1">
        <div class="flex items-center gap-1 min-w-0">
          <span class="font-medium truncate">{{ patientName }}</span>
          <UIcon
            v-if="hasNotes"
            name="i-lucide-sticky-note"
            class="w-3.5 h-3.5 text-primary shrink-0"
            :aria-label="t('appointments.hasNotes', 'Tiene notas')"
            :title="t('appointments.hasNotes', 'Tiene notas')"
          />
        </div>
        <div class="flex items-center gap-1 text-muted text-xs mt-0.5">
          <span>{{ startLabel }}–{{ endLabel }}</span>
          <span
            v-if="appointment.treatment_type"
            class="truncate"
          >· {{ appointment.treatment_type }}</span>
        </div>
      </div>
      <div class="flex items-center gap-1 shrink-0">
        <UAvatar
          v-if="professional"
          :alt="`${professional.first_name} ${professional.last_name}`"
          :text="professionalInitials"
          :style="{ backgroundColor: professional.color, color: '#fff' }"
          size="xs"
        />
        <!-- The host may pick the card up on pointerdown (the kanban
             captures the pointer to drag): the menu's press is not that. -->
        <span
          v-if="!hideQuickActions"
          class="contents"
          @pointerdown.stop
        >
          <AppointmentQuickActions
            :appointment="appointment"
            @transitioned="(apt, to) => emit('transitioned', apt, to)"
          />
        </span>
      </div>
    </div>
    <div class="flex items-center justify-between gap-2 mt-1">
      <UBadge
        v-if="cabinet"
        :label="cabinet.name"
        :style="{ backgroundColor: cabinet.color, color: '#fff' }"
        size="xs"
      />
      <UBadge
        v-else
        :label="t('appointments.cabinetAssignment.unassigned')"
        color="warning"
        variant="subtle"
        size="xs"
      />
      <span
        class="text-xs"
        :class="timerClass"
      >{{ timerLabel }}</span>
    </div>
    <div class="sr-only">
      {{ statusLabel(appointment.status) }}
    </div>
  </div>
</template>
