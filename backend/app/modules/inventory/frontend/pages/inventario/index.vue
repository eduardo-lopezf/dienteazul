<script setup lang="ts">
/**
 * Existencias — the working screen of the inventory.
 *
 * One row per article, location and lot, because that is what the
 * snapshot is keyed by and what somebody standing in front of a cabinet
 * needs to see. The article's total across every location travels with
 * each row: a reorder decision taken from one shelf buys material the
 * clinic already has.
 *
 * No `data-dense` here. It is a debt marker for grids that cannot give a
 * finger 44 px — a time grid, a tooth chart — and a table of stock rows
 * can, so it does. This screen is read standing up, on a tablet, often
 * with gloves on.
 */
import type { InventoryItem, InventoryLocation, PostableReason, StockLine } from '../../composables/useInventory'
import { quantity } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t } = useI18n()
const { can } = usePermissions()
const { stock, alerts, items: listItems, locations: listLocations } = useInventory()

if (!can(PERMISSIONS.inventory.stockRead)) {
  await navigateTo('/')
}

/** Same window the backend's alerts use by default. */
const EXPIRY_SOON = 60

/** Sentinel for "any": Reka UI reserves the empty string. */
const ANY = '__any__'

const search = ref('')
const locationId = ref<string>(ANY)
const onlyLow = ref(false)
const onlyExpiring = ref(false)

const lines = ref<StockLine[]>([])
const items = ref<InventoryItem[]>([])
const locations = ref<InventoryLocation[]>([])
const counts = ref({ low: 0, expiring: 0, expired: 0 })
const isLoading = ref(true)

const itemModalOpen = ref(false)
const movementModalOpen = ref(false)
const movementReason = ref<PostableReason>('purchase_receipt')
const movementItemId = ref<string | null>(null)
const historyOpen = ref(false)
const historyLine = ref<StockLine | null>(null)

const canWriteStock = computed(() => can(PERMISSIONS.inventory.stockWrite))
const canWriteItems = computed(() => can(PERMISSIONS.inventory.itemsWrite))
// Counting posts adjustments, so it is offered only to whoever may make
// the system agree with the shelf.
const canAdjust = computed(() => can(PERMISSIONS.inventory.stockAdjust))
// Traces are patient data, so the way in is offered only to whoever
// may read them.
const canReadImplants = computed(() => can(PERMISSIONS.inventory.implantsRead))

const locationOptions = computed(() => [
  { value: ANY, label: t('inventory.filters.allLocations') },
  ...locations.value.map(location => ({ value: location.id, label: location.name }))
])

const visibleLines = computed(() =>
  lines.value.filter((line) => {
    if (onlyLow.value && !line.is_low) return false
    if (onlyExpiring.value && (line.days_to_expiry === null || line.days_to_expiry > EXPIRY_SOON)) {
      return false
    }
    return true
  })
)

async function load() {
  isLoading.value = true
  try {
    const [stockResponse, alertsResponse] = await Promise.all([
      stock({
        search: search.value || undefined,
        location_id: locationId.value === ANY ? undefined : locationId.value
      }),
      alerts()
    ])
    lines.value = stockResponse.data
    counts.value = {
      low: alertsResponse.data.low_stock.length,
      expiring: alertsResponse.data.expiring.length,
      expired: alertsResponse.data.expired.length
    }
  } finally {
    isLoading.value = false
  }
}

async function loadReferences() {
  const [itemsResponse, locationsResponse] = await Promise.all([listItems(), listLocations()])
  items.value = itemsResponse.data
  locations.value = locationsResponse.data
}

function openMovement(reason: PostableReason, itemId: string | null = null) {
  movementReason.value = reason
  movementItemId.value = itemId
  movementModalOpen.value = true
}

function openHistory(line: StockLine) {
  historyLine.value = line
  historyOpen.value = true
}

async function afterChange() {
  await Promise.all([load(), loadReferences()])
}

watch([search, locationId], () => load())

onMounted(async () => {
  await Promise.all([load(), loadReferences()])
})

function expiryClass(line: StockLine): string {
  if (line.days_to_expiry === null) return 'text-subtle'
  if (line.days_to_expiry < 0) return 'text-error font-medium'
  if (line.days_to_expiry <= EXPIRY_SOON) return 'text-warning'
  return 'text-subtle'
}
</script>

