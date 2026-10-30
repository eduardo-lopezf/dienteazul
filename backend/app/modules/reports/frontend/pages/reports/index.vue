<script setup lang="ts">
import FilterDateRange from '~~/app/components/shared/FilterDateRange.vue'
import { PERMISSIONS } from '~~/app/config/permissions'
import { useDashboardSnapshot } from '../../composables/useDashboardSnapshot'
import CashCollectedTile from '../../components/dashboard/CashCollectedTile.vue'
import PatientAdvanceCard from '../../components/dashboard/PatientAdvanceCard.vue'
import ProductionTotalTile from '../../components/dashboard/ProductionTotalTile.vue'
import PaymentMethodsTile from '../../components/dashboard/PaymentMethodsTile.vue'
import CashCollectedChartCard from '../../components/dashboard/CashCollectedChartCard.vue'
import ProductionByDoctorCard from '../../components/dashboard/ProductionByDoctorCard.vue'
import NewPatientsTile from '../../components/dashboard/NewPatientsTile.vue'
import AppointmentFunnelTile from '../../components/dashboard/AppointmentFunnelTile.vue'
import AvgCollectedTicketTile from '../../components/dashboard/AvgCollectedTicketTile.vue'
import AgingReceivablesCard from '../../components/dashboard/AgingReceivablesCard.vue'
import EmptyPeriodNotice from '../../components/EmptyPeriodNotice.vue'
import ReportPdfButton from '~~/app/components/shared/ReportPdfButton.vue'
import SummaryScheduleModal from '../../components/SummaryScheduleModal.vue'
import MonthlyTargetsCard from '../../components/dashboard/MonthlyTargetsCard.vue'

const { t } = useI18n()
const { can } = usePermissions()

const { filters, state, periodIsEmpty } = useDashboardSnapshot()

// One range for the whole section, mirrored into the URL so it can be
// bookmarked and so a drill-down carries it over.
const { model: dateRangeModel, syncQuery } = useReportPeriod()
syncQuery()

// A section shows only while its App runs (ADR 0037).
const { on } = useReportApps()
const canPayments = computed(() => can('payments.reports.read') && on('payments'))
const canScheduling = computed(() => can('reports.scheduling.read') && on('agenda'))
const canBilling = computed(() => can('reports.billing.read') && on('billing'))
const canBudgets = computed(() => can('reports.budgets.read') && on('budget'))
// The one-pager has a permission of its own: "see how the clinic is
// doing" is granted separately from reading the invoice ledger.
const canPrintSummary = computed(() => can(PERMISSIONS.reports.summaryRead))
// Writing the standing order is its own grant: the dialog shows the
// staff addresses that receive the summary.
const canScheduleSummary = computed(() => can(PERMISSIONS.reports.summaryWrite))
const schedulingSummary = ref(false)

// Targets are monthly, the period is any range: the card shows the month
// the period ends in, which is the only rule that needs no explaining.
const targetsMonth = computed(() => `${filters.value.to.slice(0, 7)}-01`)

const noAccess = computed(
  () => !canPayments.value && !canScheduling.value && !canBilling.value && !canBudgets.value
)

// Drill-down chips rendered right under the page header. The payments
// chip is hardcoded (payments is in manifest.depends already) so we get
// a uniform compact look instead of relying on the legacy
// `reports.categories` UCard slot, which was sized for the old 3-card
// nav grid.
const drilldownCards = computed(() => [
  {
    key: 'billing',
    label: t('reports.billing.title'),
    icon: 'i-lucide-receipt',
    to: '/reports/billing',
    visible: canBilling.value
  },
  {
    key: 'budgets',
    label: t('reports.budgets.title'),
    icon: 'i-lucide-file-text',
    to: '/reports/budgets',
    visible: canBudgets.value
  },
  {
    key: 'scheduling',
    label: t('reports.scheduling.title'),
    icon: 'i-lucide-calendar-check',
    to: '/reports/scheduling',
    visible: canScheduling.value
  },
  {
    key: 'payments',
    label: t('reports.dashboard.drilldown.payments'),
    icon: 'i-lucide-wallet',
    to: '/reports/payments',
    visible: canPayments.value
  },
  {
    key: 'actionable',
    label: t('reports.actionable.title'),
    icon: 'i-lucide-list-checks',
    to: '/reports/actionable',
    visible: can(PERMISSIONS.reports.actionableRead)
  }
])
</script>

