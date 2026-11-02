<script setup lang="ts">
/**
 * Artículos — the master data behind every figure on Existencias.
 *
 * Reading it is everybody's (you need to know what an article is called
 * and what its unit is); changing it is administration's. The list shows
 * archived articles on demand rather than hiding them for good: an
 * article is archived, never deleted, because the ledger references it
 * forever.
 */
import type { InventoryItem, ItemCategory } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

/** Sentinel for "any": Reka UI reserves the empty string. */
const ANY = '__any__'

const CATEGORIES: ItemCategory[] = [
  'consumable',
  'restorative',
  'anaesthetic',
  'instrument',
  'implant',
  'prosthetic',
  'hygiene',
  'office',
  'other'
]

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { items: listItems, archiveItem, updateItem } = useInventory()
const inventoryError = useInventoryErrors()

if (!can(PERMISSIONS.inventory.itemsRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.inventory.itemsWrite))

const search = ref('')
const category = ref<ItemCategory | typeof ANY>(ANY)
const showArchived = ref(false)

const rows = ref<InventoryItem[]>([])
const total = ref(0)
const isLoading = ref(true)
const modalOpen = ref(false)
const editing = ref<InventoryItem | null>(null)

const categoryOptions = computed(() => [
  { value: ANY, label: t('inventory.filters.allCategories') },
  ...CATEGORIES.map(value => ({ value, label: t(`inventory.categories.${value}`) }))
])

async function load() {
  isLoading.value = true
  try {
    const response = await listItems({
      search: search.value || undefined,
      category: category.value === ANY ? undefined : category.value,
      status: showArchived.value ? 'archived' : 'active',
      pageSize: 100
    })
    rows.value = response.data
    total.value = response.total
  } finally {
    isLoading.value = false
  }
}

function openNew() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(item: InventoryItem) {
  editing.value = item
  modalOpen.value = true
}

async function archive(item: InventoryItem) {
  try {
    await archiveItem(item.id)
    toast.add({ title: t('inventory.items.archived'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.items.updateFailed')), color: 'error' })
  }
}

async function restore(item: InventoryItem) {
  try {
    await updateItem(item.id, { status: 'active' })
    toast.add({ title: t('inventory.items.restored'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.items.updateFailed')), color: 'error' })
  }
}

watch([search, category, showArchived], () => load())

onMounted(() => load())
</script>

<template>
  <UContainer class="py-6">
    <div class="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <UButton
          variant="ghost"
          icon="i-lucide-arrow-left"
          :label="t('inventory.stock')"
          to="/inventario"
        />
        <h1 class="mt-2 text-xl font-semibold">
          {{ t('inventory.items.title') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('inventory.items.subtitle') }}
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <UButton
          variant="ghost"
          icon="i-lucide-map-pin"
          :label="t('inventory.locations.title')"
          to="/inventario/ubicaciones"
        />
        <UButton
          v-if="canWrite"
          icon="i-lucide-plus"
          :label="t('inventory.items.add')"
          @click="openNew"
        />
      </div>
    </div>

    <div class="mb-4 flex flex-wrap items-center gap-3">
      <UInput
        v-model="search"
        class="min-w-48 flex-1"
        icon="i-lucide-search"
        :placeholder="t('inventory.filters.search')"
        :aria-label="t('inventory.filters.search')"
      />
      <USelect
        v-model="category"
        class="min-w-40"
        :items="categoryOptions"
        value-key="value"
        :aria-label="t('inventory.filters.allCategories')"
      />
      <UCheckbox
        v-model="showArchived"
        :label="t('inventory.items.showArchived')"
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
      {{ t('inventory.items.empty') }}
    </p>

    <div
      v-else
      class="overflow-x-auto rounded-token-md border border-default"
    >
      <table class="w-full text-sm">
        <thead class="bg-elevated text-left text-xs text-subtle">
          <tr>
            <th class="p-3">
              {{ t('inventory.form.code') }}
            </th>
            <th class="p-3">
              {{ t('inventory.form.name') }}
            </th>
            <th class="p-3">
              {{ t('inventory.form.category') }}
            </th>
            <th class="p-3">
              {{ t('inventory.form.baseUnit') }}
            </th>
            <th class="p-3 text-right">
              {{ t('inventory.reorderPoint') }}
            </th>
            <th class="p-3">
              {{ t('inventory.lot') }}
            </th>
            <th class="p-3" />
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="item in rows"
            :key="item.id"
            class="bg-default"
          >
            <td class="p-3 font-mono text-xs">
              {{ item.code }}
            </td>
            <td class="p-3 font-medium">
              {{ item.name }}
            </td>
            <td class="p-3">
              {{ t(`inventory.categories.${item.category}`) }}
            </td>
            <td class="p-3">
              {{ item.base_unit }}
            </td>
            <td class="p-3 text-right tabular-nums">
              <span v-if="item.reorder_point">{{ Number(item.reorder_point) }}</span>
              <span
                v-else
                class="text-subtle"
              >—</span>
            </td>
            <td class="p-3">
              <UBadge
                v-if="item.tracks_lots"
                color="neutral"
                variant="subtle"
                :label="t('inventory.items.tracked')"
              />
              <span
                v-else
                class="text-subtle"
              >—</span>
            </td>
            <td class="p-3">
              <div class="flex justify-end gap-1">
                <UButton
                  v-if="canWrite"
                  variant="ghost"
                  icon="i-lucide-pencil"
                  :aria-label="`${t('inventory.items.editTitle')}: ${item.name}`"
                  @click="openEdit(item)"
                />
                <UButton
                  v-if="canWrite && item.status === 'active'"
                  variant="ghost"
                  icon="i-lucide-archive"
                  :aria-label="`${t('inventory.items.archive')}: ${item.name}`"
                  @click="archive(item)"
                />
                <UButton
                  v-if="canWrite && item.status === 'archived'"
                  variant="ghost"
                  icon="i-lucide-archive-restore"
                  :aria-label="`${t('inventory.items.restore')}: ${item.name}`"
                  @click="restore(item)"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <InventoryItemModal
      v-model:open="modalOpen"
      :item="editing"
      @saved="load"
    />
  </UContainer>
</template>
