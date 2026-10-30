<script setup lang="ts">
import type {
  BillingSummary,
  NumberingGap,
  OverdueInvoice,
  PaymentMethodSummary,
  ProfessionalBillingSummary,
  VatSummaryItem
} from '~~/app/types'
import FilterDateRange from '~~/app/components/shared/FilterDateRange.vue'
import SnapshotBadge from '../../components/SnapshotBadge.vue'
import EmptyPeriodNotice from '../../components/EmptyPeriodNotice.vue'
import ReportExportButton from '~~/app/components/shared/ReportExportButton.vue'
import BackButton from '~~/app/components/shared/BackButton.vue'

const { t, locale } = useI18n()
const router = useRouter()

// This section's App is off (ADR 0037): back to the reports that remain.
const { on: appOn, loaded: appsLoaded } = useReportApps()
watchEffect(() => {
  if (appsLoaded.value && !appOn('billing')) void router.replace('/reports')
})
const {
  fetchBillingSummary,
  fetchOverdueInvoices,
  fetchByPaymentMethod,
  fetchBillingByProfessional,
  fetchVatSummary,
  fetchNumberingGaps,
  formatCurrency,
  getPaymentMethodLabel
} = useReports()

// State
const isLoading = ref(false)
const summary = ref<BillingSummary | null>(null)
const overdueInvoices = ref<OverdueInvoice[]>([])
const paymentMethods = ref<PaymentMethodSummary[]>([])
const professionals = ref<ProfessionalBillingSummary[]>([])
const vatSummary = ref<VatSummaryItem[]>([])
const numberingGaps = ref<NumberingGap[]>([])

// One range for the whole Productividad section (``useReportPeriod``),
// mirrored into the URL so the period survives the drill-down.
const { period, model: dateRangeModel, syncQuery } = useReportPeriod()
syncQuery()

// Nothing issued and nothing collected: the range, not the clinic, is
// usually what is wrong. The snapshot figures below still mean something,
// so the notice goes above them rather than replacing the screen.
const periodIsEmpty = computed(() =>
  !isLoading.value
  && !!summary.value
  && summary.value.invoice_count === 0
  && Number(summary.value.total_paid) === 0
)

