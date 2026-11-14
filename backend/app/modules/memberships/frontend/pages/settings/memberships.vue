<script setup lang="ts">
/**
 * Membership plans (Settings → Apps → Pacientes → Planes de membresía):
 * what the clinic offers, for a fee per month or per year. Archived, never
 * deleted — memberships point at them.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { MembershipPlan } from '../../composables/useMemberships'
import { treatmentLabel } from '../../composables/useMemberships'

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { format: money } = useCurrency()
const { listPlans, setPlanArchived } = useMemberships()

const canRead = computed(() => can(PERMISSIONS.memberships.planRead))
const canWrite = computed(() => can(PERMISSIONS.memberships.planWrite))

const plans = ref<MembershipPlan[]>([])
const loaded = ref(false)
const showArchived = ref(false)
const modalOpen = ref(false)
const editing = ref<MembershipPlan | null>(null)

async function load() {
  try {
    plans.value = await listPlans(showArchived.value)
  } catch {
    toast.add({ title: t('memberships.plans.loadFailed'), color: 'error' })
  } finally {
    loaded.value = true
  }
}

watch(canRead, (ok) => {
  if (ok && import.meta.client) load()
}, { immediate: true })
watch(showArchived, () => load())

function openNew() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(plan: MembershipPlan) {
  editing.value = plan
  modalOpen.value = true
}

async function toggleArchived(plan: MembershipPlan) {
  try {
    await setPlanArchived(plan.id, plan.status === 'active')
    await load()
  } catch {
    toast.add({ title: t('memberships.plans.saveFailed'), color: 'error' })
  }
}

function benefitLine(plan: MembershipPlan): string[] {
  return plan.benefits.map((b) => {
    const name = treatmentLabel(locale.value, b.internal_code, b.names, t('memberships.unnamedTreatment'))
    return b.kind === 'included'
      ? t('memberships.benefit.includedLine', { quantity: b.quantity, treatment: name })
      : t('memberships.benefit.discountLine', { percent: Number(b.discount_percent), treatment: name })
  })
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <UButton
        to="/settings/apps/patients"
        variant="ghost"
        size="sm"
        icon="i-lucide-arrow-left"
      >
        {{ t('memberships.plans.back') }}
      </UButton>
    </div>

    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-display text-default flex items-center gap-2">
          <UIcon
            name="i-lucide-badge-percent"
            class="h-6 w-6 text-[var(--ui-primary)]"
          />
          {{ t('memberships.plans.title') }}
        </h1>
        <p class="text-muted mt-1">
          {{ t('memberships.plans.intro') }}
        </p>
      </div>
      <UButton
        v-if="canWrite"
        icon="i-lucide-plus"
        data-testid="membership-plan-new"
        @click="openNew"
      >
        {{ t('memberships.plans.new') }}
      </UButton>
    </div>

    <div
      v-if="!canRead"
      class="rounded-md border border-default p-6 text-sm text-muted"
    >
      {{ t('common.forbidden', 'Acceso denegado') }}
    </div>

    <ClientOnly v-else>
      <USwitch
        v-model="showArchived"
        :label="t('memberships.plans.showArchived')"
      />

      <div
        v-if="!loaded"
        class="space-y-3 mt-4"
      >
        <USkeleton
          v-for="i in 3"
          :key="i"
          class="h-20 w-full"
        />
      </div>

      <p
        v-else-if="plans.length === 0"
        class="mt-4 rounded-token-md border border-default bg-default p-6 text-center text-subtle"
      >
        {{ t('memberships.plans.empty') }}
      </p>

      <ul
        v-else
        class="mt-4 space-y-3"
        data-testid="membership-plans"
      >
        <li
          v-for="plan in plans"
          :key="plan.id"
          class="rounded-[var(--radius-lg)] p-4 ring-1 ring-[var(--color-border)]"
          :class="plan.status === 'active' ? 'bg-surface' : 'bg-elevated'"
          :data-testid="`membership-plan-${plan.id}`"
        >
          <div class="flex flex-wrap items-start gap-3">
            <div class="min-w-0 flex-1">
              <p class="flex flex-wrap items-center gap-2">
                <span class="font-medium text-default">{{ plan.name }}</span>
                <UBadge
                  v-if="plan.status === 'archived'"
                  color="neutral"
                  variant="outline"
                  size="xs"
                >
                  {{ t('memberships.plans.archived') }}
                </UBadge>
              </p>
              <p class="text-sm text-default mt-0.5">
                {{ money(plan.fee) }} {{ t(`memberships.period.per.${plan.period}`) }}
                <template v-if="plan.general_discount_percent && Number(plan.general_discount_percent) > 0">
                  · {{ t('memberships.plans.generalLine', { percent: Number(plan.general_discount_percent) }) }}
                </template>
              </p>
              <ul
                v-if="plan.benefits.length"
                class="mt-1 text-sm text-muted list-disc pl-5"
              >
                <li
                  v-for="line in benefitLine(plan)"
                  :key="line"
                >
                  {{ line }}
                </li>
              </ul>
              <p
                v-if="plan.description"
                class="text-caption text-subtle mt-1"
              >
                {{ plan.description }}
              </p>
            </div>
            <div
              v-if="canWrite"
              class="flex gap-2"
            >
              <UButton
                v-if="plan.status === 'active'"
                size="sm"
                variant="soft"
                icon="i-lucide-pencil"
                @click="openEdit(plan)"
              >
                {{ t('common.edit') }}
              </UButton>
              <UButton
                size="sm"
                color="neutral"
                variant="ghost"
                :icon="plan.status === 'active' ? 'i-lucide-archive' : 'i-lucide-archive-restore'"
                @click="toggleArchived(plan)"
              >
                {{ plan.status === 'active' ? t('memberships.plans.archive') : t('memberships.plans.restore') }}
              </UButton>
            </div>
          </div>
        </li>
      </ul>

      <MembershipPlanModal
        v-model:open="modalOpen"
        :plan="editing"
        @saved="load"
      />
    </ClientOnly>
  </div>
</template>
