<script setup lang="ts">
/**
 * PaymentDetailModal — the read view of one payment.
 *
 * Four of the five lists open something when a row is tapped and this
 * one did not, which on a tablet is only discoverable by trying: there
 * is no cursor to change shape over a dead row. A payment has no detail
 * page to navigate to, so this is the card instead — where the money
 * went, what came back, and who recorded it.
 *
 * Off-books safe, like the list it opens from: gross, allocations and
 * refunded total, never an invoiced-vs-paid comparison.
 *
 * The `payments.detail.*` keys it renders were already in the locale
 * files, unused except for `refund` — this is the surface they were
 * written for.
 */
import type { PaymentRecord } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import { formatDateOnly } from '~~/app/utils/date'

const props = defineProps<{
  open: boolean
  payment: PaymentRecord | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'refund': [payment: PaymentRecord]
}>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const { format: formatCurrency } = useCurrency()

function patientName(p: PaymentRecord['patient']): string {
  if (!p) return t('payments.list.row.noPatient')
  return `${p.last_name}, ${p.first_name}`
}

function methodIcon(method: string): string {
  switch (method) {
    case 'cash': return 'i-lucide-banknote'
    case 'card': return 'i-lucide-credit-card'
    case 'bank_transfer': return 'i-lucide-landmark'
    case 'direct_debit': return 'i-lucide-repeat'
    case 'insurance': return 'i-lucide-shield'
    default: return 'i-lucide-circle-dollar-sign'
  }
}

// `payment_date` is a DATE column: `new Date()` reads it as UTC midnight
// and prints the day before west of Greenwich. Genuine timestamps still
// go through `new Date()` — see `~~/app/utils/date`.
function formatDate(s: string | undefined): string {
  if (!s) return '—'
  return formatDateOnly(s, locale.value) || '—'
}

/** Same split the row shows, so the card confirms rather than contradicts. */
const allocations = computed(() => {
  const out: { label: string, amount: number }[] = []
  let toBudget = 0
  let onAccount = 0
  let membership = 0
  for (const a of props.payment?.allocations ?? []) {
    const amount = Number(a.amount)
    if (a.target_type === 'budget') toBudget += amount
    else if (a.target_type === 'on_account') onAccount += amount
    else if (a.target_type === 'membership') membership += amount
  }
  if (toBudget) out.push({ label: t('payments.new.allocationToBudget'), amount: toBudget })
  if (onAccount) out.push({ label: t('payments.new.allocationOnAccount'), amount: onAccount })
  if (membership) out.push({ label: t('payments.new.allocationMembership'), amount: membership })
  return out
})

const refunded = computed(() => Number(props.payment?.refunded_total ?? 0))

/** Only tiles with something to say, as in the professional's card. */
const tiles = computed(() => {
  const p = props.payment
  if (!p) return []
  const out: { icon: string, label: string, value: string }[] = [
    { icon: 'i-lucide-calendar', label: t('payments.detail.date'), value: formatDate(p.payment_date) },
    { icon: methodIcon(p.method), label: t('payments.detail.method'), value: t(`payments.methods.${p.method}`) }
  ]
  if (p.reference) {
    out.push({ icon: 'i-lucide-hash', label: t('payments.detail.reference'), value: p.reference })
  }
  if (p.recorder) {
    out.push({
      icon: 'i-lucide-user-round',
      label: t('payments.detail.recordedBy'),
      value: `${p.recorder.first_name} ${p.recorder.last_name}`.trim()
    })
  }
  return out
})

const { isPortrait } = useDevice()

// Wider held upright, where the width is there and the height is what
// needs filling. Safe to read here: this card only renders after a tap.
const contentClass = computed(() =>
  isPortrait.value ? 'sm:max-w-[min(92vw,48rem)]' : 'sm:max-w-xl'
)

const canRefund = computed(() =>
  !!props.payment
  && can(PERMISSIONS.payments.recordRefund)
  && Number(props.payment.net_amount) > 0
)
</script>