// Load all report data
async function loadReports() {
  isLoading.value = true

  try {
    const [
      summaryData,
      overdueData,
      paymentMethodsData,
      professionalsData,
      vatData,
      gapsData
    ] = await Promise.all([
      fetchBillingSummary(period.value.from, period.value.to),
      fetchOverdueInvoices(),
      fetchByPaymentMethod(period.value.from, period.value.to),
      fetchBillingByProfessional(period.value.from, period.value.to),
      fetchVatSummary(period.value.from, period.value.to),
      fetchNumberingGaps()
    ])

    summary.value = summaryData
    overdueInvoices.value = overdueData
    paymentMethods.value = paymentMethodsData
    professionals.value = professionalsData
    vatSummary.value = vatData
    numberingGaps.value = gapsData
  } catch (e) {
    console.error('Failed to load reports:', e)
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

// Format date
function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString(locale.value, {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

// Get payment method icon
function getPaymentMethodIcon(method: string): string {
  const icons: Record<string, string> = {
    cash: 'i-lucide-banknote',
    card: 'i-lucide-credit-card',
    bank_transfer: 'i-lucide-building-2',
    direct_debit: 'i-lucide-repeat',
    other: 'i-lucide-circle'
  }
  return icons[method] || 'i-lucide-circle'
}

// Navigate to invoice
function goToInvoice(id: string) {
  router.push(`/invoices/${id}`)
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
            {{ t('reports.billing.title') }}
          </h1>
          <p class="text-caption text-subtle truncate">
            {{ t('reports.billing.description') }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <FilterDateRange
          v-model="dateRangeModel"
          :label="t('common.period')"
        />
        <ReportExportButton
          endpoint="/api/v1/reports/billing/export"
          stem="facturacion"
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
              {{ t('reports.billing.totalInvoiced') }}
            </p>
            <p class="text-display text-default">
              {{ formatCurrency(summary.total_invoiced) }}
            </p>
            <p class="text-caption text-subtle">
              {{ summary.invoice_count }} {{ t('reports.billing.invoices') }}
            </p>
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.billing.totalCollected') }}
            </p>
            <p class="text-display text-default text-success-accent">
              {{ formatCurrency(summary.total_paid) }}
            </p>
            <p class="text-caption text-subtle">
              {{ summary.paid_count }} {{ t('reports.billing.paid') }}
            </p>
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.billing.pending') }}
            </p>
            <p class="text-display text-default text-warning-accent">
              {{ formatCurrency(summary.total_pending) }}
            </p>
            <SnapshotBadge />
          </div>
        </UCard>

        <UCard>
          <div class="text-center">
            <p class="text-caption text-subtle">
              {{ t('reports.billing.overdue') }}
            </p>
            <p
              class="text-display text-default"
              :class="summary.overdue_count > 0 ? 'text-danger-accent' : 'text-default'"
            >
              {{ summary.overdue_count }}
            </p>
            <p class="text-caption text-subtle">
              {{ t('reports.billing.invoices') }}
            </p>
            <SnapshotBadge />
          </div>
        </UCard>
      </div>

      <!-- Numbering Gaps Alert -->
      <UAlert
        v-if="numberingGaps.length > 0"
        color="warning"
        icon="i-lucide-alert-triangle"
      >
        <template #title>
          <span class="flex items-center gap-2">
            {{ t('reports.billing.gapsDetected') }}
            <SnapshotBadge />
          </span>
        </template>
        <template #description>
          <div class="space-y-1">
            <div
              v-for="gap in numberingGaps"
              :key="`${gap.series_prefix}-${gap.year}`"
              class="text-sm"
            >
              {{ gap.series_prefix }}-{{ gap.year }}:
              {{ t('reports.billing.missingNumbers') }}
              <span class="font-mono">{{ gap.missing_numbers.join(', ') }}</span>
            </div>
          </div>
        </template>
      </UAlert>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Payment Methods -->
        <UCard>
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.billing.byPaymentMethod') }}
            </h3>
          </template>

          <div
            v-if="paymentMethods.length > 0"
            class="space-y-3"
          >
            <div
              v-for="pm in paymentMethods"
              :key="pm.payment_method"
              class="flex items-center justify-between"
            >
              <div class="flex items-center gap-2">
                <UIcon
                  :name="getPaymentMethodIcon(pm.payment_method)"
                  class="h-5 w-5 text-subtle"
                />
                <span class="text-muted">
                  {{ getPaymentMethodLabel(pm.payment_method) }}
                </span>
              </div>
              <div class="text-right">
                <p class="font-semibold text-default">
                  {{ formatCurrency(pm.total_amount) }}
                </p>
                <p class="text-caption text-subtle">
                  {{ pm.payment_count }} {{ t('reports.billing.payments') }}
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

        <!-- VAT Summary -->
        <UCard>
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.billing.vatSummary') }}
            </h3>
          </template>

          <div
            v-if="vatSummary.length > 0"
            class="overflow-x-auto"
          >
            <table class="min-w-full divide-y divide-[var(--color-border-subtle)]">
              <thead>
                <tr>
                  <th class="px-3 py-2 text-left text-xs font-medium text-subtle uppercase">
                    {{ t('reports.billing.vatType') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('reports.billing.base') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('reports.billing.tax') }}
                  </th>
                  <th class="px-3 py-2 text-right text-xs font-medium text-subtle uppercase">
                    {{ t('invoice.total') }}
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-[var(--color-border-subtle)]">
                <tr
                  v-for="vat in vatSummary"
                  :key="vat.vat_type_id || 'exempt'"
                >
                  <td class="px-3 py-2 text-sm text-muted">
                    {{ vat.vat_name }} ({{ vat.vat_rate }}%)
                  </td>
                  <td class="px-3 py-2 text-sm text-right text-muted">
                    {{ formatCurrency(vat.base_amount) }}
                  </td>
                  <td class="px-3 py-2 text-sm text-right text-muted">
                    {{ formatCurrency(vat.tax_amount) }}
                  </td>
                  <td class="px-3 py-2 text-sm text-right font-medium text-default">
                    {{ formatCurrency(vat.total_amount) }}
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

        <!-- Billing by Professional -->
        <UCard>
          <template #header>
            <h3 class="font-semibold text-default">
              {{ t('reports.billing.byProfessional') }}
            </h3>
          </template>

          <div
            v-if="professionals.length > 0"
            class="space-y-3"
          >
            <div
              v-for="prof in professionals"
              :key="prof.professional_id"
              class="flex items-center justify-between"
            >
              <div class="flex items-center gap-2">
                <UAvatar
                  :alt="prof.professional_name"
                  size="sm"
                />
                <span class="text-muted">
                  {{ prof.professional_name }}
                </span>
              </div>
              <div class="text-right">
                <p class="font-semibold text-default">
                  {{ formatCurrency(prof.total_invoiced) }}
                </p>
                <p class="text-caption text-subtle">
                  {{ prof.invoice_count }} {{ t('reports.billing.invoices') }}
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

        <!-- Overdue Invoices -->
        <UCard>
          <template #header>
            <div class="flex items-center justify-between">
              <h3 class="font-semibold text-default flex items-center gap-2">
                {{ t('reports.billing.overdueInvoices') }}
                <SnapshotBadge />
              </h3>
              <UBadge
                v-if="overdueInvoices.length > 0"
                color="error"
              >
                {{ overdueInvoices.length }}
              </UBadge>
            </div>
          </template>

          <div
            v-if="overdueInvoices.length > 0"
            class="divide-y divide-[var(--color-border-subtle)] max-h-80 overflow-y-auto"
          >
            <div
              v-for="inv in overdueInvoices"
              :key="inv.id"
              class="py-3 hover:bg-surface-muted cursor-pointer"
              @click="goToInvoice(inv.id)"
            >
              <div class="flex justify-between items-start">
                <div>
                  <p class="font-medium text-default">
                    {{ inv.invoice_number }}
                  </p>
                  <p class="text-caption text-subtle">
                    {{ inv.patient_name }}
                  </p>
                </div>
                <div class="text-right">
                  <p class="font-semibold text-danger-accent">
                    {{ formatCurrency(inv.balance_due) }}
                  </p>
                  <p class="text-xs text-danger-accent">
                    {{ inv.days_overdue }} {{ t('reports.billing.daysOverdue') }}
                  </p>
                </div>
              </div>
              <p class="text-xs text-subtle mt-1">
                {{ t('invoice.dueDate') }}: {{ formatDate(inv.due_date) }}
              </p>
            </div>
          </div>
          <div
            v-else
            class="text-center py-8"
          >
            <UIcon
              name="i-lucide-check-circle"
              class="h-12 w-12 text-success-accent mx-auto mb-2"
            />
            <p class="text-subtle">
              {{ t('reports.billing.noOverdue') }}
            </p>
          </div>
        </UCard>
      </div>
    </template>
  </div>
</template>
