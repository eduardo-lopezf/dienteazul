<script setup lang="ts">
/**
 * Ubicaciones — where stock sits.
 *
 * A handful of rows per clinic: the storeroom, the cabinets, the fridge.
 * Deliberately not a hierarchy, and deliberately not the agenda's
 * cabinets either — a location may point at one, but the inventory owns
 * its own list so the App keeps working with the Agenda switched off.
 *
 * Archiving is refused by the API while a location still holds stock:
 * hiding a place that has material in it would drop that material out of
 * every total while it is still on a shelf. The refusal is shown as it
 * comes back rather than pre-empted here, because only the server knows.
 */
import type { InventoryLocation } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { locations: listLocations, archiveLocation, updateLocation } = useInventory()
const inventoryError = useInventoryErrors()

if (!can(PERMISSIONS.inventory.stockRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.inventory.itemsWrite))

const showArchived = ref(false)
const rows = ref<InventoryLocation[]>([])
const isLoading = ref(true)
const modalOpen = ref(false)
const editing = ref<InventoryLocation | null>(null)

async function load() {
  isLoading.value = true
  try {
    rows.value = (await listLocations(showArchived.value ? 'archived' : 'active')).data
  } finally {
    isLoading.value = false
  }
}

function openNew() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(location: InventoryLocation) {
  editing.value = location
  modalOpen.value = true
}

async function archive(location: InventoryLocation) {
  try {
    await archiveLocation(location.id)
    toast.add({ title: t('inventory.locations.archived'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.locations.saveFailed')), color: 'error' })
  }
}

async function restore(location: InventoryLocation) {
  try {
    await updateLocation(location.id, { status: 'active' })
    toast.add({ title: t('inventory.locations.restored'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.locations.saveFailed')), color: 'error' })
  }
}

watch(showArchived, () => load())

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
          {{ t('inventory.locations.title') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('inventory.locations.subtitle') }}
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <UButton
          variant="ghost"
          icon="i-lucide-package"
          :label="t('inventory.items.title')"
          to="/inventario/articulos"
        />
        <UButton
          v-if="canWrite"
          icon="i-lucide-plus"
          :label="t('inventory.locations.add')"
          @click="openNew"
        />
      </div>
    </div>

    <UCheckbox
      v-model="showArchived"
      class="mb-4"
      :label="t('inventory.locations.showArchived')"
    />

    <USkeleton
      v-if="isLoading"
      class="h-48 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('inventory.locations.empty') }}
    </p>

    <ul
      v-else
      class="divide-y divide-default rounded-token-md border border-default"
    >
      <li
        v-for="location in rows"
        :key="location.id"
        class="flex items-center justify-between gap-3 bg-default p-3"
      >
        <div class="min-w-0">
          <p class="font-medium">
            {{ location.name }}
            <UBadge
              v-if="location.is_default"
              class="ml-2"
              color="primary"
              variant="subtle"
              :label="t('inventory.locations.default')"
            />
          </p>
          <p class="text-xs text-subtle">
            {{ t(`inventory.locationKinds.${location.kind}`) }}
          </p>
        </div>

        <div class="flex shrink-0 gap-1">
          <UButton
            v-if="canWrite"
            variant="ghost"
            icon="i-lucide-pencil"
            :aria-label="`${t('inventory.locations.editTitle')}: ${location.name}`"
            @click="openEdit(location)"
          />
          <UButton
            v-if="canWrite && location.status === 'active'"
            variant="ghost"
            icon="i-lucide-archive"
            :aria-label="`${t('inventory.locations.archive')}: ${location.name}`"
            @click="archive(location)"
          />
          <UButton
            v-if="canWrite && location.status === 'archived'"
            variant="ghost"
            icon="i-lucide-archive-restore"
            :aria-label="`${t('inventory.locations.restore')}: ${location.name}`"
            @click="restore(location)"
          />
        </div>
      </li>
    </ul>

    <InventoryLocationModal
      v-model:open="modalOpen"
      :location="editing"
      @saved="load"
    />
  </UContainer>
</template>
