<script setup lang="ts">
/**
 * The odontogram as a sheet for the printed record, after the paper forms:
 * the box chart with its code rows, the CPO-D / ceo-d indices, the
 * "Especificaciones" — every finding and treatment charted, tooth by tooth —
 * and room for observations and the dentist's signature.
 *
 * Opened in its own tab from the chart. No app frame (`layout: false`):
 * what is on screen is what goes to paper.
 */
import type { ApiResponse, Patient, Treatment } from '~~/app/types'
import { formatDateOnly } from '~~/app/utils/date'
import { getTreatmentDisplayName, viewsForTooth } from '~~/app/utils/treatmentView'
import { boxDimmedTeeth } from '../../../utils/boxChart'
import { dentalIndices } from '../../../utils/dentalIndices'
import { shownDentition, type ChartFacts, type EruptionStatus } from '../../../utils/dentitionLayout'

definePageMeta({ layout: false })

const route = useRoute()
const patientId = computed(() => String(route.params.patientId))
const { t, locale } = useI18n()
const api = useApi()
const clinic = useClinic()
const {
  odontogramData,
  treatments,
  fetchOdontogram,
  fetchTreatments,
  getToothRecord
} = useOdontogram()

const patient = ref<Patient | null>(null)
const loading = ref(true)
const failed = ref(false)

