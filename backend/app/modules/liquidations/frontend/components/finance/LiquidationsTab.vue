<script setup lang="ts">
/**
 * Settling with an associate dentist.
 *
 * The screen is built around one comparison and refuses to hide it: what
 * the associate **earned** and what has been **collected** for that work
 * sit side by side, with the one the percentage is taken on marked. On a
 * large case those two are months apart, and a clinic paying a percentage
 * of the first is handing out money it has not received.
 *
 * The quincena is the default period because that is when payroll is paid,
 * and it is the calendar one — the 1st to the 15th and the 16th to the end
 * of the month — for the same reason the till's period cut uses it.
 */
import type { CommissionBasis, Liquidation, PayoutMethod } from '../../composables/useLiquidations'
import { PERMISSIONS } from '~~/app/config/permissions'
import { formatDateOnly } from '~~/app/utils/date'

const { t, locale } = useI18n()
const { can } = usePermissions()
// Payments and Professionals are integrated, not required (ADR 0037):
// with either off the issued settlements are read and paid, none is worked out.
const { active, isActive } = useModules()
const canCalculate = computed(() =>
  active.value === null || (isActive('payments') && isActive('professionals'))
)
const { format: money } = useCurrency()
const { currentClinic } = useClinic()
const toast = useToast()
const { professionals, fetchProfessionals } = useProfessionals()
const {
  commissions,
  preview,
  issued,
  loading,
  fetchCommissions,
  saveCommission,
  fetchPreview,
  fetchIssued,
  issue,
  pay,
  unpay
} = useLiquidations()

const canIssue = computed(() => can(PERMISSIONS.liquidations.settlementIssue))
const canSetCommission = computed(() => can(PERMISSIONS.liquidations.commissionWrite))

