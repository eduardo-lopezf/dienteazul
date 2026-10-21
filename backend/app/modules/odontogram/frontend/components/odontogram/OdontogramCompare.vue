<script setup lang="ts">
/**
 * OdontogramCompare — the chart on two dates, side by side, and what changed
 * in between: work charted, done or withdrawn, and teeth that came through or
 * fell out. For a child it shows the exchange and how caries evolved; for an
 * adult, how a plan was carried out.
 *
 * Each side is the chart as it stood that day (`GET /odontogram/at`): a
 * treatment done later is still planned there, and the eruption statuses are
 * those of the date. Each side draws the dentition of the patient's age then,
 * unless the clinician chose one for the patient. Box view: two anatomical
 * arches do not fit side by side.
 */
import type { ApiResponse, Treatment } from '~~/app/types'
import { formatDateOnly } from '~~/app/utils/date'
import { viewsForTooth } from '~~/app/utils/treatmentView'
import { boxDimmedTeeth } from '../../utils/boxChart'
import { compareCharts, type ChartChange } from '../../utils/chartCompare'
import { dentalIndices } from '../../utils/dentalIndices'
import {
  shownDentition,
  type Dentition,
  type EruptionAges,
  type EruptionStatus,
  type ShownDentition
} from '../../utils/dentitionLayout'

const props = defineProps<{
  open: boolean
  patientId: string
  /** The clinician's choice for the patient; `auto` follows the age then. */
  dentition: Dentition
  eruptionAges?: EruptionAges
}>()

const emit = defineEmits<{ close: [] }>()

const { t, locale } = useI18n()
const api = useApi()

interface ChartAt {
  date: string
  patient_age: number | null
  suggested_dentition: ShownDentition | null
  teeth: Array<{ tooth_number: number, general_condition: string, eruption_status?: EruptionStatus | null }>
  treatments: Treatment[]
}

const today = new Date().toISOString().slice(0, 10)
const dates = ref<string[]>([])
const left = ref<string | null>(null)
const right = ref<string | null>(null)
const charts = reactive<Record<'left' | 'right', ChartAt | null>>({ left: null, right: null })
const loading = ref(false)
const failed = ref(false)

const dateOptions = computed(() =>
  [...new Set([today, ...dates.value])]
    .sort((a, b) => b.localeCompare(a))
    .map(value => ({
      value,
      label: value === today
        ? t('odontogram.compare.today')
        : formatDateOnly(value, locale.value, { day: '2-digit', month: 'short', year: 'numeric' })
    }))
)

async function loadDates() {
  try {
    const response = await api.get<ApiResponse<{ dates: Array<{ date: string }> }>>(
      `/api/v1/odontogram/patients/${props.patientId}/odontogram/timeline`
    )
    dates.value = response.data.dates.map(d => d.date.slice(0, 10))
  } catch {
    dates.value = []
  }
  // From the first charted day to today: the whole story at a glance.
  const oldest = [...dates.value].sort()[0]
  left.value = oldest && oldest !== today ? oldest : today
  right.value = today
}