<template>
  <UContainer class="py-6">
    <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">
          {{ t('inventory.stock') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('inventory.stockSubtitle') }}
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <!-- What another module offers to do with this stock. `purchasing`
             puts its way in here; with that module off nothing renders and
             this screen never learns it existed (ADR 0041). -->
        <ModuleSlot
          name="inventory.stock.actions"
          :ctx="{}"
        />
        <UButton
          variant="ghost"
          icon="i-lucide-scroll-text"
          :label="t('inventory.ledger.title')"
          to="/inventario/movimientos"
        />
        <UButton
          v-if="canReadImplants"
          variant="ghost"
          icon="i-lucide-bone"
          :label="t('inventory.implants.title')"
          to="/inventario/implantes"
        />
        <UButton
          variant="ghost"
          icon="i-lucide-list-checks"
          :label="t('inventory.materials.title')"
          to="/inventario/escandallos"
        />
        <UButton
          variant="ghost"
          icon="i-lucide-package"
          :label="t('inventory.items.title')"
          to="/inventario/articulos"
        />
        <UButton
          v-if="canAdjust"
          variant="ghost"
          icon="i-lucide-clipboard-check"
          :label="t('inventory.count.open')"
          to="/inventario/recuento"
        />
        <UButton
          v-if="canWriteItems"
          variant="subtle"
          icon="i-lucide-plus"
          :label="t('inventory.items.add')"
          @click="itemModalOpen = true"
        />
        <UButton
          v-if="canWriteStock"
          icon="i-lucide-package-plus"
          :label="t('inventory.movements.add')"
          @click="openMovement('purchase_receipt')"
        />
      </div>
    </div>

    <!-- What needs attention, before the table that explains it. -->
    <div class="mb-4 grid gap-3 sm:grid-cols-3">
      <button
        type="button"
        class="rounded-token-md border border-default bg-default p-3 text-left"
        :class="onlyLow ? 'ring-2 ring-primary' : ''"
        @click="onlyLow = !onlyLow"
      >
        <p class="text-xs text-subtle">
          {{ t('inventory.lowStock') }}
        </p>
        <p class="text-lg font-semibold tabular-nums">
          {{ counts.low }}
        </p>
      </button>

      <button
        type="button"
        class="rounded-token-md border border-default bg-default p-3 text-left"
        :class="onlyExpiring ? 'ring-2 ring-primary' : ''"
        @click="onlyExpiring = !onlyExpiring"
      >
        <p class="text-xs text-subtle">
          {{ t('inventory.expiringSoon') }}
        </p>
        <p class="text-lg font-semibold tabular-nums">
          {{ counts.expiring }}
        </p>
      </button>

      <div class="rounded-token-md border border-default bg-default p-3">
        <p class="text-xs text-subtle">
          {{ t('inventory.expired') }}
        </p>
        <p
          class="text-lg font-semibold tabular-nums"
          :class="counts.expired > 0 ? 'text-error' : ''"
        >
          {{ counts.expired }}
        </p>
      </div>
    </div>

    <div class="mb-4 flex flex-wrap gap-3">
      <UInput
        v-model="search"
        class="min-w-48 flex-1"
        icon="i-lucide-search"
        :placeholder="t('inventory.filters.search')"
        :aria-label="t('inventory.filters.search')"
      />
      <USelect
        v-model="locationId"
        class="min-w-40"
        :items="locationOptions"
        value-key="value"
        :aria-label="t('inventory.filters.allLocations')"
      />
    </div>

    <USkeleton
      v-if="isLoading"
      class="h-64 w-full"
    />

    <p
      v-else-if="visibleLines.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ lines.length === 0 ? t('inventory.emptyShelf') : t('inventory.noMatches') }}
    </p>

    <div
      v-else
      class="overflow-x-auto rounded-token-md border border-default"
    >
      <table class="w-full text-sm">
        <thead class="bg-elevated text-left text-xs text-subtle">
          <tr>
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
              {{ t('inventory.onHand') }}
            </th>
            <th class="p-3 text-right">
              {{ t('inventory.itemTotal') }}
            </th>
            <th class="p-3" />
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="line in visibleLines"
            :key="`${line.item_id}-${line.location_id}-${line.lot_id ?? 'nolot'}`"
            class="bg-default"
          >
            <td class="p-3">
              <p class="font-medium">
                {{ line.item_name }}
              </p>
              <p class="text-xs text-subtle">
                {{ line.item_code }} · {{ t(`inventory.categories.${line.category}`) }}
              </p>
            </td>
            <td class="p-3">
              {{ line.location_name }}
            </td>
            <td class="p-3">
              <template v-if="line.lot_code">
                <p>{{ line.lot_code }}</p>
                <p
                  v-if="line.expires_on"
                  class="text-xs"
                  :class="expiryClass(line)"
                >
                  {{ line.expires_on }}
                  <template v-if="line.days_to_expiry !== null && line.days_to_expiry < 0">
                    · {{ t('inventory.expired') }}
                  </template>
                </p>
              </template>
              <span
                v-else
                class="text-subtle"
              >—</span>
            </td>
            <td class="p-3 text-right tabular-nums">
              {{ quantity(line.quantity) }} {{ line.base_unit }}
            </td>
            <td class="p-3 text-right tabular-nums">
              <span :class="line.is_low ? 'font-semibold text-warning' : ''">
                {{ quantity(line.item_total) }}
              </span>
              <UBadge
                v-if="line.is_low"
                class="ml-2"
                color="warning"
                variant="subtle"
                :label="t('inventory.lowStock')"
              />
            </td>
            <td class="p-3">
              <div class="flex justify-end gap-1">
                <UButton
                  variant="ghost"
                  icon="i-lucide-history"
                  :aria-label="t('inventory.history.open')"
                  @click="openHistory(line)"
                />
                <UButton
                  v-if="canWriteStock"
                  variant="ghost"
                  icon="i-lucide-minus"
                  :aria-label="t('inventory.reasons.consumption')"
                  @click="openMovement('consumption', line.item_id)"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <InventoryItemModal
      v-model:open="itemModalOpen"
      @saved="afterChange"
    />

    <InventoryMovementModal
      v-model:open="movementModalOpen"
      :items="items"
      :locations="locations"
      :item-id="movementItemId"
      :reason="movementReason"
      @saved="afterChange"
    />

    <InventoryHistorySlideover
      v-model:open="historyOpen"
      :item-id="historyLine?.item_id ?? null"
      :item-name="historyLine?.item_name ?? ''"
      :base-unit="historyLine?.base_unit ?? ''"
    />
  </UContainer>
</template>
