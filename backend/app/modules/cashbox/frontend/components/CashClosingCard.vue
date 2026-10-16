<script setup lang="ts">
/**
 * The arqueo: count the drawer, and see what that means afterwards.
 *
 * **The expected figure is not on screen until the count is entered.** This
 * is the whole design of the card and it is worth being stubborn about:
 * show someone "you should have 4.350" and then ask them to count, and they
 * type 4.350. The difference comes out zero every day and a year of counts
 * says nothing at all. So the workings are visible — what came in, what was
 * refunded, what moved — and the total they add up to is not.
 *
 * Once the day is counted the card flips to reading it back, where there is
 * nothing left to bias and the expected figure is the point.
 */
import type { CashClosing, CashPosition } from '../composables/useCashbox'
import { PERMISSIONS } from '~~/app/config/permissions'
import { formatInstant } from '~~/app/utils/date'

const props = defineProps<{
  position: CashPosition | null
  businessDate: string
}>()

const emit = defineEmits<{ changed: [] }>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const { currentClinic } = useClinic()
const { format: money } = useCurrency()
const toast = useToast()
// Collections are integrated, not required (ADR 0037): with them off the
// count is the till's own movements and the float.
const { active, isActive } = useModules()
const paymentsAvailable = computed(() => active.value === null || isActive('payments'))
const { closeDay, reopenClosing } = useCashClosings()

const closing = computed<CashClosing | null>(() => props.position?.closing ?? null)
const canClose = computed(() => can(PERMISSIONS.cashbox.closingWrite))
const canReopen = computed(() => can(PERMISSIONS.cashbox.closingReopen))

const counting = ref(false)
const saving = ref(false)
const countedCash = ref('')
const openingFloat = ref('')
const closingFloat = ref('')
const notes = ref('')

/**
 * Only once a number has been typed does the arithmetic appear.
 *
 * Goes through `String()` rather than calling `.trim()` on the ref: a
 * `UInput` with `type="number"` types its model as `string` but hands back
 * whatever the browser gives it, and `.trim()` on a number throws inside a
 * computed — where it fails silently and the reveal simply never fires.
 */
const hasCount = computed(() => {
  const raw = String(countedCash.value ?? '').trim()
  return raw !== '' && !Number.isNaN(Number(raw))
})

const expected = computed(() => {
  if (!props.position) return 0
  const p = props.position
  return (
    Number(openingFloat.value || 0)
    + Number(p.cash_collected)
    - Number(p.cash_refunded)
    + Number(p.movements_in)
    - Number(p.movements_out)
  )
})

const difference = computed(() => Number(countedCash.value || 0) - expected.value)
const mismatched = computed(() => hasCount.value && Math.abs(difference.value) > 0.005)

const blocked = computed<string | null>(() => {
  if (!hasCount.value) return t('cashbox.closing.blocked.count')
  if (mismatched.value && !notes.value.trim()) return t('cashbox.closing.blocked.notes')
  if (Number(closingFloat.value || 0) > Number(countedCash.value || 0)) {
    return t('cashbox.closing.blocked.float')
  }
  return null
})

function startCounting() {
  counting.value = true
  countedCash.value = ''
  notes.value = ''
  // Suggested, not imposed: the person who opened the drawer is the one who
  // knows what was in it, and the chain from yesterday is only a default.
  openingFloat.value = props.position?.opening_float ?? '0'
  closingFloat.value = props.position?.opening_float ?? '0'
}

