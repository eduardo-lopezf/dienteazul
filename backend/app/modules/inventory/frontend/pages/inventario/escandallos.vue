<script setup lang="ts">
/**
 * Escandallos — what each treatment is expected to consume.
 *
 * The list lives in the inventory, keyed by a treatment, rather than on
 * the treatment itself: switch Treatments off and these rows stay
 * intact but inert; switch the inventory off and the catalogue never
 * learns stock exists (ADR 0037).
 *
 * That is why a row can show an id with no name — the Treatments App is
 * off, or the treatment was deleted. The screen says so instead of
 * hiding the row, because the row is still the clinic's data.
 */
import type { CatalogTreatmentOption, InventoryItem, TreatmentMaterials } from '../../composables/useInventory'
import { quantity } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const {
  materials: listMaterials,
  catalogueTreatments,
  items: listItems,
  setMaterials
} = useInventory()
const inventoryError = useInventoryErrors()

if (!can(PERMISSIONS.inventory.itemsRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.inventory.itemsWrite))

const rows = ref<TreatmentMaterials[]>([])
const treatments = ref<CatalogTreatmentOption[]>([])
const articles = ref<InventoryItem[]>([])
const isLoading = ref(true)
const modalOpen = ref(false)
const editing = ref<TreatmentMaterials | null>(null)

const taken = computed(() => rows.value.map(row => row.catalog_item_id))

async function load() {
  isLoading.value = true
  try {
    const [materialsResponse, treatmentsResponse, itemsResponse] = await Promise.all([
      listMaterials(),
      catalogueTreatments(),
      listItems()
    ])
    rows.value = materialsResponse.data
    treatments.value = treatmentsResponse.data
    articles.value = itemsResponse.data
  } finally {
    isLoading.value = false
  }
}

function openNew() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(row: TreatmentMaterials) {
  editing.value = row
  modalOpen.value = true
}

async function clear(row: TreatmentMaterials) {
  try {
    await setMaterials(row.catalog_item_id, [])
    toast.add({ title: t('inventory.materials.cleared'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.materials.saveFailed')), color: 'error' })
  }
}

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
          {{ t('inventory.materials.title') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('inventory.materials.subtitle') }}
        </p>
      </div>

      <UButton
        v-if="canWrite"
        icon="i-lucide-plus"
        :label="t('inventory.materials.add')"
        @click="openNew"
      />
    </div>

    <p
      v-if="!isLoading && treatments.length === 0"
      class="mb-4 rounded-token-md border border-default bg-default p-3 text-sm text-subtle"
    >
      {{ t('inventory.materials.noTreatments') }}
    </p>

    <USkeleton
      v-if="isLoading"
      class="h-48 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('inventory.materials.empty') }}
    </p>

    <ul
      v-else
      class="space-y-3"
    >
      <li
        v-for="row in rows"
        :key="row.catalog_item_id"
        class="rounded-token-md border border-default bg-default p-3"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-medium">
              <template v-if="row.treatment_name">
                {{ row.treatment_name }}
              </template>
              <span
                v-else
                class="text-subtle italic"
              >{{ t('inventory.materials.unknownTreatment') }}</span>
            </p>
            <p
              v-if="row.treatment_code"
              class="text-xs text-subtle"
            >
              {{ row.treatment_code }}
            </p>
          </div>

          <div
            v-if="canWrite"
            class="flex shrink-0 gap-1"
          >
            <UButton
              variant="ghost"
              icon="i-lucide-pencil"
              :aria-label="t('inventory.materials.editTitle')"
              @click="openEdit(row)"
            />
            <UButton
              variant="ghost"
              icon="i-lucide-trash-2"
              :aria-label="t('inventory.materials.clear')"
              @click="clear(row)"
            />
          </div>
        </div>

        <ul class="mt-2 divide-y divide-default border-t border-default">
          <li
            v-for="line in row.lines"
            :key="line.item_id"
            class="flex items-center justify-between gap-3 py-2 text-sm"
          >
            <span class="min-w-0">
              {{ line.item_name }}
              <span class="text-xs text-subtle">{{ line.item_code }}</span>
              <UBadge
                v-if="line.tracks_lots"
                class="ml-2"
                color="warning"
                variant="subtle"
                :label="t('inventory.materials.byHand')"
              />
            </span>
            <span class="shrink-0 tabular-nums">
              {{ quantity(line.quantity_base) }} {{ line.base_unit }}
            </span>
          </li>
        </ul>
      </li>
    </ul>

    <p class="mt-4 text-xs text-subtle">
      {{ t('inventory.materials.howItWorks') }}
    </p>

    <TreatmentMaterialsModal
      v-model:open="modalOpen"
      :materials="editing"
      :treatments="treatments"
      :articles="articles"
      :taken="taken"
      @saved="load"
    />
  </UContainer>
</template>