async function loadSide(side: 'left' | 'right', date: string | null) {
  if (!date) return
  loading.value = true
  try {
    const response = await api.get<ApiResponse<ChartAt>>(
      `/api/v1/odontogram/patients/${props.patientId}/odontogram/at?date=${date}`
    )
    charts[side] = response.data
    failed.value = false
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

// Every opening reads afresh: work may have been charted since.
watch(() => props.open, async (open) => {
  if (!open) return
  await loadDates()
  await Promise.all([loadSide('left', left.value), loadSide('right', right.value)])
}, { immediate: true })

function pick(side: 'left' | 'right', date: string) {
  if (side === 'left') left.value = date
  else right.value = date
  void loadSide(side, date)
}

/** Everything one side draws and counts. */
function sideView(chart: ChartAt | null) {
  if (!chart) return null
  const records = new Map(chart.teeth.map(tooth => [tooth.tooth_number, tooth]))
  const statusOf = (tooth: number) => records.get(tooth)?.eruption_status ?? null
  const conditionOf = (tooth: number) => records.get(tooth)?.general_condition
  const charted = (tooth: number) =>
    chart.treatments.some(tr => tr.teeth?.some(tt => tt.tooth_number === tooth))
    || (!!conditionOf(tooth) && conditionOf(tooth) !== 'healthy')
  const dentition = shownDentition(props.dentition, chart.suggested_dentition ?? 'permanent')
  return {
    age: chart.patient_age,
    dentition,
    getTreatments: (tooth: number) => viewsForTooth(chart.treatments, tooth),
    conditionOf,
    dimmed: boxDimmedTeeth(dentition, { age: chart.patient_age, charted, statusOf, ages: props.eruptionAges }),
    indices: dentalIndices({ treatments: chart.treatments, conditionOf, statusOf })
  }
}

const sides = computed(() => ({ left: sideView(charts.left), right: sideView(charts.right) }))

const changes = computed<ChartChange[]>(() => {
  if (!charts.left || !charts.right) return []
  // Always from the earlier date to the later one, whichever side holds it.
  const [before, after] = charts.left.date <= charts.right.date
    ? [charts.left, charts.right]
    : [charts.right, charts.left]
  return compareCharts(before, after)
})

function changeText(change: ChartChange): string {
  if (change.kind === 'condition') {
    return t('odontogram.compare.changes.condition', {
      condition: t(`odontogram.conditions.${change.type}`, change.type)
    })
  }
  if (change.kind === 'eruption') {
    return t('odontogram.compare.changes.eruption', {
      status: t(`odontogram.eruption.status.${change.type}`)
    })
  }
  const name = t(`odontogram.treatments.types.${change.type}`, change.type)
  if (change.kind === 'added') {
    return t(change.planned ? 'odontogram.compare.changes.addedPlanned' : 'odontogram.compare.changes.added', { name })
  }
  return t(`odontogram.compare.changes.${change.kind}`, { name })
}

function whereText(change: ChartChange): string {
  return change.teeth.length ? change.teeth.join(', ') : t('odontogram.print.wholeMouth')
}

const CHANGE_ICONS: Record<ChartChange['kind'], string> = {
  added: 'i-lucide-plus',
  performed: 'i-lucide-check',
  removed: 'i-lucide-minus',
  eruption: 'i-lucide-arrow-up-down',
  condition: 'i-lucide-stethoscope'
}
</script>

<template>
  <UModal
    :open="open"
    fullscreen
    :title="t('odontogram.compare.title')"
    @update:open="(value: boolean) => { if (!value) emit('close') }"
  >
    <template #body>
      <div
        class="space-y-6"
        data-testid="odontogram-compare"
      >
        <UAlert
          v-if="failed"
          color="error"
          variant="subtle"
          :title="t('odontogram.compare.failed')"
        />

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <section
            v-for="side in (['left', 'right'] as const)"
            :key="side"
            class="rounded-lg border border-default p-4 space-y-3"
            :data-testid="`odontogram-compare-${side}`"
          >
            <div class="flex flex-wrap items-center gap-3">
              <USelect
                :model-value="side === 'left' ? left ?? undefined : right ?? undefined"
                :items="dateOptions"
                value-key="value"
                class="w-48"
                :aria-label="t('odontogram.compare.date')"
                @update:model-value="(value: string) => pick(side, value)"
              />
              <span
                v-if="sides[side]"
                class="text-caption text-subtle"
              >
                <template v-if="sides[side]!.age !== null">
                  {{ t('odontogram.print.age', { age: sides[side]!.age }) }} ·
                </template>
                {{ t(`odontogram.dentition.${sides[side]!.dentition}`) }}
              </span>
            </div>

            <template v-if="sides[side]">
              <ToothBoxChart
                :dentition="sides[side]!.dentition"
                :get-treatments="sides[side]!.getTreatments"
                :get-condition="sides[side]!.conditionOf"
                :dimmed-teeth="sides[side]!.dimmed"
                readonly
                hide-legend
              />
              <p class="text-caption text-muted flex flex-wrap gap-4">
                <span v-if="sides[side]!.dentition !== 'deciduous'">
                  <strong class="text-default">{{ t('odontogram.indices.cpod') }} {{ sides[side]!.indices.cpod.total }}</strong>
                  · {{ t('odontogram.indices.cpodParts', sides[side]!.indices.cpod) }}
                </span>
                <span v-if="sides[side]!.dentition !== 'permanent'">
                  <strong class="text-default">{{ t('odontogram.indices.ceod') }} {{ sides[side]!.indices.ceod.total }}</strong>
                  · {{ t('odontogram.indices.ceodParts', sides[side]!.indices.ceod) }}
                </span>
              </p>
            </template>
            <USkeleton
              v-else
              class="h-48 w-full"
            />
          </section>
        </div>

        <section>
          <h3 class="text-h3 text-default mb-2">
            {{ t('odontogram.compare.changesTitle') }}
          </h3>
          <p
            v-if="!loading && charts.left && charts.right && !changes.length"
            class="text-sm text-muted"
          >
            {{ t('odontogram.compare.noChanges') }}
          </p>
          <ul
            v-else
            class="divide-y divide-default"
            data-testid="odontogram-compare-changes"
          >
            <li
              v-for="(change, i) in changes"
              :key="i"
              class="flex items-center gap-3 py-1.5 text-sm"
            >
              <UIcon
                :name="CHANGE_ICONS[change.kind]"
                class="w-4 h-4 text-muted flex-none"
              />
              <span class="w-32 flex-none font-medium tabular-nums whitespace-nowrap">{{ whereText(change) }}</span>
              <span class="text-default">{{ changeText(change) }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </UModal>
</template>
