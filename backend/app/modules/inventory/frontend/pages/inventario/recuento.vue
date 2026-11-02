<script setup lang="ts">
/**
 * Recuento — count what is on the shelf and post the differences.
 *
 * This is what keeps the ledger honest. The database and the physical
 * world drift apart by nature: somebody takes a box without saying so.
 * Without a way to record the count, the figure on screen slowly becomes
 * fiction and the whole feature is abandoned as "it never matches".
 *
 * Two rules the screen exists to express:
 *
 * - **A blank line is not a zero.** It means nobody counted that row, so
 *   nothing is posted for it. Typing `0` is a statement that the shelf is
 *   empty, and that posts an adjustment. Conflating the two would write
 *   off every article the counter did not reach.
 * - **A count does not overwrite the number.** It posts the difference as
 *   an adjustment, so afterwards the record holds both what was believed
 *   and what was found (ADR 0065).
 *
 * One location at a time, because that is how counting physically
 * happens: you stand in front of one cabinet.
 */
import type { StockLine } from '../../composables/useInventory'
import { quantity } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

/** The API refuses more than this in one count. */
const MAX_LINES = 500

const { t } = useI18n()
const toast = useToast()
const router = useRouter()
const { can } = usePermissions()
const { stock, locations: listLocations, closeCount } = useInventory()
const inventoryError = useInventoryErrors()

if (!can(PERMISSIONS.inventory.stockAdjust)) {
  await navigateTo('/inventario')
}

interface CountRow extends StockLine {
  /**
   * What the counter typed. Empty string means "not counted".
   *
   * Typed as a number too, because `UInput type="number"` writes a
   * `number` into the model as soon as something is entered and leaves
   * the empty state as `''`. Assuming a string here cost a
   * `row.counted.trim is not a function` on the first keystroke, which
   * silently blanked the whole Diferencia column.
   */
  counted: string | number
}

const locationId = ref<string>('')
const locationOptions = ref<{ value: string, label: string }[]>([])
const rows = ref<CountRow[]>([])
/**
 * True until the locations *and* the first load have landed.
 *
 * Starting at `false` meant a cold load painted "this location has no
 * articles yet" over a full storeroom for as long as the two requests
 * took — an empty-state lie is worse than a skeleton.
 */
const isLoading = ref(true)
const isSaving = ref(false)
const confirmOpen = ref(false)

function difference(row: CountRow): number | null {
  if (row.counted === '' || row.counted === null || row.counted === undefined) return null
  const counted
    = typeof row.counted === 'number' ? row.counted : Number.parseFloat(String(row.counted))
  if (!Number.isFinite(counted)) return null
  return counted - quantity(row.quantity)
}

const countedRows = computed(() => rows.value.filter(row => difference(row) !== null))
const differingRows = computed(() => countedRows.value.filter(row => difference(row) !== 0))

async function load() {
  if (!locationId.value) return
  isLoading.value = true

  try {
    // `include_empty`: an article the system believes is at zero is
    // exactly the one worth counting, and leaving it out would hide it.
    const response = await stock({ location_id: locationId.value, include_empty: true })
    rows.value = response.data.map(line => ({ ...line, counted: '' }))
  } finally {
    isLoading.value = false
  }
}