<template>
  <UModal
    :open="open"
    :ui="{ content: contentClass }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #content>
      <div
        v-if="payment"
        class="flex h-full flex-col"
      >
        <div class="relative">
          <div class="h-20 rounded-t-[var(--radius-xl)] bg-[var(--color-primary-soft)]" />
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            class="absolute right-2 top-2"
            :aria-label="t('actions.close', 'Cerrar')"
            @click="emit('update:open', false)"
          />
          <div class="-mt-10 flex flex-col items-center px-6">
            <div
              class="flex h-20 w-20 items-center justify-center rounded-full bg-surface ring-4 ring-[var(--color-surface)] shadow-token-md"
            >
              <UIcon
                :name="methodIcon(payment.method)"
                class="h-9 w-9 text-[var(--color-primary)]"
              />
            </div>

            <h2 class="mt-3 text-h1 text-default text-center text-pretty">
              {{ patientName(payment.patient) }}
            </h2>

            <!-- The three numbers that answer "what happened to this
                 money": what came in, what went back, what is left. The
                 middle one only exists when there was a refund. -->
            <div class="mt-3 flex flex-wrap items-end justify-center gap-x-6 gap-y-2">
              <div class="text-center">
                <p class="text-caption text-subtle">
                  {{ t('payments.detail.amount') }}
                </p>
                <Money
                  :value="payment.amount"
                  strong
                />
              </div>
              <div
                v-if="refunded > 0"
                class="text-center"
              >
                <p class="text-caption text-subtle">
                  {{ t('payments.detail.refundedTotal') }}
                </p>
                <span class="text-ui text-danger tnum">
                  − {{ formatCurrency(payment.refunded_total) }}
                </span>
              </div>
              <div
                v-if="refunded > 0"
                class="text-center"
              >
                <p class="text-caption text-subtle">
                  {{ t('payments.detail.netAmount') }}
                </p>
                <Money
                  :value="payment.net_amount"
                  strong
                />
              </div>
            </div>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto px-6 pb-2 pt-5">
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:[&>*:nth-child(odd):last-child]:col-span-2">
            <div
              v-for="tile in tiles"
              :key="tile.label"
              class="flex items-start gap-3 rounded-token-lg border border-subtle bg-surface-muted px-4 py-3"
            >
              <UIcon
                :name="tile.icon"
                class="mt-0.5 h-5 w-5 shrink-0 text-subtle"
              />
              <div class="min-w-0">
                <p class="text-caption text-subtle">
                  {{ tile.label }}
                </p>
                <p class="text-ui text-default break-words">
                  {{ tile.value }}
                </p>
              </div>
            </div>
          </div>

          <!-- Where the money was applied. Its own block rather than a
               tile: there can be two lines and each carries an amount. -->
          <div
            v-if="allocations.length"
            class="mt-3 rounded-token-lg border border-subtle bg-surface-muted px-4 py-3"
          >
            <p class="text-caption text-subtle">
              {{ t('payments.detail.allocations') }}
            </p>
            <div
              v-for="a in allocations"
              :key="a.label"
              class="mt-1 flex items-center justify-between gap-4"
            >
              <span class="text-ui text-default">{{ a.label }}</span>
              <span class="text-ui text-default tnum">{{ formatCurrency(a.amount) }}</span>
            </div>
          </div>

          <div
            v-if="payment.notes"
            class="mt-3 rounded-token-lg border border-subtle bg-surface-muted px-4 py-3"
          >
            <p class="text-caption text-subtle">
              {{ t('payments.detail.notes') }}
            </p>
            <p class="mt-1 text-body text-default whitespace-pre-line">
              {{ payment.notes }}
            </p>
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 border-t border-subtle px-6 py-4">
          <UButton
            color="neutral"
            variant="ghost"
            @click="emit('update:open', false)"
          >
            {{ t('actions.close', 'Cerrar') }}
          </UButton>
          <UButton
            v-if="canRefund"
            color="warning"
            variant="soft"
            icon="i-lucide-rotate-ccw"
            @click="emit('refund', payment)"
          >
            {{ t('payments.detail.refund') }}
          </UButton>
        </div>
      </div>
    </template>
  </UModal>
</template>
