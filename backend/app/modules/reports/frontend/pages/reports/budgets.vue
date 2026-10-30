<script setup lang="ts">
import type {
  BudgetSummary,
  BudgetByProfessional,
  BudgetByTreatment,
  BudgetByStatus
} from '../../composables/useReports'
import FilterDateRange from '~~/app/components/shared/FilterDateRange.vue'
import BackButton from '~~/app/components/shared/BackButton.vue'
import EmptyPeriodNotice from '../../components/EmptyPeriodNotice.vue'
import ReportExportButton from '~~/app/components/shared/ReportExportButton.vue'
import { BUDGET_STATUS_ROLE, roleToUiColor, type BudgetStatus, type UiColor } from '~~/app/config/severity'

const { t } = useI18n()
const router = useRouter()

// This section's App is off (ADR 0037): back to the reports that remain.
const { on: appOn, loaded: appsLoaded } = useReportApps()
watchEffect(() => {
  if (appsLoaded.value && !appOn('budget')) void router.replace('/reports')
})
const {
  fetchBudgetSummary,
  fetchBudgetsByProfessional,
  fetchBudgetsByTreatment,
  fetchBudgetsByStatus,
  formatCurrency,
  getBudgetStatusLabel
} = useReports()

// State
const isLoading = ref(false)
const summary = ref<BudgetSummary | null>(null)
const byProfessional = ref<BudgetByProfessional[]>([])
const byTreatment = ref<BudgetByTreatment[]>([])
const byStatus = ref<BudgetByStatus[]>([])

// One range for the whole Productividad section (``useReportPeriod``),
// mirrored into the URL so the period survives the drill-down.
const { period, model: dateRangeModel, syncQuery } = useReportPeriod()
syncQuery()

// No budget was created in the range — every figure on this screen is
// range-scoped, so the whole page is zeroes.
const periodIsEmpty = computed(() =>
  !isLoading.value && !!summary.value && summary.value.total_created === 0
)

// Load all report data
async function loadReports() {
  isLoading.value = true

  try {
    const [summaryData, professionalsData, treatmentsData, statusData] = await Promise.all([
      fetchBudgetSummary(period.value.from, period.value.to),
      fetchBudgetsByProfessional(period.value.from, period.value.to),
      fetchBudgetsByTreatment(period.value.from, period.value.to),
      fetchBudgetsByStatus(period.value.from, period.value.to)
    ])

    summary.value = summaryData
    byProfessional.value = professionalsData
    byTreatment.value = treatmentsData
    byStatus.value = statusData
  } catch (e) {
    console.error('Failed to load budget reports:', e)
  } finally {
    isLoading.value = false
  }
}

// Reload when the shared period changes
watch(period, () => {
  loadReports()
}, { deep: true })

onMounted(() => {
  loadReports()
})

