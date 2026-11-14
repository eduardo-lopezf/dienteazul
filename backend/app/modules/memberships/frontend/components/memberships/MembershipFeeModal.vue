<script setup lang="ts">
/**
 * Collect a membership fee: the first, signing the patient up to a plan,
 * or the next one. The fee is recorded as a payment of the patient in the
 * Budgets and payments App when that App is on.
 */
import type {
  MembershipPlan,
  PatientMembership,
  PaymentMethod
} from '../../composables/useMemberships'
import { PAYMENT_METHODS } from '../../composables/useMemberships'

const props = defineProps<{
  open: boolean
  patientId: string
  /** The membership to renew; none to sign the patient up. */
  membership: PatientMembership | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': [membership: PatientMembership]
}>()

const { t } = useI18n()
const toast = useToast()
const { format: money } = useCurrency()
const { listPlans, enroll, renew } = useMemberships()

function isoToday(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

const plans = ref<MembershipPlan[]>([])
const planId = ref<string | undefined>(undefined)
const startsOn = ref(isoToday())
const method = ref<PaymentMethod>('cash')
const paymentDate = ref(isoToday())
const reference = ref('')
const saving = ref(false)

const isRenewal = computed(() => props.membership !== null)
const plan = computed(() =>
  plans.value.find(p => p.id === (isRenewal.value ? props.membership!.plan_id : planId.value))
)

const planOptions = computed(() =>
  plans.value.map(p => ({
    value: p.id,
    label: `${p.name} · ${money(p.fee)} ${t(`memberships.period.per.${p.period}`)}`
  }))
)
const methodOptions = computed(() =>
  PAYMENT_METHODS.map(m => ({ value: m, label: t(`memberships.method.${m}`) }))
)

watch(() => props.open, async (open) => {
  if (!open) return
  startsOn.value = isoToday()
  paymentDate.value = isoToday()
  reference.value = ''
  method.value = 'cash'
  try {
    plans.value = await listPlans()
  } catch {
    plans.value = []
  }
  if (!isRenewal.value) planId.value = plans.value[0]?.id
}, { immediate: true })

const valid = computed(() => !!plan.value && !!paymentDate.value && (isRenewal.value || !!startsOn.value))

async function save() {
  if (!valid.value) return
  saving.value = true
  const payment = { method: method.value, payment_date: paymentDate.value, reference: reference.value.trim() || null }
  try {
    const saved = isRenewal.value
      ? await renew(props.membership!.id, payment)
      : await enroll(props.patientId, { plan_id: planId.value!, starts_on: startsOn.value, payment })
    toast.add({ title: t(isRenewal.value ? 'memberships.fee.renewed' : 'memberships.fee.enrolled'), color: 'success' })
    emit('saved', saved)
    emit('update:open', false)
  } catch (err: unknown) {
    const e = err as { data?: { message?: string } }
    toast.add({ title: t('memberships.fee.failed'), description: e?.data?.message, color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="isRenewal ? t('memberships.fee.renewTitle') : t('memberships.fee.enrollTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div
        class="flex flex-col gap-4"
        data-testid="membership-fee-form"
      >
        <p
          v-if="!isRenewal && plans.length === 0"
          class="text-sm text-muted m-0"
        >
          {{ t('memberships.fee.noPlans') }}
        </p>

        <UFormField
          v-if="!isRenewal"
          :label="t('memberships.fee.plan')"
          required
        >
          <USelect
            v-model="planId"
            class="w-full"
            :items="planOptions"
            value-key="value"
            :aria-label="t('memberships.fee.plan')"
            data-testid="membership-fee-plan"
          />
        </UFormField>
        <p
          v-else-if="plan"
          class="text-sm text-default m-0"
        >
          {{ plan.name }} · {{ money(plan.fee) }} {{ t(`memberships.period.per.${plan.period}`) }}
        </p>
        <p
          v-else
          class="text-sm text-muted m-0"
        >
          {{ t('memberships.fee.planArchived') }}
        </p>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <UFormField
            v-if="!isRenewal"
            :label="t('memberships.fee.startsOn')"
            required
          >
            <UInput
              v-model="startsOn"
              type="date"
              class="w-full"
            />
          </UFormField>
          <UFormField
            :label="t('memberships.fee.paymentDate')"
            required
          >
            <UInput
              v-model="paymentDate"
              type="date"
              class="w-full"
            />
          </UFormField>
          <UFormField :label="t('memberships.fee.method')">
            <USelect
              v-model="method"
              class="w-full"
              :items="methodOptions"
              value-key="value"
              :aria-label="t('memberships.fee.method')"
            />
          </UFormField>
          <UFormField :label="t('memberships.fee.reference')">
            <UInput
              v-model="reference"
              class="w-full"
              maxlength="100"
            />
          </UFormField>
        </div>

        <p class="text-caption text-subtle m-0">
          {{ isRenewal ? t('memberships.fee.renewHint') : t('memberships.fee.enrollHint') }}
        </p>
      </div>
    </template>
    <template #footer>
      <div class="flex justify-end gap-2 w-full">
        <UButton
          color="neutral"
          variant="ghost"
          @click="emit('update:open', false)"
        >
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          :loading="saving"
          :disabled="!valid"
          data-testid="membership-fee-save"
          @click="save"
        >
          {{ plan ? t('memberships.fee.collect', { amount: money(plan.fee) }) : t('memberships.fee.collectNone') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