<template>
  <div class="space-y-6">
    <!-- Sticky header: title + date range filter -->
    <header
      class="sticky top-0 z-10 -mx-4 px-4 py-3 bg-surface border-b border-default flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="min-w-0">
        <h1 class="text-display text-default truncate">
          {{ t('reports.dashboard.title') }}
        </h1>
        <p class="text-caption text-muted truncate">
          {{ t('reports.dashboard.subtitle') }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <FilterDateRange
          v-model="dateRangeModel"
          :label="t('common.period')"
        />
        <ReportPdfButton
          v-if="canPrintSummary"
          endpoint="/api/v1/reports/summary.pdf"
          :label="t('reports.summaryPdf.action')"
        />
        <UButton
          v-if="canScheduleSummary"
          variant="soft"
          color="neutral"
          icon="i-lucide-mail-plus"
          :aria-label="t('reports.scheduleSummary.action')"
          @click="schedulingSummary = true"
        >
          {{ t('reports.scheduleSummary.action') }}
        </UButton>
      </div>
    </header>

    <!-- Empty / no-access state -->
    <div
      v-if="noAccess"
      class="text-center py-12"
    >
      <UIcon
        name="i-lucide-lock"
        class="h-12 w-12 text-subtle mx-auto mb-4"
      />
      <p class="text-subtle">
        {{ t('reports.noAccess') }}
      </p>
    </div>

    <template v-else>
      <!-- Drill-down chips: keep detail pages one tap away, right under
           the header. Horizontal scroll on mobile so the row stays a
           single line; flex-wrap on tablet+. -->
      <nav
        v-if="drilldownCards.some(c => c.visible)"
        :aria-label="t('reports.dashboard.drilldown.title')"
        class="-mx-4 px-4 flex gap-2 overflow-x-auto sm:flex-wrap sm:overflow-visible scrollbar-thin"
      >
        <template
          v-for="card in drilldownCards"
          :key="card.key"
        >
          <NuxtLink
            v-if="card.visible"
            :to="card.to"
            class="inline-flex items-center gap-2 shrink-0 rounded-full border border-default bg-surface px-3 py-1.5 text-ui text-default transition-colors hover:bg-surface-muted hover:border-primary-accent"
          >
            <UIcon
              :name="card.icon"
              class="h-4 w-4 text-primary-accent"
            />
            <span class="truncate">{{ card.label }}</span>
          </NuxtLink>
        </template>
      </nav>

      <EmptyPeriodNotice v-if="periodIsEmpty" />

      <!-- Hero row: the headline KPIs. Cash collected, patient credit
           (snapshot), production total, and average collected ticket. The
           sales-by-method breakdown is a donut and gets the charts row
           where it has space for its legend. -->
      <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <CashCollectedTile
          v-if="canPayments"
          :state="state.paymentsCurrent"
        />
        <PatientAdvanceCard
          v-if="canPayments"
          :state="state.paymentsCurrent"
        />
        <ProductionTotalTile
          v-if="canPayments"
          :state="state.production"
        />
        <AvgCollectedTicketTile
          v-if="canPayments"
          :state="state.paymentsCurrent"
        />
      </section>

      <!-- Charts row: cash trend + payment-method breakdown -->
      <section
        v-if="canPayments"
        class="grid grid-cols-1 lg:grid-cols-2 gap-4"
      >
        <CashCollectedChartCard :state="state.paymentsTrends" />
        <PaymentMethodsTile :state="state.methods" />
      </section>

      <!-- Production by doctor: full width — the bar list breathes
           best at full-width on desktop. -->
      <ProductionByDoctorCard
        v-if="canPayments"
        :state="state.production"
      />

      <!-- Operations row -->
      <section
        v-if="canScheduling"
        class="grid grid-cols-1 sm:grid-cols-2 gap-3"
      >
        <NewPatientsTile :state="state.newPatients" />
        <AppointmentFunnelTile :state="state.funnel" />
      </section>

      <!-- Goals, beside the figures they judge -->
      <MonthlyTargetsCard
        v-if="canPrintSummary"
        :month="targetsMonth"
      />

      <!-- Attention row -->
      <AgingReceivablesCard
        v-if="canPayments"
        :state="state.aging"
      />

      <!-- Extensibility: other modules can inject their own dashboard widgets. -->
      <ModuleSlot
        name="reports.dashboard.widgets"
        :ctx="{ filters }"
      />
    </template>

    <SummaryScheduleModal
      v-if="canScheduleSummary"
      v-model:open="schedulingSummary"
    />
  </div>
</template>
