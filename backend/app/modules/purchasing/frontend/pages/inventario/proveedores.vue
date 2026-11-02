<script setup lang="ts">
/**
 * Proveedores — who the clinic buys from.
 *
 * Archiving one with goods still on the way is refused by the service:
 * hiding the supplier would hide the orders somebody chases when a
 * delivery is late. The refusal is shown as it comes back.
 */
import type { Supplier } from '../../composables/usePurchasing'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { suppliers: listSuppliers, archiveSupplier, updateSupplier } = usePurchasing()
const purchasingError = usePurchasingErrors()

if (!can(PERMISSIONS.purchasing.suppliersRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.purchasing.suppliersWrite))

const showArchived = ref(false)
const rows = ref<Supplier[]>([])
const isLoading = ref(true)
const modalOpen = ref(false)
const editing = ref<Supplier | null>(null)

/**
 * The contact details on one line, without the dangling separator a
 * `v-if` chain leaves when the last field is the one that is missing.
 */
function contactLine(supplier: Supplier): string {
  const parts = [supplier.contact_name, supplier.phone, supplier.email].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : t('purchasing.suppliers.noContact')
}

async function load() {
  isLoading.value = true
  try {
    rows.value = (await listSuppliers(showArchived.value ? 'archived' : 'active')).data
  } finally {
    isLoading.value = false
  }
}

function openNew() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(supplier: Supplier) {
  editing.value = supplier
  modalOpen.value = true
}

async function archive(supplier: Supplier) {
  try {
    await archiveSupplier(supplier.id)
    toast.add({ title: t('purchasing.suppliers.archived'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({
      title: purchasingError(error, t('purchasing.suppliers.saveFailed')),
      color: 'error'
    })
  }
}

async function restore(supplier: Supplier) {
  try {
    await updateSupplier(supplier.id, { status: 'active' })
    toast.add({ title: t('purchasing.suppliers.restored'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({
      title: purchasingError(error, t('purchasing.suppliers.saveFailed')),
      color: 'error'
    })
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
          :label="t('purchasing.orders.title')"
          to="/inventario/compras"
        />
        <h1 class="mt-2 text-xl font-semibold">
          {{ t('purchasing.suppliers.title') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('purchasing.suppliers.subtitle') }}
        </p>
      </div>

      <UButton
        v-if="canWrite"
        icon="i-lucide-plus"
        :label="t('purchasing.suppliers.add')"
        @click="openNew"
      />
    </div>

    <UCheckbox
      v-model="showArchived"
      class="mb-4"
      :label="t('purchasing.suppliers.showArchived')"
    />

    <USkeleton
      v-if="isLoading"
      class="h-48 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('purchasing.suppliers.empty') }}
    </p>

    <ul
      v-else
      class="divide-y divide-default rounded-token-md border border-default"
    >
      <li
        v-for="supplier in rows"
        :key="supplier.id"
        class="flex items-center justify-between gap-3 bg-default p-3"
      >
        <div class="min-w-0">
          <p class="font-medium">
            {{ supplier.name }}
          </p>
          <p class="text-xs text-subtle">
            {{ contactLine(supplier) }}
          </p>
        </div>

        <div class="flex shrink-0 gap-1">
          <UButton
            v-if="canWrite"
            variant="ghost"
            icon="i-lucide-pencil"
            :aria-label="`${t('purchasing.suppliers.editTitle')}: ${supplier.name}`"
            @click="openEdit(supplier)"
          />
          <UButton
            v-if="canWrite && supplier.status === 'active'"
            variant="ghost"
            icon="i-lucide-archive"
            :aria-label="`${t('purchasing.suppliers.archive')}: ${supplier.name}`"
            @click="archive(supplier)"
          />
          <UButton
            v-if="canWrite && supplier.status === 'archived'"
            variant="ghost"
            icon="i-lucide-archive-restore"
            :aria-label="`${t('purchasing.suppliers.restore')}: ${supplier.name}`"
            @click="restore(supplier)"
          />
        </div>
      </li>
    </ul>

    <SupplierModal
      v-model:open="modalOpen"
      :supplier="editing"
      @saved="load"
    />
  </UContainer>
</template>
