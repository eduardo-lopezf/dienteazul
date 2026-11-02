<script setup lang="ts">
/**
 * What the material used in the period cost, by treatment.
 *
 * The figures come from the Inventario App through a contract; this
 * card only draws them. With that App off the page does not render it
 * at all, which is why there is no "unavailable" state here.
 *
 * A treatment showing zero is not a free treatment: it is material
 * nobody put a price on. The card says so once, under the table,
 * rather than letting a column of zeros speak for itself.
 */
import SummaryCard from '~~/app/components/shared/SummaryCard.vue'
import type { MaterialCostSummary } from '../../composables/useReports'

interface Props {
  state: {
    loading: boolean
    error: boolean
    data: MaterialCostSummary | null
  }
}

const TOP_N = 8

const props = defineProps<Props>()
const { t } = useI18n()
const { format } = useCurrency()

const rows = computed(() => (props.state.data?.lines ?? []).slice(0, TOP_N))
const hidden = computed(() => Math.max(0, (props.state.data?.lines.length ?? 0) - TOP_N))
</script>

<template>
  <SummaryCard
    :title="t('reports.dashboard.materials.title')"
    :loading="state.loading"
    :error="state.error"
  >
    <template #default>
      <p class="mb-3 text-2xl font-semibold tabular-nums">
        {{ format(Number(state.data?.total ?? 0)) }}
        <span class="text-sm font-normal text-subtle">
          {{ t('reports.dashboard.materials.consumed') }}
        </span>
      </p>

      <p
        v-if="rows.length === 0"
        class="text-sm text-subtle"
      >
        {{ t('reports.dashboard.materials.empty') }}
      </p>

      <table
        v-else
        class="w-full text-sm"
      >
        <thead class="text-left text-xs text-subtle">
          <tr>
            <th class="pb-1">
              {{ t('reports.dashboard.materials.treatment') }}
            </th>
            <th class="pb-1 text-right">
              {{ t('reports.dashboard.materials.count') }}
            </th>
            <th class="pb-1 text-right">
              {{ t('reports.dashboard.materials.perTreatment') }}
            </th>
            <th class="pb-1 text-right">
              {{ t('reports.dashboard.materials.total') }}
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="row in rows"
            :key="row.catalog_item_id ?? '__unknown__'"
          >
            <td class="py-1">
              {{ row.treatment_name }}
            </td>
            <td class="py-1 text-right tabular-nums">
              {{ row.treatments }}
            </td>
            <td class="py-1 text-right tabular-nums">
              {{ format(Number(row.cost_per_treatment)) }}
            </td>
            <td class="py-1 text-right font-medium tabular-nums">
              {{ format(Number(row.cost)) }}
            </td>
          </tr>
        </tbody>
      </table>

      <p
        v-if="hidden > 0"
        class="mt-2 text-xs text-subtle"
      >
        {{ t('reports.dashboard.materials.more', { count: hidden }) }}
      </p>

      <p
        v-if="state.data?.unpriced_note"
        class="mt-2 text-xs text-subtle"
      >
        {{ t('reports.dashboard.materials.unpriced') }}
      </p>
    </template>
  </SummaryCard>
</template>
