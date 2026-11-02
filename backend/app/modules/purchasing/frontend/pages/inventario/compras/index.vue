<script setup lang="ts">
/**
 * Compras — what has been ordered and what is still coming.
 *
 * The list is the working screen: a clinic's open orders are a short
 * list, so it filters rather than pages. Everything about one order —
 * its lines, receiving it — is on its own page.
 */
import type { OrderStatus, PurchaseOrder } from '../../../composables/usePurchasing'
import { amount } from '../../../composables/usePurchasing'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t, locale } = useI18n()
const router = useRouter()
const { can } = usePermissions()
const { orders: listOrders, suppliers: listSuppliers } = usePurchasing()

if (!can(PERMISSIONS.purchasing.ordersRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.purchasing.ordersWrite))

const openOnly = ref(true)
const rows = ref<PurchaseOrder[]>([])
const suppliers = ref<{ id: string, name: string }[]>([])
const articles = ref<
  { id: string, code: string, name: string, base_unit: string, cost_per_base_unit: string | null }[]
>([])
const isLoading = ref(true)
const modalOpen = ref(false)

async function load() {
  isLoading.value = true
  try {
    rows.value = (await listOrders({ open_only: openOnly.value })).data
  } finally {
    isLoading.value = false
  }
}

function statusColor(status: OrderStatus): 'neutral' | 'info' | 'warning' | 'success' | 'error' {
  return {
    draft: 'neutral',
    sent: 'info',
    partially_received: 'warning',
    received: 'success',
    cancelled: 'error'
  }[status] as 'neutral' | 'info' | 'warning' | 'success' | 'error'
}

function formatDate(iso: string | null): string {
  return iso
    ? new Date(`${iso}T00:00:00`).toLocaleDateString(locale.value, {
        day: '2-digit',
        month: 'short',
        year: '2-digit'
      })
    : '—'
}

watch(openOnly, () => load())

onMounted(async () => {
  // The articles feed the new-order dialog. Asked for here rather than
  // inside it so opening the dialog is instant.
  const { items } = useInventory()
  const [suppliersResponse, itemsResponse] = await Promise.all([listSuppliers(), items()])
  suppliers.value = suppliersResponse.data.map(s => ({ id: s.id, name: s.name }))
  articles.value = itemsResponse.data.map(item => ({
    id: item.id,
    code: item.code,
    name: item.name,
    base_unit: item.base_unit,
    cost_per_base_unit: item.cost_per_base_unit
  }))
  await load()
})
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
          {{ t('purchasing.orders.title') }}
        </h1>
        <p class="text-sm text-subtle">
          {{ t('purchasing.orders.subtitle') }}
        </p>
      </div>

      <div class="flex flex-wrap gap-2">
        <UButton
          variant="ghost"
          icon="i-lucide-truck"
          :label="t('purchasing.suppliers.title')"
          to="/inventario/proveedores"
        />
        <UButton
          v-if="canWrite"
          icon="i-lucide-plus"
          :label="t('purchasing.orders.add')"
          :disabled="suppliers.length === 0"
          @click="modalOpen = true"
        />
      </div>
    </div>

    <p
      v-if="suppliers.length === 0 && !isLoading"
      class="mb-4 rounded-token-md border border-default bg-default p-3 text-sm text-subtle"
    >
      {{ t('purchasing.orders.needsSupplier') }}
    </p>

    <UCheckbox
      v-model="openOnly"
      class="mb-4"
      :label="t('purchasing.orders.openOnly')"
    />

    <USkeleton
      v-if="isLoading"
      class="h-48 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('purchasing.orders.empty') }}
    </p>

    <div
      v-else
      class="overflow-x-auto rounded-token-md border border-default"
    >
      <table class="w-full text-sm">
        <thead class="bg-elevated text-left text-xs text-subtle">
          <tr>
            <th class="p-3">
              {{ t('purchasing.orders.number') }}
            </th>
            <th class="p-3">
              {{ t('purchasing.form.supplier') }}
            </th>
            <th class="p-3">
              {{ t('purchasing.form.orderDate') }}
            </th>
            <th class="p-3">
              {{ t('purchasing.form.expectedDate') }}
            </th>
            <th class="p-3 text-right">
              {{ t('purchasing.form.total') }}
            </th>
            <th class="p-3">
              {{ t('purchasing.orders.status') }}
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="order in rows"
            :key="order.id"
            class="cursor-pointer bg-default hover:bg-elevated"
            @click="router.push(`/inventario/compras/${order.id}`)"
          >
            <td class="p-3 font-mono text-xs">
              {{ order.number }}
            </td>
            <td class="p-3 font-medium">
              {{ order.supplier_name }}
            </td>
            <td class="p-3">
              {{ formatDate(order.order_date) }}
            </td>
            <td class="p-3">
              {{ formatDate(order.expected_date) }}
            </td>
            <td class="p-3 text-right tabular-nums">
              {{ amount(order.total).toFixed(2) }}
            </td>
            <td class="p-3">
              <UBadge
                :color="statusColor(order.status)"
                variant="subtle"
                :label="t(`purchasing.status.${order.status}`)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <PurchaseOrderModal
      v-model:open="modalOpen"
      :suppliers="suppliers"
      :articles="articles"
      @saved="(id: string) => router.push(`/inventario/compras/${id}`)"
    />
  </UContainer>
</template>
