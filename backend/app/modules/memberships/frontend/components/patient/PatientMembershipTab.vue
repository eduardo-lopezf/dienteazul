<script setup lang="ts">
/**
 * The "Membresía" tab of the patient record (`patient.detail.tabs`).
 *
 * The patient's plan, whether it is in force, the included services used
 * this membership year and the fees paid. The patient comes from the
 * slot's context, so this module never calls the Patients App (ADR 0041).
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import type { MembershipPlan, PatientMembership } from '../../composables/useMemberships'
import { treatmentLabel } from '../../composables/useMemberships'

const props = defineProps<{ ctx: { patient: PatientExtended } }>()

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { format: money } = useCurrency()
const { forPatient, listPlans, changePlan, cancel } = useMemberships()

const canWrite = computed(() => can(PERMISSIONS.memberships.membershipWrite))

const membership = ref<PatientMembership | null>(null)
const isLoading = ref(true)
const feeOpen = ref(false)
const renewing = ref(false)
const confirmCancel = ref(false)
const planOpen = ref(false)
const plans = ref<MembershipPlan[]>([])
const nextPlanId = ref<string | undefined>(undefined)
const busy = ref(false)

async function load() {
  isLoading.value = true
  try {
    membership.value = await forPatient(props.ctx.patient.id)
  } catch {
    toast.add({ title: t('memberships.loadFailed'), color: 'error' })
  } finally {
    isLoading.value = false
  }
}

watch(() => props.ctx.patient.id, () => load())
onMounted(() => load())

/** An active membership is renewed; none, or a cancelled one, signs up anew. */
const isOpen = computed(() => membership.value?.status === 'active')

function openEnroll() {
  renewing.value = false
  feeOpen.value = true
}

function openRenew() {
  renewing.value = true
  feeOpen.value = true
}

async function openChangePlan() {
  try {
    plans.value = (await listPlans()).filter(p => p.id !== membership.value?.plan_id)
  } catch {
    plans.value = []
  }
  nextPlanId.value = plans.value[0]?.id
  planOpen.value = true
}

async function saveChangePlan() {
  if (!membership.value || !nextPlanId.value) return
  busy.value = true
  try {
    membership.value = await changePlan(membership.value.id, nextPlanId.value)
    toast.add({ title: t('memberships.changePlan.saved'), color: 'success' })
    planOpen.value = false
  } catch {
    toast.add({ title: t('memberships.changePlan.failed'), color: 'error' })
  } finally {
    busy.value = false
  }
}

async function doCancel() {
  if (!membership.value) return
  busy.value = true
  try {
    membership.value = await cancel(membership.value.id)
    toast.add({ title: t('memberships.cancel.done'), color: 'success' })
    confirmCancel.value = false
  } catch {
    toast.add({ title: t('memberships.cancel.failed'), color: 'error' })
  } finally {
    busy.value = false
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale.value, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  })
}

function name(code: string | null | undefined, names: Record<string, string> | null | undefined) {
  return treatmentLabel(locale.value, code, names, t('memberships.unnamedTreatment'))
}

const stateColor = computed(() => {
  switch (membership.value?.state) {
    case 'active': return 'success'
    case 'expired': return 'warning'
    default: return 'neutral'
  }
})

const planOptions = computed(() =>
  plans.value.map(p => ({ value: p.id, label: `${p.name} · ${money(p.fee)} ${t(`memberships.period.per.${p.period}`)}` }))
)
</script>

