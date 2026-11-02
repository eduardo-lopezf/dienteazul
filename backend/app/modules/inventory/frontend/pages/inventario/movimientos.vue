<script setup lang="ts">
/**
 * Movimientos — the ledger, whole.
 *
 * The article history slideover answers "why is *this* figure what it
 * is". This answers the questions that span articles: what came in last
 * week, what was thrown away this month, every adjustment anybody has
 * posted. It is the same rows either way — `inv_movements` is the truth
 * about stock (ADR 0065) — read with different filters.
 *
 * Paginated, unlike Existencias: the ledger only grows, and a clinic
 * that has been counting for a year has tens of thousands of lines.
 */
import type { InventoryItem, InventoryLocation, InventoryMovement, MovementReason } from '../../composables/useInventory'
import { quantity } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

/** Sentinel for "any": Reka UI reserves the empty string. */
const ANY = '__any__'

const PAGE_SIZE = 50

const REASONS: MovementReason[] = [
  'purchase_receipt',
  'consumption',
  'transfer',
  'adjustment',
  'expiry_write_off',
  'return'
]

const { t, locale } = useI18n()
const { can } = usePermissions()
const { movements, items: listItems, locations: listLocations } = useInventory()

if (!can(PERMISSIONS.inventory.stockRead)) {
  await navigateTo('/inventario')
}

const itemId = ref<string>(ANY)
const locationId = ref<string>(ANY)
const reason = ref<MovementReason | typeof ANY>(ANY)
const dateFrom = ref('')
const dateTo = ref('')
const page = ref(1)

const rows = ref<InventoryMovement[]>([])
const total = ref(0)
const items = ref<InventoryItem[]>([])
const locations = ref<InventoryLocation[]>([])
const isLoading = ref(true)

const itemOptions = computed(() => [
  { value: ANY, label: t('inventory.filters.allItems') },
  ...items.value.map(item => ({ value: item.id, label: `${item.code} · ${item.name}` }))
])

const locationOptions = computed(() => [
  { value: ANY, label: t('inventory.filters.allLocations') },
  ...locations.value.map(location => ({ value: location.id, label: location.name }))
])

const reasonOptions = computed(() => [
  { value: ANY, label: t('inventory.filters.allReasons') },
  ...REASONS.map(value => ({ value, label: t(`inventory.reasons.${value}`) }))
])

const lastPage = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

async function load() {
  isLoading.value = true
  try {
    const response = await movements({
      item_id: itemId.value === ANY ? undefined : itemId.value,
      location_id: locationId.value === ANY ? undefined : locationId.value,
      reason: reason.value === ANY ? undefined : reason.value,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
      page: page.value,
      page_size: PAGE_SIZE
    })
    rows.value = response.data
    total.value = response.total
  } finally {
    isLoading.value = false
  }
}

function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString(locale.value, {
    day: '2-digit',
    month: 'short',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function who(movement: InventoryMovement): string {
  const user = movement.performed_by_user
  return user ? `${user.first_name} ${user.last_name}` : t('inventory.ledger.automatic')
}

// Any filter change restarts the paging: page 3 of the old result set is
// not page 3 of the new one.
watch([itemId, locationId, reason, dateFrom, dateTo], () => {
  page.value = 1
  load()
})
watch(page, () => load())

onMounted(async () => {
  const [itemsResponse, locationsResponse] = await Promise.all([listItems(), listLocations()])
  items.value = itemsResponse.data
  locations.value = locationsResponse.data
  await load()
})
</script>

<template>
  <UContainer class="py-6">
    <div class="mb-6">
      <UButton
        variant="ghost"
        icon="i-lucide-arrow-left"
        :label="t('inventory.stock')"
        to="/inventario"
      />
      <h1 class="mt-2 text-xl font-semibold">
        {{ t('inventory.ledger.title') }}
      </h1>
      <p class="text-sm text-subtle">
        {{ t('inventory.ledger.subtitle') }}
      </p>
    </div>

    <div class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <USelect
        v-model="itemId"
        :items="itemOptions"
        value-key="value"
        :aria-label="t('inventory.filters.allItems')"
      />
      <USelect
        v-model="locationId"
        :items="locationOptions"
        value-key="value"
        :aria-label="t('inventory.filters.allLocations')"
      />
      <USelect
        v-model="reason"
        :items="reasonOptions"
        value-key="value"
        :aria-label="t('inventory.filters.allReasons')"
      />
      <UInput
        v-model="dateFrom"
        type="date"
        :aria-label="t('inventory.ledger.from')"
      />
      <UInput
        v-model="dateTo"
        type="date"
        :aria-label="t('inventory.ledger.to')"
      />
    </div>

    <USkeleton
      v-if="isLoading"
      class="h-64 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('inventory.ledger.empty') }}
    </p>

    <template v-else>
      <div class="overflow-x-auto rounded-token-md border border-default">
        <table class="w-full text-sm">
          <thead class="bg-elevated text-left text-xs text-subtle">
            <tr>
              <th class="p-3">
                {{ t('inventory.ledger.when') }}
              </th>
              <th class="p-3">
                {{ t('inventory.form.item') }}
              </th>
              <th class="p-3">
                {{ t('inventory.form.location') }}
              </th>
              <th class="p-3">
                {{ t('inventory.lot') }}
              </th>
              <th class="p-3 text-right">
                {{ t('inventory.ledger.amount') }}
              </th>
              <th class="p-3">
                {{ t('inventory.form.reason') }}
              </th>
              <th class="p-3">
                {{ t('inventory.ledger.who') }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-default">
            <tr
              v-for="movement in rows"
              :key="movement.id"
              class="bg-default"
            >
              <td class="p-3 whitespace-nowrap text-xs">
                {{ formatMoment(movement.created_at) }}
              </td>
              <td class="p-3 font-medium">
                {{ movement.item_name }}
              </td>
              <td class="p-3">
                {{ movement.location_name }}
              </td>
              <td class="p-3">
                <span v-if="movement.lot_code">{{ movement.lot_code }}</span>
                <span
                  v-else
                  class="text-subtle"
                >—</span>
              </td>
              <td
                class="p-3 text-right font-semibold tabular-nums"
                :class="quantity(movement.quantity_base) > 0 ? 'text-success' : 'text-error'"
              >
                {{ quantity(movement.quantity_base) > 0 ? '+' : ''
                }}{{ quantity(movement.quantity_base) }}
              </td>
              <td class="p-3">
                <p>{{ t(`inventory.reasons.${movement.reason}`) }}</p>
                <p
                  v-if="movement.note"
                  class="text-xs text-subtle"
                >
                  {{ movement.note }}
                </p>
              </td>
              <td class="p-3 text-xs">
                {{ who(movement) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="mt-4 flex items-center justify-between gap-3">
        <p class="text-sm text-subtle">
          {{ t('inventory.ledger.count', { total }) }}
        </p>
        <div class="flex items-center gap-2">
          <UButton
            variant="ghost"
            icon="i-lucide-chevron-left"
            :disabled="page <= 1"
            :aria-label="t('inventory.ledger.previous')"
            @click="page -= 1"
          />
          <span class="text-sm tabular-nums">{{ page }} / {{ lastPage }}</span>
          <UButton
            variant="ghost"
            icon="i-lucide-chevron-right"
            :disabled="page >= lastPage"
            :aria-label="t('inventory.ledger.next')"
            @click="page += 1"
          />
        </div>
      </div>
    </template>
  </UContainer>
</template>
