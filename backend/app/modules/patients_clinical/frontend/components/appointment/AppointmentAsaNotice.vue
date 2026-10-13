<script setup lang="ts">
/**
 * AppointmentAsaNotice — said while an appointment is being booked: this
 * patient's current ASA class is III or IV.
 *
 * A notice, not a gate: whether and how to see the patient is the
 * clinician's call. Whoever books sees the class and what to do about it
 * in the scheduling — nothing else. What the class means, when it was
 * assessed, by whom and on what grounds is the medical history's, shown
 * only to those who may read it. Registered into
 * ``appointment.patient.alerts`` by patients_clinical; the agenda never
 * imports this file (ADR 0041).
 */
import { PERMISSIONS } from '~/config/permissions'

interface Shown {
  asa_class: number
  label: string
  /** Null for whoever sees the class alone. */
  assessed_at: string | null
  assessed_by_name: string | null
  rationale: string | null
}

const props = defineProps<{ ctx: { patientId: string } }>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const asa = useAsaAssessments()

const current = ref<Shown | null>(null)
/** Whether the reader may see the history behind the class. */
const detailed = computed(() => can(PERMISSIONS.medicalHistory.read))

async function load() {
  current.value = null
  try {
    if (detailed.value) {
      const full = (await asa.status(props.ctx.patientId)).current
      current.value = full
    } else {
      const brief = await asa.currentClass(props.ctx.patientId)
      current.value = brief.asa_class && brief.label
        ? {
            asa_class: brief.asa_class,
            label: brief.label,
            assessed_at: null,
            assessed_by_name: null,
            rationale: null
          }
        : null
    }
  } catch {
    // Booking goes on without the notice rather than failing on it.
    current.value = null
  }
}

onMounted(load)
watch(() => props.ctx.patientId, load)

const shown = computed(() => (current.value && current.value.asa_class >= 3 ? current.value : null))

const assessed = computed(() => shown.value?.assessed_at
  ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(shown.value.assessed_at))
  : ''
)
</script>

<template>
  <UAlert
    v-if="shown"
    :color="shown.asa_class >= 4 ? 'error' : 'warning'"
    variant="subtle"
    icon="i-lucide-shield-plus"
    :title="detailed
      ? t('asa.booking.title', { label: shown.label, description: t(`asa.classes.${shown.asa_class}`) })
      : t('asa.booking.titleBrief', { label: shown.label })"
    data-testid="appointment-asa-notice"
  >
    <template #description>
      <p>{{ t(`asa.booking.advice.${shown.asa_class}`) }}</p>
      <p
        v-if="detailed"
        class="text-caption mt-1"
      >
        {{ t('asa.booking.assessed', { when: assessed }) }}<template v-if="shown.assessed_by_name">
          · {{ shown.assessed_by_name }}
        </template><template v-if="shown.rationale">
          · {{ shown.rationale }}
        </template>
      </p>
    </template>
  </UAlert>
</template>