onMounted(async () => {
  try {
    const [found] = await Promise.all([
      api.get<ApiResponse<Patient>>(`/api/v1/patients/${patientId.value}`),
      fetchOdontogram(patientId.value),
      fetchTreatments(patientId.value),
      clinic.currentClinic.value ? Promise.resolve() : clinic.fetchClinic()
    ])
    patient.value = found.data
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
})

const dentition = computed(() =>
  shownDentition(
    odontogramData.value?.dentition ?? 'auto',
    odontogramData.value?.suggested_dentition ?? 'permanent'
  )
)

function isCharted(tooth: number): boolean {
  if (treatments.value.some(tr => tr.teeth?.some(tt => tt.tooth_number === tooth))) return true
  const record = getToothRecord(tooth)
  return !!record && record.general_condition !== 'healthy'
}

const facts = computed<ChartFacts>(() => ({
  age: odontogramData.value?.patient_age ?? null,
  charted: isCharted,
  statusOf: tooth => (getToothRecord(tooth)?.eruption_status ?? null) as EruptionStatus | null,
  ages: odontogramData.value?.eruption_ages
}))
const dimmed = computed(() => boxDimmedTeeth(dentition.value, facts.value))
const indices = computed(() =>
  dentalIndices({
    treatments: treatments.value,
    conditionOf: tooth => getToothRecord(tooth)?.general_condition,
    statusOf: facts.value.statusOf
  })
)

function treatmentsOf(tooth: number) {
  return viewsForTooth(treatments.value, tooth)
}

/** Every charted act, tooth by tooth; whole-mouth work last. */
const specifications = computed(() => {
  const name = (tr: Treatment) =>
    getTreatmentDisplayName(
      { treatment_type: tr.clinical_type, catalog_item: tr.catalog_item },
      locale.value,
      (key: string, fallback?: string) => t(key, fallback ?? key)
    )
  const rows = treatments.value.map((tr) => {
    const teeth = tr.teeth.map(tt => tt.tooth_number).sort((a, b) => a - b)
    const surfaces = [...new Set(tr.teeth.flatMap(tt => tt.surfaces ?? []))]
    const where = teeth.length
      ? teeth.join(', ')
      : tr.arch
        ? t(`odontogram.quadrants.${tr.arch}`)
        : t('odontogram.print.wholeMouth')
    return {
      id: tr.id,
      sortKey: teeth[0] ?? 999,
      where,
      what: name(tr),
      surfaces: surfaces.join(', '),
      status: t(tr.status === 'planned' ? 'odontogram.status.planned' : 'odontogram.status.existing'),
      planned: tr.status === 'planned',
      date: formatDateOnly(tr.performed_at ?? tr.recorded_at, locale.value)
    }
  })
  return rows.sort((a, b) => a.sortKey - b.sortKey)
})

const today = computed(() =>
  new Date().toLocaleDateString(locale.value, { day: '2-digit', month: '2-digit', year: 'numeric' })
)
const patientName = computed(() =>
  patient.value ? `${patient.value.first_name} ${patient.value.last_name}` : ''
)
const age = computed(() => odontogramData.value?.patient_age ?? null)

useHead({ title: () => t('odontogram.print.title') })

function print() {
  window.print()
}
</script>

<template>
  <div class="print-sheet">
    <div class="print-actions">
      <UButton
        icon="i-lucide-printer"
        :disabled="loading || failed"
        data-testid="odontogram-print-button"
        @click="print"
      >
        {{ t('odontogram.print.print') }}
      </UButton>
    </div>

    <p
      v-if="loading"
      class="text-muted"
    >
      {{ t('common.loading') }}
    </p>
    <UAlert
      v-else-if="failed"
      color="error"
      variant="subtle"
      :title="t('odontogram.print.failed')"
    />

    <template v-else>
      <header class="sheet-header">
        <div>
          <p class="sheet-clinic">
            {{ clinic.currentClinic.value?.name }}
          </p>
          <h1 class="sheet-title">
            {{ t('odontogram.print.title') }}
          </h1>
        </div>
        <dl class="sheet-meta">
          <div>
            <dt>{{ t('odontogram.print.patient') }}</dt>
            <dd>{{ patientName }}</dd>
          </div>
          <div v-if="patient?.date_of_birth">
            <dt>{{ t('odontogram.print.birthDate') }}</dt>
            <dd>
              {{ formatDateOnly(patient.date_of_birth, locale) }}
              <template v-if="age !== null">
                ({{ t('odontogram.print.age', { age }) }})
              </template>
            </dd>
          </div>
          <div>
            <dt>{{ t('odontogram.print.dentition') }}</dt>
            <dd>{{ t(`odontogram.dentition.${dentition}`) }}</dd>
          </div>
          <div>
            <dt>{{ t('odontogram.print.date') }}</dt>
            <dd>{{ today }}</dd>
          </div>
        </dl>
      </header>

      <section class="sheet-chart">
        <ToothBoxChart
          :dentition="dentition"
          :get-treatments="treatmentsOf"
          :get-condition="(tooth: number) => getToothRecord(tooth)?.general_condition"
          :dimmed-teeth="dimmed"
          readonly
        />
      </section>

      <section class="sheet-indices">
        <span v-if="dentition !== 'deciduous'">
          <strong>{{ t('odontogram.indices.cpod') }} {{ indices.cpod.total }}</strong>
          · {{ t('odontogram.indices.cpodParts', indices.cpod) }}
        </span>
        <span v-if="dentition !== 'permanent'">
          <strong>{{ t('odontogram.indices.ceod') }} {{ indices.ceod.total }}</strong>
          · {{ t('odontogram.indices.ceodParts', indices.ceod) }}
        </span>
      </section>

      <section>
        <h2 class="sheet-section">
          {{ t('odontogram.print.specifications') }}
        </h2>
        <p
          v-if="!specifications.length"
          class="sheet-empty"
        >
          {{ t('odontogram.print.nothingCharted') }}
        </p>
        <table
          v-else
          class="sheet-table"
          data-testid="odontogram-print-specifications"
        >
          <thead>
            <tr>
              <th>{{ t('odontogram.print.tooth') }}</th>
              <th>{{ t('odontogram.print.finding') }}</th>
              <th>{{ t('odontogram.print.surfaces') }}</th>
              <th>{{ t('odontogram.print.status') }}</th>
              <th>{{ t('odontogram.print.recorded') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in specifications"
              :key="row.id"
            >
              <td>{{ row.where }}</td>
              <td>{{ row.what }}</td>
              <td>{{ row.surfaces }}</td>
              <td :class="row.planned ? 'mark-planned' : 'mark-existing'">
                {{ row.status }}
              </td>
              <td>{{ row.date }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2 class="sheet-section">
          {{ t('odontogram.print.observations') }}
        </h2>
        <div class="sheet-lines">
          <div
            v-for="n in 4"
            :key="n"
          />
        </div>
      </section>

      <footer class="sheet-signature">
        <div>{{ t('odontogram.print.signature') }}</div>
      </footer>
    </template>
  </div>
</template>

<style scoped>
.print-sheet {
  max-width: 820px;
  margin: 0 auto;
  padding: 24px 16px 48px;
  background: #fff;
  color: #111;
  min-height: 100vh;
  font-size: 13px;
  /* The box chart reads the theme's tokens; paper is always light. */
  --color-text-muted: #555;
  --color-border-strong: #999;
  --color-primary-soft: transparent;
}

.print-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 16px;
}

.sheet-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  border-bottom: 2px solid #111;
  padding-bottom: 8px;
  margin-bottom: 16px;
}

.sheet-clinic {
  font-size: 12px;
  color: #555;
}

.sheet-title {
  font-size: 20px;
  font-weight: 700;
}

.sheet-meta {
  display: grid;
  grid-template-columns: auto auto;
  gap: 2px 16px;
}

.sheet-meta dt {
  color: #555;
  font-size: 11px;
}

.sheet-meta dd {
  font-weight: 600;
}

.sheet-chart {
  border: 1px solid #999;
  padding: 12px 8px;
  margin-bottom: 8px;
}

.sheet-indices {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
}

.sheet-section {
  font-size: 14px;
  font-weight: 700;
  margin: 16px 0 6px;
  border-bottom: 1px solid #999;
}

.sheet-empty {
  color: #555;
}

.sheet-table {
  width: 100%;
  border-collapse: collapse;
}

.sheet-table th,
.sheet-table td {
  border: 1px solid #bbb;
  padding: 3px 6px;
  text-align: left;
  vertical-align: top;
}

.sheet-table th {
  background: #f2f2f2;
  font-size: 11px;
}

.mark-existing {
  color: #2563EB;
}

.mark-planned {
  color: #DC2626;
}

.sheet-lines div {
  height: 26px;
  border-bottom: 1px solid #bbb;
}

.sheet-signature {
  display: flex;
  justify-content: flex-end;
  margin-top: 56px;
}

.sheet-signature div {
  width: 260px;
  border-top: 1px solid #111;
  text-align: center;
  padding-top: 4px;
}

@media print {
  .print-actions {
    display: none;
  }

  .print-sheet {
    padding: 0;
    max-width: none;
  }

  .sheet-table tr,
  .sheet-chart {
    break-inside: avoid;
  }
}

@page {
  size: A4;
  margin: 12mm;
}
</style>