async function close() {
  isSaving.value = true
  try {
    const result = await closeCount({
      lines: countedRows.value.map(row => ({
        item_id: row.item_id,
        location_id: row.location_id,
        lot_id: row.lot_id,
        counted_quantity: String(row.counted)
      })),
      note: t('inventory.count.noteDefault')
    })
    confirmOpen.value = false
    toast.add({
      title: t('inventory.count.closed', {
        counted: result.data.lines_counted,
        posted: result.data.adjustments_posted
      }),
      color: 'success'
    })
    await router.push('/inventario')
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.count.failed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}

watch(locationId, () => load())

onMounted(async () => {
  const response = await listLocations()
  locationOptions.value = response.data.map(location => ({
    value: location.id,
    label: location.name
  }))
  locationId.value
    = response.data.find(location => location.is_default)?.id ?? response.data[0]?.id ?? ''
  // No locations at all: nothing is going to load, so stop waiting and
  // let the empty state say so.
  if (!locationId.value) isLoading.value = false
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
        {{ t('inventory.count.title') }}
      </h1>
      <p class="text-sm text-subtle">
        {{ t('inventory.count.subtitle') }}
      </p>
    </div>

    <UFormField
      class="mb-4 max-w-xs"
      :label="t('inventory.form.location')"
    >
      <USelect
        v-model="locationId"
        class="w-full"
        :items="locationOptions"
        value-key="value"
        :aria-label="t('inventory.form.location')"
      />
    </UFormField>

    <USkeleton
      v-if="isLoading"
      class="h-64 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('inventory.count.nothingHere') }}
    </p>

    <template v-else>
      <div class="overflow-x-auto rounded-token-md border border-default">
        <table class="w-full text-sm">
          <thead class="bg-elevated text-left text-xs text-subtle">
            <tr>
              <th class="p-3">
                {{ t('inventory.form.item') }}
              </th>
              <th class="p-3">
                {{ t('inventory.lot') }}
              </th>
              <th class="p-3 text-right">
                {{ t('inventory.count.system') }}
              </th>
              <th class="p-3 text-right">
                {{ t('inventory.count.counted') }}
              </th>
              <th class="p-3 text-right">
                {{ t('inventory.count.difference') }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-default">
            <tr
              v-for="row in rows"
              :key="`${row.item_id}-${row.lot_id ?? 'nolot'}`"
              class="bg-default"
            >
              <td class="p-3">
                <p class="font-medium">
                  {{ row.item_name }}
                </p>
                <p class="text-xs text-subtle">
                  {{ row.item_code }}
                </p>
              </td>
              <td class="p-3">
                <span v-if="row.lot_code">{{ row.lot_code }}</span>
                <span
                  v-else
                  class="text-subtle"
                >—</span>
              </td>
              <td class="p-3 text-right tabular-nums">
                {{ quantity(row.quantity) }} {{ row.base_unit }}
              </td>
              <td class="p-3">
                <UInput
                  v-model="row.counted"
                  class="ml-auto w-28"
                  type="number"
                  min="0"
                  step="0.001"
                  inputmode="decimal"
                  :placeholder="t('inventory.count.notCountedShort')"
                  :aria-label="`${t('inventory.count.counted')}: ${row.item_name}`"
                />
              </td>
              <td class="p-3 text-right tabular-nums">
                <span
                  v-if="difference(row) === null"
                  class="text-subtle"
                >—</span>
                <span
                  v-else-if="difference(row) === 0"
                  class="text-subtle"
                >0</span>
                <span
                  v-else
                  :class="difference(row)! > 0 ? 'text-success' : 'text-error'"
                >
                  {{ difference(row)! > 0 ? '+' : '' }}{{ difference(row) }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Sticky, not fixed: the counter is at the far end of a long list
           when they finish and a button at the top is a button nobody
           reaches — but `fixed inset-x-0` spans the viewport and slides
           the bar under the sidebar. -->
      <div
        class="sticky bottom-0 mt-4 rounded-token-md border border-default bg-default/95 p-3 backdrop-blur"
      >
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p class="text-sm text-subtle">
            {{ t('inventory.count.progress', {
              counted: countedRows.length,
              total: rows.length,
              differing: differingRows.length
            }) }}
          </p>
          <UButton
            :label="t('inventory.count.close')"
            :disabled="countedRows.length === 0 || countedRows.length > MAX_LINES"
            @click="confirmOpen = true"
          />
        </div>
      </div>
    </template>

    <UModal
      v-model:open="confirmOpen"
      :title="t('inventory.count.confirmTitle')"
    >
      <template #body>
        <p class="mb-3 text-sm text-subtle">
          {{ t('inventory.count.confirmBody', {
            counted: countedRows.length,
            differing: differingRows.length
          }) }}
        </p>

        <ul
          v-if="differingRows.length > 0"
          class="divide-y divide-default text-sm"
        >
          <li
            v-for="row in differingRows"
            :key="`diff-${row.item_id}-${row.lot_id ?? 'nolot'}`"
            class="flex items-center justify-between gap-3 py-2"
          >
            <span class="min-w-0">
              {{ row.item_name }}
              <span
                v-if="row.lot_code"
                class="text-xs text-subtle"
              >· {{ row.lot_code }}</span>
            </span>
            <span class="shrink-0 tabular-nums">
              {{ quantity(row.quantity) }} → {{ row.counted }}
              <span :class="difference(row)! > 0 ? 'text-success' : 'text-error'">
                ({{ difference(row)! > 0 ? '+' : '' }}{{ difference(row) }})
              </span>
            </span>
          </li>
        </ul>

        <p
          v-else
          class="text-sm"
        >
          {{ t('inventory.count.noDifferences') }}
        </p>
      </template>

      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            variant="ghost"
            :label="t('common.cancel')"
            @click="confirmOpen = false"
          />
          <UButton
            :label="t('inventory.count.confirm')"
            :loading="isSaving"
            @click="close"
          />
        </div>
      </template>
    </UModal>
  </UContainer>
</template>
