<script setup lang="ts">
import type { PaginatedResponse } from '~~/app/types'
import type { PipelineRow } from '../../composables/usePipeline'

/**
 * Home widget: plans waiting on the patient's answer (the pipeline's
 * "Esperando paciente" tab), oldest first as the server sorts them.
 */
defineProps<{ ctx?: unknown }>()

const { t } = useI18n()
const api = useApi()

const rows = ref<PipelineRow[]>([])
const total = ref(0)
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the list is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

function sample(): PipelineRow[] {
  const people: [string, string, number][] = [
    ['Laura', 'Demo', 12],
    ['Iván', 'Muestra', 6],
    ['Carmen', 'Modelo', 2]
  ]
  return people.map(([first_name, last_name, days], i) => ({
    plan_id: `preview-plan-${i + 1}`,
    plan_number: `PT-000${i + 1}`,
    plan_title: null,
    plan_status: 'pending',
    days_in_status: days,
    closure_reason: null,
    items_total: 3,
    items_completed: 0,
    patient: { id: `preview-patient-${i + 1}`, first_name, last_name, phone: null },
    budget: null,
    next_appointment: null
  }))
}

async function load() {
  if (preview) {
    rows.value = sample()
    total.value = rows.value.length
    pending.value = false
    return
  }
  try {
    const res = await api.get<PaginatedResponse<PipelineRow>>(
      '/api/v1/treatment_plan/treatment-plans/pipeline?tab=esperando_paciente&page_size=5'
    )
    rows.value = res.data
    total.value = res.total
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    pending.value = false
  }
}

onMounted(load)
onActivated(load)
</script>

<template>
  <SectionCard
    icon="i-lucide-clipboard-list"
    icon-role="warning"
    :title="t('dashboard.awaitingPlans.title')"
  >
    <template #actions>
      <UButton
        to="/treatments/plans?tab=esperando_paciente"
        variant="ghost"
        color="neutral"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        :aria-label="t('dashboard.awaitingPlans.all', { n: total })"
      />
    </template>

    <div
      v-if="pending"
      class="space-y-2"
    >
      <USkeleton
        v-for="i in 3"
        :key="i"
        class="h-10 w-full"
      />
    </div>

    <EmptyState
      v-else-if="rows.length === 0"
      icon="i-lucide-clipboard-check"
      :title="t('dashboard.awaitingPlans.empty')"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="row in rows"
        :key="row.plan_id"
      >
        <ListRow :to="`/treatments/plans/${row.plan_id}`">
          <template #title>
            {{ row.patient.first_name }} {{ row.patient.last_name }}
          </template>
          <template #subtitle>
            {{ row.plan_title || row.plan_number }}
          </template>
          <template #meta>
            <span class="text-caption text-subtle tnum">
              {{ t('dashboard.awaitingPlans.days', { n: row.days_in_status }, row.days_in_status) }}
            </span>
          </template>
        </ListRow>
      </li>
    </ul>
  </SectionCard>
</template>