// Format percentage
function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`
}

// `BUDGET_STATUS_ROLE` is the one table (`app/config/severity.ts`); a
// local copy here is what let `sent` fall back to the draft grey.
function getStatusBadgeColor(status: string): UiColor {
  return roleToUiColor(BUDGET_STATUS_ROLE[status as BudgetStatus] ?? 'neutral')
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header: back, title and the one period control -->
    <header
      class="sticky top-0 z-10 -mx-4 px-4 py-3 bg-surface border-b border-default flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex items-center gap-4 min-w-0">
        <BackButton to="/reports" />
        <div class="min-w-0">
          <h1 class="text-display text-default truncate">
            {{ t('reports.budgets.title') }}
          </h1>
          <p class="text-caption text-subtle truncate">
            {{ t('reports.budgets.description') }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <FilterDateRange
          v-model="dateRangeModel"
          :label="t('common.period')"
        />
        <ReportExportButton
          endpoint="/api/v1/reports/budgets/export"
          stem="presupuestos"
        />
      </div>
    </header>

    <!-- Loading state -->
    <div
      v-if="isLoading"
      class="flex justify-center py-12"
    >
      <UIcon
        name="i-lucide-loader-2"
        class="h-8 w-8 animate-spin text-primary-accent"
      />
    </div>

    <template v-else>
      <EmptyPeriodNotice v-if="periodIsEmpty" />

      <!-- Summary Cards -->
      <div
        v-if="summary"
        class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.budgets.labels.totalCreated') }}
            </p>
            <p class="text-display text-default">
              {{ summary.total_created }}
            </p>
            <p class="text-caption text-subtle">
              {{ formatCurrency(summary.total_amount) }}
            </p>
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.budgets.labels.accepted') }}
            </p>
            <p class="text-display text-default text-success-accent">
              {{ summary.accepted_count }}
            </p>
            <p class="text-caption text-subtle">
              {{ formatCurrency(summary.accepted_amount) }}
            </p>
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.budgets.labels.acceptanceRate') }}
            </p>
            <p class="text-display text-default text-info-accent">
              {{ formatPercent(summary.acceptance_rate) }}
            </p>
            <p class="text-caption text-subtle">
              {{ summary.rejected_count }} {{ t('reports.budgets.labels.rejected') }}
            </p>
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.budgets.labels.averageValue') }}
            </p>
            <p class="text-display text-default">
              {{ formatCurrency(summary.average_value) }}
            </p>
            <p class="text-caption text-subtle">
              {{ summary.pending_count }} {{ t('reports.budgets.labels.pending') }}
            </p>
          </div>
        </UCard>
      </div>

      <!-- Completed Budget Info -->
      <div
        v-if="summary && summary.completed_count > 0"
        class="grid grid-cols-1 md:grid-cols-2 gap-4"
      >
        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.budgets.labels.completed') }}
            </p>
            <p class="text-display text-default text-purple-600">
              {{ summary.completed_count }}
            </p>
            <p class="text-caption text-subtle">
              {{ formatCurrency(summary.completed_amount) }}
            </p>
          </div>
        </UCard>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- By Status -->
        <UCard>
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.budgets.labels.byStatus') }}
            </h3>
          </template>

          <div
            v-if="byStatus.length > 0"
            class="space-y-3"
          >
            <div
              v-for="item in byStatus"
              :key="item.status"
              class="flex items-center justify-between"
            >
              <div class="flex items-center gap-2">
                <UBadge
                  :color="getStatusBadgeColor(item.status)"
                  size="sm"
                >
                  {{ getBudgetStatusLabel(item.status) }}
                </UBadge>
              </div>
              <div class="text-right">
                <p class="font-semibold text-default">
                  {{ item.count }}
                </p>
                <p class="text-caption text-subtle">
                  {{ formatCurrency(item.total_amount) }}
                </p>
              </div>
            </div>
          </div>
          <p
            v-else
            class="text-subtle text-center py-4"
          >
            {{ t('reports.billing.noData') }}
          </p>
        </UCard>

        <!-- By Professional -->
        <UCard>
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.budgets.features.byProfessional') }}
            </h3>
          </template>

          <div
            v-if="byProfessional.length > 0"
            class="space-y-3"
          >
            <div
              v-for="prof in byProfessional"
              :key="prof.professional_id || 'unknown'"
              class="flex items-center justify-between"
            >
              <div class="flex items-center gap-2">
                <UAvatar
                  :alt="prof.professional_name"
                  size="sm"
                />
                <div>
                  <p class="text-muted">
                    {{ prof.professional_name }}
                  </p>
                  <p class="text-caption text-subtle">
                    {{ formatPercent(prof.acceptance_rate) }} {{ t('reports.budgets.labels.acceptanceRate').toLowerCase() }}
                  </p>
                </div>
              </div>
              <div class="text-right">
                <p class="font-semibold text-default">
                  {{ prof.budget_count }}
                </p>
                <p class="text-caption text-subtle">
                  {{ formatCurrency(prof.total_amount) }}
                </p>
              </div>
            </div>
          </div>
          <p
            v-else
            class="text-subtle text-center py-4"
          >
            {{ t('reports.billing.noData') }}
          </p>
        </UCard>

        <!-- By Treatment (Top 10) -->
        <UCard class="lg:col-span-2">
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.budgets.labels.topTreatments') }}
            </h3>
          </template>

          <div
            v-if="byTreatment.length > 0"
            class="overflow-x-auto"
          >
            <table class="min-w-full divide-y divide-[var(--color-border-subtle)]">
              <thead>
                <tr>
                  <th class="px-3 py-2 text-left text-xs font-medium text-subtle uppercase">
                    {{ t('reports.budgets.labels.treatment') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('reports.budgets.labels.occurrences') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('reports.budgets.labels.quantity') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('invoice.total') }}
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--color-border-subtle)]">
                <tr
                  v-for="treatment in byTreatment"
                  :key="treatment.catalog_item_id || treatment.treatment_name"
                >
                  <td class="px-3 py-2 text-sm text-muted">
                    {{ treatment.treatment_name }}
                  </td>
                  <td class="px-3 py-2 text-sm text-right text-muted">
                    {{ treatment.occurrence_count }}
                  </td>
                  <td class="px-3 py-2 text-sm text-right text-muted">
                    {{ treatment.total_quantity }}
                  </td>
                  <td class="px-3 py-2 text-sm text-right font-medium text-default">
                    {{ formatCurrency(treatment.total_amount) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p
            v-else
            class="text-subtle text-center py-4"
          >
            {{ t('reports.billing.noData') }}
          </p>
        </UCard>
      </div>
    </template>
  </div>
</template>