<template>
  <div data-testid="patient-membership-tab">
    <USkeleton
      v-if="isLoading"
      class="h-32 w-full"
    />

    <div
      v-else-if="!membership"
      class="rounded-token-md border border-default bg-default p-6 text-center"
    >
      <p class="text-subtle m-0">
        {{ t('memberships.none') }}
      </p>
      <UButton
        v-if="canWrite"
        class="mt-3"
        icon="i-lucide-badge-plus"
        data-testid="membership-enroll"
        @click="openEnroll"
      >
        {{ t('memberships.enroll') }}
      </UButton>
    </div>

    <div
      v-else
      class="space-y-4"
    >
      <UCard>
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="flex flex-wrap items-center gap-2 m-0">
              <span class="font-semibold text-default">{{ membership.plan_name }}</span>
              <UBadge
                :color="stateColor"
                variant="subtle"
                size="sm"
                data-testid="membership-state"
              >
                {{ t(`memberships.state.${membership.state}`) }}
              </UBadge>
            </p>
            <p class="text-sm text-muted mt-1 m-0">
              <template v-if="membership.state === 'active'">
                {{ t('memberships.coveredUntil', { date: formatDate(membership.covered_until) }) }}
              </template>
              <template v-else-if="membership.state === 'expired'">
                {{ t('memberships.expiredSince', { date: formatDate(membership.paid_through) }) }}
              </template>
              <template v-else>
                {{ t('memberships.cancelledNote') }}
              </template>
            </p>
            <p class="text-caption text-subtle mt-1 m-0">
              {{ t('memberships.memberSince', { date: formatDate(membership.started_on) }) }}
            </p>
          </div>
          <div
            v-if="canWrite"
            class="flex flex-wrap gap-2"
          >
            <template v-if="isOpen">
              <UButton
                icon="i-lucide-hand-coins"
                data-testid="membership-renew"
                @click="openRenew"
              >
                {{ t('memberships.renew') }}
              </UButton>
              <UButton
                variant="soft"
                icon="i-lucide-repeat"
                @click="openChangePlan"
              >
                {{ t('memberships.changePlan.action') }}
              </UButton>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                data-testid="membership-cancel"
                @click="confirmCancel = true"
              >
                {{ t('memberships.cancel.action') }}
              </UButton>
            </template>
            <UButton
              v-else
              icon="i-lucide-badge-plus"
              @click="openEnroll"
            >
              {{ t('memberships.enrollAgain') }}
            </UButton>
          </div>
        </div>
        <p
          v-if="!membership.payments_available"
          class="text-caption text-subtle mt-3 m-0"
        >
          {{ t('memberships.paymentsOff') }}
        </p>
      </UCard>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <UCard>
          <template #header>
            <p class="font-medium m-0">
              {{ t('memberships.included.title') }}
            </p>
            <p class="text-caption text-subtle m-0">
              {{ t('memberships.included.cycle', { date: formatDate(membership.cycle_start) }) }}
            </p>
          </template>
          <ul
            v-if="membership.included.length"
            class="space-y-2 m-0 p-0 list-none"
            data-testid="membership-included"
          >
            <li
              v-for="item in membership.included"
              :key="item.catalog_item_id"
              class="flex items-center justify-between gap-3 text-sm"
            >
              <span class="min-w-0 truncate">{{ name(item.internal_code, item.names) }}</span>
              <span
                class="shrink-0 tabular-nums"
                :class="item.used >= item.quantity ? 'text-subtle' : 'text-default'"
              >
                {{ t('memberships.included.usage', { used: item.used, quantity: item.quantity }) }}
              </span>
            </li>
          </ul>
          <p
            v-else
            class="text-sm text-subtle m-0"
          >
            {{ t('memberships.included.none') }}
          </p>
        </UCard>

        <UCard>
          <template #header>
            <p class="font-medium m-0">
              {{ t('memberships.discounts.title') }}
            </p>
          </template>
          <ul class="space-y-2 m-0 p-0 list-none text-sm">
            <li
              v-for="item in membership.discounts"
              :key="item.catalog_item_id"
              class="flex items-center justify-between gap-3"
            >
              <span class="min-w-0 truncate">{{ name(item.internal_code, item.names) }}</span>
              <span class="shrink-0 tabular-nums">−{{ Number(item.discount_percent) }} %</span>
            </li>
            <li
              v-if="membership.general_discount_percent && Number(membership.general_discount_percent) > 0"
              class="flex items-center justify-between gap-3 text-muted"
            >
              <span>{{ t('memberships.discounts.general') }}</span>
              <span class="shrink-0 tabular-nums">−{{ Number(membership.general_discount_percent) }} %</span>
            </li>
          </ul>
          <p
            v-if="!membership.discounts.length && !(membership.general_discount_percent && Number(membership.general_discount_percent) > 0)"
            class="text-sm text-subtle m-0"
          >
            {{ t('memberships.discounts.none') }}
          </p>
        </UCard>
      </div>

      <UCard>
        <template #header>
          <p class="font-medium m-0">
            {{ t('memberships.periods.title') }}
          </p>
        </template>
        <ul
          class="divide-y divide-default m-0 p-0 list-none"
          data-testid="membership-periods"
        >
          <li
            v-for="period in membership.periods"
            :key="period.id"
            class="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
          >
            <span>
              {{ formatDate(period.starts_on) }} – {{ formatDate(period.ends_on) }}
              <span class="text-subtle">· {{ period.plan_name }}</span>
            </span>
            <span class="flex items-center gap-2">
              <UBadge
                v-if="period.status === 'refunded'"
                color="neutral"
                variant="outline"
                size="xs"
              >
                {{ t('memberships.periods.refunded') }}
              </UBadge>
              <span class="tabular-nums">{{ money(period.amount) }}</span>
            </span>
          </li>
        </ul>
      </UCard>
    </div>

    <MembershipFeeModal
      v-model:open="feeOpen"
      :patient-id="ctx.patient.id"
      :membership="renewing ? membership : null"
      @saved="(m: PatientMembership) => (membership = m)"
    />

    <UModal
      v-model:open="planOpen"
      :title="t('memberships.changePlan.title')"
      :description="t('memberships.changePlan.hint')"
    >
      <template #body>
        <USelect
          v-if="planOptions.length"
          v-model="nextPlanId"
          class="w-full"
          :items="planOptions"
          value-key="value"
          :aria-label="t('memberships.fee.plan')"
        />
        <p
          v-else
          class="text-sm text-muted m-0"
        >
          {{ t('memberships.changePlan.noOther') }}
        </p>
      </template>
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            @click="planOpen = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            :loading="busy"
            :disabled="!nextPlanId"
            @click="saveChangePlan"
          >
            {{ t('common.save') }}
          </UButton>
        </div>
      </template>
    </UModal>

    <UModal
      v-model:open="confirmCancel"
      :title="t('memberships.cancel.title')"
      :description="t('memberships.cancel.hint', { date: formatDate(membership?.paid_through ?? null) })"
    >
      <template #footer>
        <div class="flex justify-end gap-2 w-full">
          <UButton
            color="neutral"
            variant="ghost"
            @click="confirmCancel = false"
          >
            {{ t('memberships.cancel.keep') }}
          </UButton>
          <UButton
            color="error"
            :loading="busy"
            data-testid="membership-cancel-confirm"
            @click="doCancel"
          >
            {{ t('memberships.cancel.confirm') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