async function submit() {
  if (blocked.value || saving.value) return
  saving.value = true
  try {
    await closeDay({
      business_date: props.businessDate,
      counted_cash: String(countedCash.value),
      opening_float: String(openingFloat.value || 0),
      closing_float: String(closingFloat.value || 0),
      notes: notes.value.trim() || null
    })
    counting.value = false
    emit('changed')
  } catch {
    toast.add({ title: t('cashbox.closing.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

const showReopen = ref(false)
const reopenReason = ref('')

async function submitReopen() {
  if (!closing.value || !reopenReason.value.trim()) return
  try {
    await reopenClosing(closing.value.id, reopenReason.value.trim())
    showReopen.value = false
    reopenReason.value = ''
    emit('changed')
  } catch {
    toast.add({ title: t('cashbox.closing.reopenFailed'), color: 'error' })
  }
}

/**
 * When a count was signed, in the clinic's calendar and not the reader's.
 *
 * A Madrid clinic read from Mexico would otherwise show the day before, and
 * the count would contradict the receipt the patient is holding.
 */
function instant(value: string | null | undefined): string {
  if (!value) return ''
  // Field options, not `dateStyle`/`timeStyle`: `formatInstant` goes through
  // `toLocaleDateString`, which throws `Invalid option : timeStyle` — and a
  // throw inside a template unmounts the card rather than showing an error.
  // Same option shape `PendingChargesCard` uses.
  return formatInstant(
    value,
    locale.value,
    { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' },
    currentClinic.value?.timezone
  )
}
</script>

<template>
  <UCard
    v-if="position"
    class="closing-card"
  >
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon
          :name="closing ? 'i-lucide-lock' : 'i-lucide-calculator'"
          class="w-5 h-5"
        />
        <span class="font-medium">{{ t('cashbox.closing.title') }}</span>
        <UBadge
          v-if="closing"
          color="neutral"
          variant="subtle"
          :label="t('cashbox.closing.done')"
        />
      </div>
    </template>

    <!-- Already counted: read it back. -->
    <div
      v-if="closing"
      class="closed-view"
    >
      <dl class="closed-grid">
        <div>
          <dt>{{ t('cashbox.closing.openingFloat') }}</dt>
          <dd>{{ money(closing.opening_float) }}</dd>
        </div>
        <div>
          <dt>{{ t('cashbox.closing.expected') }}</dt>
          <dd>{{ money(closing.expected_cash) }}</dd>
        </div>
        <div>
          <dt>{{ t('cashbox.closing.counted') }}</dt>
          <dd>{{ money(closing.counted_cash) }}</dd>
        </div>
        <div>
          <dt>{{ t('cashbox.closing.difference') }}</dt>
          <dd :class="Number(closing.difference) === 0 ? 'diff-ok' : 'diff-off'">
            {{ money(closing.difference) }}
          </dd>
        </div>
      </dl>

      <p
        v-if="closing.notes"
        class="closed-notes"
      >
        {{ closing.notes }}
      </p>

      <p class="closed-meta">
        {{ t('cashbox.closing.closedBy', {
          who: closing.closer ? `${closing.closer.first_name} ${closing.closer.last_name}` : '',
          when: instant(closing.closed_at)
        }) }}
        · {{ t('cashbox.closing.leftForTomorrow', { amount: money(closing.closing_float) }) }}
      </p>

      <UButton
        v-if="canReopen"
        color="warning"
        variant="soft"
        size="xs"
        icon="i-lucide-undo-2"
        @click="showReopen = true"
      >
        {{ t('cashbox.closing.reopen') }}
      </UButton>
    </div>

    <!-- Not counted yet. -->
    <div v-else>
      <!-- The workings, always. The total they add up to, never before the
           count — see the component docstring. -->
      <dl class="workings">
        <div>
          <dt>{{ t('cashbox.closing.openingFloat') }}</dt>
          <dd>{{ money(position.opening_float) }}</dd>
        </div>
        <div v-if="paymentsAvailable">
          <dt>{{ t('cashbox.closing.cashCollected') }}</dt>
          <dd>{{ money(position.cash_collected) }}</dd>
        </div>
        <div v-if="paymentsAvailable">
          <dt>{{ t('cashbox.closing.cashRefunded') }}</dt>
          <!-- No sign on a zero: "−0,00" reads as a negative amount. -->
          <dd>{{ Number(position.cash_refunded) ? '−' : '' }}{{ money(position.cash_refunded) }}</dd>
        </div>
        <div>
          <dt>{{ t('cashbox.totals.in') }}</dt>
          <dd>{{ money(position.movements_in) }}</dd>
        </div>
        <div>
          <dt>{{ t('cashbox.totals.out') }}</dt>
          <dd>{{ Number(position.movements_out) ? '−' : '' }}{{ money(position.movements_out) }}</dd>
        </div>
      </dl>

      <p
        v-if="!paymentsAvailable"
        class="methods-note"
        data-testid="cashbox-payments-off"
      >
        {{ t('cashbox.paymentsOff') }}
      </p>
      <p
        v-if="position.collected_by_method.length"
        class="methods-note"
      >
        {{ t('cashbox.closing.otherChannels') }}
        <span
          v-for="m in position.collected_by_method.filter(x => x.method !== 'cash')"
          :key="m.method"
          class="method-chip"
        >
          {{ t(`invoice.payments.methods.${m.method}`) }} {{ money(m.amount) }}
        </span>
      </p>

      <UButton
        v-if="!counting && canClose"
        class="mt-3"
        icon="i-lucide-calculator"
        @click="startCounting"
      >
        {{ t('cashbox.closing.start') }}
      </UButton>

      <div
        v-if="counting"
        class="count-form"
      >
        <UFormField
          :label="t('cashbox.closing.openingFloat')"
          :description="t('cashbox.closing.openingFloatHint')"
        >
          <UInput
            v-model="openingFloat"
            class="w-full"
            type="number"
            step="0.01"
            min="0"
          />
        </UFormField>

        <UFormField
          :label="t('cashbox.closing.counted')"
          :description="t('cashbox.closing.countedHint')"
        >
          <UInput
            v-model="countedCash"
            class="w-full"
            type="number"
            step="0.01"
            min="0"
            autofocus
            :placeholder="t('cashbox.closing.countedPlaceholder')"
          />
        </UFormField>

        <!-- Revealed only now. -->
        <div
          v-if="hasCount"
          class="reveal"
        >
          <div>
            <span class="reveal-label">{{ t('cashbox.closing.expected') }}</span>
            <span class="reveal-value">{{ money(expected) }}</span>
          </div>
          <div>
            <span class="reveal-label">{{ t('cashbox.closing.difference') }}</span>
            <span
              class="reveal-value"
              :class="mismatched ? 'diff-off' : 'diff-ok'"
            >{{ money(difference) }}</span>
          </div>
        </div>

        <UFormField
          v-if="mismatched"
          :label="t('cashbox.closing.notes')"
          :description="t('cashbox.closing.notesHint')"
        >
          <UInput
            v-model="notes"
            class="w-full"
            :placeholder="t('cashbox.closing.notesPlaceholder')"
          />
        </UFormField>

        <UFormField
          :label="t('cashbox.closing.closingFloat')"
          :description="t('cashbox.closing.closingFloatHint')"
        >
          <UInput
            v-model="closingFloat"
            class="w-full"
            type="number"
            step="0.01"
            min="0"
          />
        </UFormField>

        <div class="flex justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            @click="counting = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            :disabled="!!blocked"
            :loading="saving"
            @click="submit"
          >
            {{ t('cashbox.closing.confirm') }}
          </UButton>
        </div>
        <p
          v-if="blocked"
          class="blocked-note"
        >
          {{ blocked }}
        </p>
      </div>
    </div>

    <UModal
      v-model:open="showReopen"
      :title="t('cashbox.closing.reopenTitle')"
    >
      <template #body>
        <p class="reopen-warning">
          {{ t('cashbox.closing.reopenWarning') }}
        </p>
        <UFormField :label="t('cashbox.closing.reopenReason')">
          <UInput
            v-model="reopenReason"
            class="w-full"
            :placeholder="t('cashbox.closing.reopenReasonPlaceholder')"
          />
        </UFormField>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            @click="showReopen = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            color="warning"
            :disabled="!reopenReason.trim()"
            @click="submitReopen"
          >
            {{ t('cashbox.closing.reopen') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </UCard>
</template>

<style scoped>
.closing-card {
  text-align: left;
}

.workings,
.closed-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin: 0;
}

.workings dt,
.closed-grid dt {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted, #6B7280);
}

.workings dd,
.closed-grid dd {
  margin: 2px 0 0;
  font-size: 15px;
  font-variant-numeric: tabular-nums;
}

.diff-ok {
  color: var(--ui-success, #059669);
}

.diff-off {
  color: var(--ui-warning, #B45309);
  font-weight: 600;
}

.methods-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 12px 0 0;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.method-chip {
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  font-variant-numeric: tabular-nums;
}

.count-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--color-border);
}

.reveal {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  padding: 10px 12px;
  border-radius: var(--radius-md, 8px);
  background: var(--color-bg-subtle, #F9FAFB);
}

.reveal-label {
  display: block;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-muted, #6B7280);
}

.reveal-value {
  font-size: 18px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.blocked-note {
  margin: 0;
  text-align: right;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.closed-view {
  display: flex;
  flex-direction: column;
  gap: 10px;
  /* `flex-start` is for the reopen button, which should hug its label.
     Without stretching the grid back the whole read-back collapses into a
     single column, because a flex item shrinks to its content. */
  align-items: flex-start;
}

.closed-view .closed-grid {
  align-self: stretch;
}

.closed-notes {
  margin: 0;
  font-size: 12px;
}

.closed-meta {
  margin: 0;
  font-size: 11px;
  color: var(--color-text-muted, #6B7280);
}

.reopen-warning {
  margin: 0 0 12px;
  font-size: 13px;
}
</style>
