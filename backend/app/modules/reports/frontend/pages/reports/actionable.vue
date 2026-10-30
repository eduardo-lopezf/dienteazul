<script setup lang="ts">
/**
 * Listas accionables — the queues, not the figures.
 *
 * Every other screen in Productividad answers "how are we doing"; this
 * one answers "who do I call". So a row is a name, a phone and one tap
 * to use it, and the lists deliberately exclude anybody who already has
 * an appointment — a queue that offers a patient who is coming on
 * Thursday stops being read.
 *
 * It carries no period filter on purpose. "Owes and is not coming back"
 * is true today or it is not; a date range would only let somebody work
 * a stale queue.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import BackButton from '~~/app/components/shared/BackButton.vue'
import EmptyState from '~~/app/components/shared/EmptyState.vue'
import {
  useActionableLists,
  type ActionableKey,
  type ActionableRow
} from '../../composables/useActionableLists'

const { t } = useI18n()
const { can } = usePermissions()
const router = useRouter()
const { format: money } = useCurrency()

// This screen reads debts, budgets and the agenda. Without the grant
// there is nothing to show, so leave rather than render an empty shell.
watchEffect(() => {
  if (!can(PERMISSIONS.reports.actionableRead)) void router.replace('/reports')
})

const { state, minimum, months, load, invalidate } = useActionableLists()

const TABS: { key: ActionableKey, icon: string }[] = [
  { key: 'owes_not_booked', icon: 'i-lucide-hand-coins' },
  { key: 'accepted_not_booked', icon: 'i-lucide-file-check' },
  { key: 'no_visit', icon: 'i-lucide-user-x' }
]

const active = ref<ActionableKey>('owes_not_booked')

const tabItems = computed(() =>
  TABS.map(tab => ({
    value: tab.key,
    label: t(`reports.actionable.${tab.key}.tab`),
    icon: tab.icon
  }))
)

const current = computed(() => state[active.value])

onMounted(() => load(active.value))
watch(active, key => load(key))

function reload(key: ActionableKey) {
  invalidate(key)
  void load(key)
}

function call(row: ActionableRow) {
  if (row.phone) window.location.href = `tel:${row.phone}`
}

function whatsapp(row: ActionableRow) {
  if (!row.phone) return
  window.open(`https://wa.me/${row.phone.replace(/\D/g, '')}`, '_blank', 'noopener')
}

/** The figure that put the row on this list, in that list's own words. */
function reason(key: ActionableKey, row: ActionableRow): string {
  if (key === 'no_visit') {
    return t('reports.actionable.no_visit.since', { days: row.days ?? 0 })
  }
  if (key === 'owes_not_booked') {
    return t('reports.actionable.owes_not_booked.since', { days: row.days ?? 0 })
  }
  return row.detail ?? ''
}
</script>

<template>
  <div class="space-y-6">
    <header
      class="sticky top-0 z-10 -mx-4 px-4 py-3 bg-surface border-b border-default flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex items-center gap-4 min-w-0">
        <BackButton to="/reports" />
        <div class="min-w-0">
          <h1 class="text-display text-default truncate">
            {{ t('reports.actionable.title') }}
          </h1>
          <p class="text-caption text-subtle truncate">
            {{ t('reports.actionable.subtitle') }}
          </p>
        </div>
      </div>
      <UButton
        variant="soft"
        color="neutral"
        icon="i-lucide-refresh-cw"
        :loading="current.loading"
        :aria-label="t('common.refresh')"
        @click="reload(active)"
      />
    </header>

    <UTabs
      v-model="active"
      :items="tabItems"
      :ui="{ content: 'overflow-visible' }"
    >
      <template #content>
        <div class="mt-4 space-y-4">
          <!-- Each list's own knob, next to the list it changes. -->
          <div
            v-if="active === 'owes_not_booked'"
            class="flex items-end gap-3"
          >
            <UFormField :label="t('reports.actionable.owes_not_booked.minimum')">
              <UInput
                v-model.number="minimum"
                type="number"
                min="0"
                class="w-36"
              />
            </UFormField>
            <UButton
              variant="soft"
              color="neutral"
              @click="reload('owes_not_booked')"
            >
              {{ t('common.apply') }}
            </UButton>
          </div>

          <div
            v-if="active === 'no_visit'"
            class="flex items-end gap-3"
          >
            <UFormField :label="t('reports.actionable.no_visit.months')">
              <UInput
                v-model.number="months"
                type="number"
                min="1"
                max="60"
                class="w-36"
              />
            </UFormField>
            <UButton
              variant="soft"
              color="neutral"
              @click="reload('no_visit')"
            >
              {{ t('common.apply') }}
            </UButton>
          </div>

          <div
            v-if="current.loading"
            class="space-y-2"
          >
            <USkeleton
              v-for="n in 4"
              :key="n"
              class="h-16 w-full"
            />
          </div>

          <EmptyState
            v-else-if="current.error"
            icon="i-lucide-alert-circle"
            :title="t('reports.actionable.failed')"
          />

          <EmptyState
            v-else-if="!current.data?.rows.length"
            icon="i-lucide-check-circle"
            :title="t(`reports.actionable.${active}.empty`)"
            :description="t('reports.actionable.emptyHint')"
          />

          <template v-else>
            <ul class="space-y-2">
              <li
                v-for="row in current.data.rows"
                :key="row.patient_id"
                class="flex flex-wrap items-center gap-3 rounded-token-lg border border-default bg-surface px-4 py-3"
              >
                <NuxtLink
                  :to="`/patients/${row.patient_id}`"
                  class="min-w-0 flex-1"
                >
                  <p class="text-ui text-default truncate">
                    {{ row.patient_name }}
                  </p>
                  <p class="text-caption text-subtle truncate">
                    {{ reason(active, row) }}
                  </p>
                </NuxtLink>

                <span
                  v-if="row.amount"
                  class="text-ui text-default font-semibold tnum"
                >
                  {{ money(Number(row.amount)) }}
                </span>

                <div class="flex items-center gap-1">
                  <UButton
                    v-if="row.phone"
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-phone"
                    size="sm"
                    :title="row.phone"
                    :aria-label="t('reports.actionable.call')"
                    @click="call(row)"
                  />
                  <UButton
                    v-if="row.phone"
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-message-circle"
                    size="sm"
                    :aria-label="t('reports.actionable.whatsapp')"
                    @click="whatsapp(row)"
                  />
                </div>
              </li>
            </ul>

            <!-- Say the queue was cut rather than let somebody believe
                 they finished it. -->
            <p
              v-if="current.data.truncated"
              class="text-caption text-subtle"
            >
              {{ t('reports.actionable.truncated', { count: current.data.rows.length }) }}
            </p>
          </template>
        </div>
      </template>
    </UTabs>
  </div>
</template>
