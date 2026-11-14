<script setup lang="ts">
import type { PaginatedResponse } from '~~/app/types'
import { formatDateOnly } from '~~/app/utils/date'

/**
 * Home widget: budgets still awaiting acceptance whose validity ends in
 * the next week — the ones worth a call before they lapse.
 */
defineProps<{ ctx?: unknown }>()

interface Row {
  id: string
  budget_number: string
  valid_until: string | null
  total: string
  patient: { first_name: string, last_name: string } | null
}

const WINDOW_DAYS = 7

const { t, locale } = useI18n()
const api = useApi()
const { format: money } = useCurrency()

const rows = ref<Row[]>([])
const total = ref(0)
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the list is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

/** The local calendar day `days` from now — not UTC, which is tomorrow by evening. */
function isoInDays(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toLocaleDateString('en-CA')
}

function sample(): Row[] {
  const people: [string, string, number, string][] = [
    ['Sofía', 'Ejemplo', 1, '12400.00'],
    ['Marcos', 'Prueba', 3, '3850.00'],
    ['Laura', 'Demo', 6, '780.00']
  ]
  return people.map(([first_name, last_name, days, amount], i) => ({
    id: `preview-budget-${i + 1}`,
    budget_number: `P-2026-00${i + 1}`,
    valid_until: isoInDays(days),
    total: amount,
    patient: { first_name, last_name }
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
    const params = new URLSearchParams({
      status: 'draft',
      valid_until_after: isoInDays(0),
      valid_until_before: isoInDays(WINDOW_DAYS),
      sort: 'valid_until:asc',
      page_size: '5'
    })
    const res = await api.get<PaginatedResponse<Row>>(`/api/v1/budget/budgets?${params}`)
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
    icon="i-lucide-file-clock"
    icon-role="warning"
    :title="t('dashboard.expiringBudgets.title')"
  >
    <template #actions>
      <UButton
        to="/budgets"
        variant="ghost"
        color="neutral"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        :aria-label="t('dashboard.expiringBudgets.all')"
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
      icon="i-lucide-file-check"
      :title="t('dashboard.expiringBudgets.empty', { n: WINDOW_DAYS })"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="row in rows"
        :key="row.id"
      >
        <ListRow :to="`/budgets/${row.id}`">
          <template #title>
            {{ row.patient ? `${row.patient.first_name} ${row.patient.last_name}` : row.budget_number }}
          </template>
          <template #subtitle>
            {{ row.budget_number }} · {{ money(row.total) }}
          </template>
          <template #meta>
            <span
              v-if="row.valid_until"
              class="text-caption text-subtle tnum"
            >
              {{ t('dashboard.expiringBudgets.until', { date: formatDateOnly(row.valid_until, locale, { day: '2-digit', month: 'short' }) }) }}
            </span>
          </template>
        </ListRow>
      </li>
    </ul>
    <p
      v-if="total > rows.length"
      class="mt-2 text-caption text-subtle"
    >
      {{ t('dashboard.expiringBudgets.more', { n: total - rows.length }) }}
    </p>
  </SectionCard>
</template>