/** Today in the clinic's calendar — the period is anchored on it. */
function clinicToday(): Date {
  const iso = new Intl.DateTimeFormat('en-CA', {
    timeZone: currentClinic.value?.timezone || undefined,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(new Date())
  return new Date(`${iso}T00:00:00`)
}

/**
 * The calendar quincena containing a day: the 1st-15th, or the 16th to the
 * end of the month. Not a rolling fortnight — payroll is paid on those two
 * dates, and a rolling one drifts off the month by March.
 */
function fortnightOf(day: Date): { from: string, to: string } {
  const y = day.getFullYear()
  const m = day.getMonth()
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  if (day.getDate() <= 15) {
    return { from: iso(new Date(y, m, 1)), to: iso(new Date(y, m, 15)) }
  }
  return { from: iso(new Date(y, m, 16)), to: iso(new Date(y, m + 1, 0)) }
}

const period = ref(fortnightOf(clinicToday()))
// `undefined`, not `null`: `USelect`'s model is `string | undefined`, and
// null is the shape that does not fit it.
const professionalId = ref<string | undefined>(undefined)

const professionalOptions = computed(() =>
  professionals.value.map(p => ({
    value: p.id,
    label: `${p.first_name} ${p.last_name}`
  }))
)

const commissionFor = computed(() =>
  commissions.value.find(c => c.professional_id === professionalId.value) ?? null
)

async function reload() {
  await fetchIssued(period.value.from, period.value.to)
  if (professionalId.value && canCalculate.value) {
    await fetchPreview(professionalId.value, period.value.from, period.value.to)
  }
}

onMounted(async () => {
  await Promise.all([fetchProfessionals(), fetchCommissions()])
  if (!professionalId.value && professionals.value.length) {
    professionalId.value = professionals.value[0]!.id
  }
  await reload()
})

watch([professionalId, period], reload, { deep: true })

function day(value: string): string {
  return formatDateOnly(value, locale.value, { day: '2-digit', month: 'short' })
}

// --- The arrangement --------------------------------------------------

const editingCommission = ref(false)
const basis = ref<CommissionBasis>('collected')
const percent = ref('')

const basisOptions = computed(() => [
  { value: 'collected' as CommissionBasis, label: t('liquidations.basis.collected') },
  { value: 'earned' as CommissionBasis, label: t('liquidations.basis.earned') }
])

function startCommission() {
  basis.value = (commissionFor.value?.basis ?? 'collected')
  percent.value = commissionFor.value?.percent ?? ''
  editingCommission.value = true
}

async function submitCommission() {
  if (!professionalId.value) return
  try {
    await saveCommission(professionalId.value, basis.value, String(percent.value || 0))
    editingCommission.value = false
    await fetchCommissions()
    await reload()
  } catch {
    toast.add({ title: t('liquidations.commission.saveFailed'), color: 'error' })
  }
}

// --- Paying ------------------------------------------------------------
//
// Issuing says what is owed; paying hands it over. Kept as two acts because
// they happen at different moments — the quincena is closed on the 15th and
// the associate is paid when they come in — and because a settlement that
// went out and one that is still owed are different things to look at.

const paying = ref<Liquidation | null>(null)
const payMethod = ref<PayoutMethod>('cash')
const paySaving = ref(false)

const methodOptions = computed(() => [
  { value: 'cash' as PayoutMethod, label: t('liquidations.pay.methods.cash') },
  { value: 'transfer' as PayoutMethod, label: t('liquidations.pay.methods.transfer') },
  { value: 'other' as PayoutMethod, label: t('liquidations.pay.methods.other') }
])

function startPay(row: Liquidation) {
  paying.value = row
  payMethod.value = 'cash'
}

async function submitPay() {
  if (!paying.value || paySaving.value) return
  paySaving.value = true
  try {
    await pay(paying.value.id, payMethod.value)
    paying.value = null
    await reload()
  } catch {
    toast.add({ title: t('liquidations.pay.failed'), color: 'error' })
  } finally {
    paySaving.value = false
  }
}

async function submitUnpay(row: Liquidation) {
  try {
    await unpay(row.id)
    await reload()
  } catch {
    // The usual reason is the till day having been counted, which the API
    // explains far better than a generic toast could — but a toast is all
    // this surface has, so it says where to look.
    toast.add({ title: t('liquidations.pay.undoFailed'), color: 'error' })
  }
}

// --- Issuing ----------------------------------------------------------

const issuing = ref(false)

async function submitIssue() {
  if (!professionalId.value || issuing.value) return
  issuing.value = true
  try {
    await issue(professionalId.value, period.value.from, period.value.to)
    await reload()
  } catch {
    toast.add({ title: t('liquidations.issueFailed'), color: 'error' })
  } finally {
    issuing.value = false
  }
}
</script>

<template>
  <div class="liq-tab">
    <UAlert
      v-if="!canCalculate"
      color="info"
      variant="subtle"
      icon="i-lucide-info"
      :description="t('liquidations.appsOff')"
      data-testid="liquidations-apps-off"
    />
    <div class="liq-head">
      <UFormField
        v-if="canCalculate"
        :label="t('liquidations.professional')"
      >
        <USelect
          v-model="professionalId"
          class="min-w-56"
          :items="professionalOptions"
          value-key="value"
          :aria-label="t('liquidations.professional')"
        />
      </UFormField>
      <UFormField :label="t('liquidations.from')">
        <UInput
          v-model="period.from"
          type="date"
        />
      </UFormField>
      <UFormField :label="t('liquidations.to')">
        <UInput
          v-model="period.to"
          type="date"
        />
      </UFormField>
    </div>

    <USkeleton
      v-if="loading && !preview"
      class="h-28 w-full"
    />

    <UCard v-else-if="preview && canCalculate">
      <template #header>
        <div class="flex items-center justify-between gap-2 flex-wrap">
          <span class="font-medium">
            {{ preview.professional
              ? `${preview.professional.first_name} ${preview.professional.last_name}`
              : '' }}
            · {{ day(preview.date_from) }} – {{ day(preview.date_to) }}
          </span>
          <UBadge
            v-if="preview.issued_id"
            color="neutral"
            variant="subtle"
            icon="i-lucide-lock"
            :label="t('liquidations.alreadyIssued')"
          />
        </div>
      </template>

      <!-- No arrangement yet: the work is real, the share is not. Saying so
           beats handing somebody a confident zero. -->
      <div
        v-if="preview.missing_commission"
        class="no-commission"
      >
        <UIcon
          name="i-lucide-alert-triangle"
          class="w-4 h-4 shrink-0 mt-0.5"
        />
        <div class="min-w-0">
          <p class="m-0 font-medium">
            {{ t('liquidations.commission.missing') }}
          </p>
          <p class="no-commission-why">
            {{ t('liquidations.commission.missingWhy') }}
          </p>
        </div>
      </div>

      <!-- The comparison the screen exists for. -->
      <dl class="liq-grid">
        <div :class="{ 'is-base': preview.basis === 'earned' }">
          <dt>{{ t('liquidations.earned') }}</dt>
          <dd>{{ money(preview.earned_total) }}</dd>
          <dd class="hint">
            {{ t('liquidations.earnedHint') }}
          </dd>
        </div>
        <div :class="{ 'is-base': preview.basis === 'collected' }">
          <dt>{{ t('liquidations.collected') }}</dt>
          <dd>{{ money(preview.collected_total) }}</dd>
          <dd class="hint">
            {{ t('liquidations.collectedHint') }}
          </dd>
        </div>
        <div>
          <dt>{{ t('liquidations.share') }}</dt>
          <dd>
            {{ preview.percent }} %
            <span class="basis-chip">{{ t(`liquidations.basis.${preview.basis}`) }}</span>
          </dd>
          <dd
            v-if="canSetCommission"
            class="hint"
          >
            <UButton
              color="neutral"
              variant="link"
              size="xs"
              class="p-0"
              @click="startCommission"
            >
              {{ t('liquidations.commission.edit') }}
            </UButton>
          </dd>
        </div>
        <div class="due">
          <dt>{{ t('liquidations.due') }}</dt>
          <dd>{{ money(preview.amount_due) }}</dd>
          <dd class="hint">
            {{ t('liquidations.dueHint', { base: money(preview.base_amount) }) }}
          </dd>
        </div>
      </dl>

      <ol
        v-if="preview.lines.length"
        class="line-list"
      >
        <li
          v-for="line in preview.lines"
          :key="line.treatment_id"
          class="line-row"
        >
          <span class="line-day">{{ day(line.performed_at.slice(0, 10)) }}</span>
          <span class="min-w-0 flex-1 line-what">{{ line.description || '—' }}</span>
          <span class="line-amount">{{ money(line.earned) }}</span>
          <span
            class="line-amount line-collected"
            :class="{ 'is-short': Number(line.collected) < Number(line.earned) }"
          >{{ money(line.collected) }}</span>
        </li>
      </ol>
      <p
        v-else
        class="liq-empty"
      >
        {{ t('liquidations.noWork') }}
      </p>

      <div
        v-if="canIssue && !preview.issued_id && preview.lines.length"
        class="liq-actions"
      >
        <UButton
          :loading="issuing"
          :disabled="preview.missing_commission"
          icon="i-lucide-file-check"
          @click="submitIssue"
        >
          {{ t('liquidations.issue') }}
        </UButton>
        <p class="liq-actions-why">
          {{ t('liquidations.issueWhy') }}
        </p>
      </div>
    </UCard>

    <UCard v-if="issued.length">
      <template #header>
        <span class="font-medium">{{ t('liquidations.issuedTitle') }}</span>
      </template>
      <ol class="line-list">
        <li
          v-for="row in issued"
          :key="row.id"
          class="line-row"
        >
          <span class="min-w-0 flex-1 line-what">
            {{ row.professional
              ? `${row.professional.first_name} ${row.professional.last_name}`
              : '' }}
            · {{ day(row.date_from) }} – {{ day(row.date_to) }}
          </span>
          <span class="line-percent">{{ row.percent }} % {{ t(`liquidations.basis.${row.basis}`) }}</span>
          <span class="line-amount">{{ money(row.amount_due) }}</span>

          <!-- Issued and paid are different things to look at: one is owed
               and one is gone. -->
          <template v-if="row.paid_at">
            <UBadge
              color="success"
              variant="subtle"
              icon="i-lucide-check"
              :label="t(`liquidations.pay.paidBy.${row.payment_method}`)"
            />
            <UButton
              v-if="canIssue"
              color="neutral"
              variant="ghost"
              size="xs"
              icon="i-lucide-undo-2"
              :aria-label="t('liquidations.pay.undo')"
              @click="submitUnpay(row)"
            />
          </template>
          <UButton
            v-else-if="canIssue"
            color="neutral"
            variant="outline"
            size="xs"
            @click="startPay(row)"
          >
            {{ t('liquidations.pay.action') }}
          </UButton>
        </li>
      </ol>
    </UCard>

    <UModal
      :open="paying !== null"
      :title="t('liquidations.pay.title')"
      @update:open="(v: boolean) => { if (!v) paying = null }"
    >
      <template #body>
        <p class="pay-what">
          {{ paying?.professional
            ? `${paying.professional.first_name} ${paying.professional.last_name}`
            : '' }}
          · {{ paying ? money(paying.amount_due) : '' }}
        </p>
        <UFormField
          :label="t('liquidations.pay.method')"
          :description="t('liquidations.pay.methodHint')"
        >
          <USelect
            v-model="payMethod"
            class="w-full"
            :items="methodOptions"
            value-key="value"
            :aria-label="t('liquidations.pay.method')"
          />
        </UFormField>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            @click="paying = null"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            :loading="paySaving"
            @click="submitPay"
          >
            {{ t('liquidations.pay.action') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      v-model:open="editingCommission"
      :title="t('liquidations.commission.title')"
    >
      <template #body>
        <div class="commission-form">
          <UFormField
            :label="t('liquidations.commission.basis')"
            :description="t('liquidations.commission.basisHint')"
          >
            <USelect
              v-model="basis"
              class="w-full"
              :items="basisOptions"
              value-key="value"
              :aria-label="t('liquidations.commission.basis')"
            />
          </UFormField>
          <UFormField :label="t('liquidations.commission.percent')">
            <UInput
              v-model="percent"
              class="w-full"
              type="number"
              step="0.01"
              min="0"
              max="100"
            />
          </UFormField>
          <p class="commission-note">
            {{ t('liquidations.commission.note') }}
          </p>
        </div>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            @click="editingCommission = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton @click="submitCommission">
            {{ t('common.save') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>

<style scoped>
.liq-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
  text-align: left;
}

.liq-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: 12px;
}

.no-commission {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: var(--radius-md, 8px);
  border: 1px solid var(--ui-warning, #B45309);
  background: color-mix(in oklab, var(--ui-warning, #B45309) 8%, transparent);
  font-size: 13px;
}

.no-commission-why {
  margin: 4px 0 0;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.liq-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin: 0;
}

.liq-grid > div {
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: var(--radius-md, 8px);
}

/* The one the percentage is taken on. Without this the two totals read as
   equally relevant and the whole point of showing both is lost. */
.liq-grid > div.is-base {
  border-color: var(--ui-primary, #3B82F6);
  background: color-mix(in oklab, var(--ui-primary, #3B82F6) 5%, transparent);
}

.liq-grid dt {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted, #6B7280);
}

.liq-grid dd {
  margin: 2px 0 0;
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}

.liq-grid dd.hint {
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.liq-grid .due dd:first-of-type {
  font-weight: 600;
  color: var(--ui-success, #059669);
}

.basis-chip {
  margin-left: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  font-size: 11px;
}

.line-list {
  margin: 14px 0 0;
  padding: 14px 0 0;
  border-top: 1px solid var(--color-border);
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.line-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 12px;
}

.line-day {
  width: 58px;
  flex-shrink: 0;
  color: var(--color-text-muted, #6B7280);
}

.line-what {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.line-percent {
  flex-shrink: 0;
  color: var(--color-text-muted, #6B7280);
}

.line-amount {
  width: 104px;
  flex-shrink: 0;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.line-collected.is-short {
  color: var(--ui-warning, #B45309);
}

.liq-empty {
  margin: 14px 0 0;
  font-size: 12px;
  color: var(--color-text-muted, #6B7280);
}

.liq-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}

.liq-actions-why {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.commission-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.pay-what {
  margin: 0 0 12px;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.commission-note {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}
</style>
