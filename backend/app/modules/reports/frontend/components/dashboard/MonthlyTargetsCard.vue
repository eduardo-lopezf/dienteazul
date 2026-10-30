<script setup lang="ts">
/**
 * Objetivos del mes — the goals the clinic set, and how it is doing.
 *
 * A figure says what happened; a figure next to a goal says whether that
 * was good. The card answers the second question for the three things a
 * clinic steers by: what it collected, what it produced and how many new
 * patients came.
 *
 * **The colour is judged against the calendar, not only the goal.** Half
 * a target on the 5th is ahead; the same half on the 28th is behind, and
 * a bar that only knew the goal would paint both the same amber. For a
 * month already over the reference is simply 100%.
 */
import SummaryCard from '~~/app/components/shared/SummaryCard.vue'
import BarRow from '~~/app/components/charts/BarRow.vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import {
  useMonthlyTargets,
  monthElapsedPct,
  type TargetDraft
} from '../../composables/useMonthlyTargets'

const props = defineProps<{
  /** Any day of the month to show; the panel passes its period's end. */
  month: string
}>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const { format: money } = useCurrency()
const toast = useToast()

const { targets, loading, saving, failed, load, save } = useMonthlyTargets()

const canEdit = computed(() => can(PERMISSIONS.reports.summaryWrite))
const editing = ref(false)
const draft = ref<TargetDraft>({
  collected_target: null,
  production_target: null,
  new_patients_target: null
})

watch(() => props.month, month => load(month), { immediate: true })

const elapsed = computed(() => monthElapsedPct(props.month))

const monthLabel = computed(() =>
  new Date(`${props.month}T00:00:00`).toLocaleDateString(locale.value, {
    month: 'long',
    year: 'numeric'
  })
)

type Role = 'success' | 'warning' | 'danger' | 'neutral'

function tone(ratio: number | null): Role {
  if (ratio === null) return 'neutral'
  if (ratio >= 100) return 'success'
  // Behind the calendar by a fifth or more is the line worth a red.
  if (ratio >= elapsed.value * 0.8) return 'warning'
  return 'danger'
}

const rows = computed(() => {
  const data = targets.value
  if (!data) return []
  return [
    {
      key: 'collected',
      label: t('reports.targets.collected'),
      attainment: data.collected,
      valueLabel: money(Number(data.collected.actual))
    },
    {
      key: 'production',
      label: t('reports.targets.production'),
      attainment: data.production,
      valueLabel: money(Number(data.production.actual))
    },
    {
      key: 'new_patients',
      label: t('reports.targets.newPatients'),
      attainment: data.new_patients,
      valueLabel: String(Number(data.new_patients.actual))
    }
  ]
})

const nothingSet = computed(() => rows.value.every(row => row.attainment.target === null))

function startEditing() {
  const data = targets.value
  draft.value = {
    collected_target: data?.collected.target ? Number(data.collected.target) : null,
    production_target: data?.production.target ? Number(data.production.target) : null,
    new_patients_target: data?.new_patients.target ? Number(data.new_patients.target) : null
  }
  editing.value = true
}

async function submit() {
  try {
    await save(props.month, draft.value)
    editing.value = false
  } catch {
    toast.add({ title: t('reports.targets.failed'), color: 'error' })
  }
}

function hint(attainment: { target: string | null, ratio: number | null }): string {
  if (attainment.target === null) return t('reports.targets.noGoal')
  return t('reports.targets.ofGoal', { ratio: attainment.ratio ?? 0 })
}
</script>

<template>
  <SummaryCard
    :title="t('reports.targets.title', { month: monthLabel })"
    icon="i-lucide-target"
    severity="info"
    :loading="loading"
    :empty="failed"
  >
    <template #header-trailing>
      <UButton
        v-if="canEdit && !editing"
        class="ml-auto"
        color="neutral"
        variant="ghost"
        icon="i-lucide-pencil"
        size="xs"
        :aria-label="t('reports.targets.edit')"
        @click="startEditing"
      />
    </template>

    <template #empty>
      {{ t('reports.targets.failed') }}
    </template>

    <div
      v-if="editing"
      class="space-y-3"
    >
      <UFormField :label="t('reports.targets.collected')">
        <UInput
          v-model.number="draft.collected_target"
          type="number"
          min="0"
          step="0.01"
        />
      </UFormField>
      <UFormField :label="t('reports.targets.production')">
        <UInput
          v-model.number="draft.production_target"
          type="number"
          min="0"
          step="0.01"
        />
      </UFormField>
      <UFormField :label="t('reports.targets.newPatients')">
        <UInput
          v-model.number="draft.new_patients_target"
          type="number"
          min="0"
        />
      </UFormField>
      <p class="text-caption text-subtle">
        {{ t('reports.targets.clearHint') }}
      </p>
      <div class="flex items-center justify-end gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          size="sm"
          @click="editing = false"
        >
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          color="primary"
          size="sm"
          :loading="saving"
          @click="submit"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </div>

    <div
      v-else
      class="space-y-3"
    >
      <ul class="space-y-3">
        <li
          v-for="row in rows"
          :key="row.key"
        >
          <BarRow
            :value="row.attainment.ratio ?? 0"
            :max="100"
            :label="row.label"
            :value-label="row.valueLabel"
            :hint="hint(row.attainment)"
            :tone="tone(row.attainment.ratio)"
          />
        </li>
      </ul>

      <p
        v-if="nothingSet"
        class="text-caption text-subtle"
      >
        {{ t('reports.targets.empty') }}
      </p>
      <p
        v-else
        class="text-caption text-subtle"
      >
        {{ t('reports.targets.elapsed', { pct: elapsed }) }}
      </p>
    </div>
  </SummaryCard>
</template>
