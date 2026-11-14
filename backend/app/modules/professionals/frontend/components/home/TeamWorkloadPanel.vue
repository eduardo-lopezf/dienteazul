<script setup lang="ts">
import type { PaginatedResponse } from '~~/app/types'
import type { ProfessionalWorkload } from '../../composables/useProfessionalWorkload'

/**
 * Home widget: what each active professional has on their plate —
 * upcoming appointments and plans in progress. Only for a clinic
 * (registered with `tiers: ['clinic']`): an individual practice has one
 * professional and nothing to compare.
 */
defineProps<{ ctx?: unknown }>()

interface Row {
  id: string
  full_name: string
  upcoming?: number
  plans?: number
}

const { t } = useI18n()
const api = useApi()

const rows = ref<Row[]>([])
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the list is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

function sample(): Row[] {
  return [
    { id: 'preview-pro-1', full_name: 'Dra. Ana Ejemplo', upcoming: 14, plans: 6 },
    { id: 'preview-pro-2', full_name: 'Dr. Luis Prueba', upcoming: 9, plans: 3 },
    { id: 'preview-pro-3', full_name: 'Marta Modelo', upcoming: 5 }
  ]
}

async function load() {
  if (preview) {
    rows.value = sample()
    pending.value = false
    return
  }
  try {
    const [people, workload] = await Promise.all([
      api.get<PaginatedResponse<{ id: string, full_name: string, is_active: boolean }>>(
        '/api/v1/professionals?page_size=100'
      ),
      api.get<{ data: ProfessionalWorkload[] }>('/api/v1/professionals/workload')
        .catch(() => ({ data: [] as ProfessionalWorkload[] }))
    ])
    const byId = Object.fromEntries(workload.data.map(w => [w.professional_id, w]))
    rows.value = people.data
      .filter(p => p.is_active)
      .map(p => ({
        id: p.id,
        full_name: p.full_name,
        // A figure whose App is off stays absent, never a zero.
        upcoming: byId[p.id]?.counts.appointments_upcoming,
        plans: byId[p.id]?.counts.plans_in_progress
      }))
      .sort((a, b) => (b.upcoming ?? 0) - (a.upcoming ?? 0))
      .slice(0, 6)
  } catch {
    rows.value = []
  } finally {
    pending.value = false
  }
}

onMounted(load)
onActivated(load)
</script>

<template>
  <SectionCard
    icon="i-lucide-users-round"
    icon-role="info"
    :title="t('dashboard.teamWorkload.title')"
  >
    <template #actions>
      <UButton
        to="/professionals"
        variant="ghost"
        color="neutral"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        :aria-label="t('dashboard.teamWorkload.all')"
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
      icon="i-lucide-users-round"
      :title="t('dashboard.teamWorkload.empty')"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="row in rows"
        :key="row.id"
      >
        <ListRow to="/professionals">
          <template #title>
            {{ row.full_name }}
          </template>
          <template #subtitle>
            <span v-if="row.plans !== undefined">
              {{ t('dashboard.teamWorkload.plans', { n: row.plans }, row.plans) }}
            </span>
          </template>
          <template #meta>
            <span
              v-if="row.upcoming !== undefined"
              class="text-caption text-subtle tnum"
            >
              {{ t('dashboard.teamWorkload.upcoming', { n: row.upcoming }, row.upcoming) }}
            </span>
          </template>
        </ListRow>
      </li>
    </ul>
  </SectionCard>
</template>
