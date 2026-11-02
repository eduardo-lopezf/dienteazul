<script setup lang="ts">
/**
 * One purchase order: its lines, what has arrived, and the way to book
 * in what just turned up.
 *
 * The buttons follow the order's state rather than the person's rights
 * alone: a draft is sent, a sent order receives, and a received one only
 * reads. Receiving is `orders.receive`, which reception holds and
 * ordering is not.
 */
import type { PurchaseOrder } from '../../../composables/usePurchasing'
import { amount } from '../../../composables/usePurchasing'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

const { t, locale } = useI18n()
const toast = useToast()
const route = useRoute()
const { can } = usePermissions()
const { order: getOrder, sendOrder, cancelOrder } = usePurchasing()
const purchasingError = usePurchasingErrors()

if (!can(PERMISSIONS.purchasing.ordersRead)) {
  await navigateTo('/inventario')
}

const canWrite = computed(() => can(PERMISSIONS.purchasing.ordersWrite))
const canReceive = computed(() => can(PERMISSIONS.purchasing.ordersReceive))

const order = ref<PurchaseOrder | null>(null)
const isLoading = ref(true)
const receiveOpen = ref(false)

const isDraft = computed(() => order.value?.status === 'draft')
const isOpen = computed(
  () => order.value?.status === 'sent' || order.value?.status === 'partially_received'
)
const hasPending = computed(
  () => order.value?.lines.some(line => amount(line.quantity_pending) > 0) ?? false
)

async function load() {
  isLoading.value = true
  try {
    order.value = (await getOrder(String(route.params.id))).data
  } finally {
    isLoading.value = false
  }
}

async function send() {
  try {
    await sendOrder(String(route.params.id))
    toast.add({ title: t('purchasing.orders.sent'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: purchasingError(error, t('purchasing.orders.saveFailed')), color: 'error' })
  }
}

async function cancel() {
  try {
    await cancelOrder(String(route.params.id))
    toast.add({ title: t('purchasing.orders.cancelled'), color: 'success' })
    await load()
  } catch (error: unknown) {
    toast.add({ title: purchasingError(error, t('purchasing.orders.saveFailed')), color: 'error' })
  }
}

function formatDate(iso: string | null): string {
  return iso
    ? new Date(`${iso}T00:00:00`).toLocaleDateString(locale.value, {
        day: '2-digit',
        month: 'short',
        year: 'numeric'
      })
    : '—'
}

onMounted(() => load())
</script>

<template>
  <UContainer class="py-6">
    <UButton
      variant="ghost"
      icon="i-lucide-arrow-left"
      :label="t('purchasing.orders.title')"
      to="/inventario/compras"
    />

    <USkeleton
      v-if="isLoading"
      class="mt-4 h-64 w-full"
    />

    <p
      v-else-if="!order"
      class="mt-4 rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('purchasing.orders.notFound') }}
    </p>

    <template v-else>
      <div class="mt-2 mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div class="flex items-center gap-3">
            <h1 class="text-xl font-semibold">
              {{ order.number }}
            </h1>
            <UBadge
              variant="subtle"
              :label="t(`purchasing.status.${order.status}`)"
            />
          </div>
          <p class="text-sm text-subtle">
            {{ order.supplier_name }} · {{ formatDate(order.order_date) }}
            <template v-if="order.expected_date">
              · {{ t('purchasing.form.expectedDate') }} {{ formatDate(order.expected_date) }}
            </template>
          </p>
          <p
            v-if="order.notes"
            class="mt-1 text-sm"
          >
            {{ order.notes }}
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <UButton
            v-if="canWrite && isDraft"
            icon="i-lucide-send"
            :label="t('purchasing.orders.send')"
            @click="send"
          />
          <UButton
            v-if="canReceive && isOpen && hasPending"
            icon="i-lucide-package-check"
            :label="t('purchasing.receipt.open')"
            @click="receiveOpen = true"
          />
          <UButton
            v-if="canWrite && (isDraft || isOpen)"
            variant="ghost"
            icon="i-lucide-x"
            :label="t('purchasing.orders.cancel')"
            @click="cancel"
          />
        </div>
      </div>

      <div class="overflow-x-auto rounded-token-md border border-default">
        <table class="w-full text-sm">
          <thead class="bg-elevated text-left text-xs text-subtle">
            <tr>
              <th class="p-3">
                {{ t('purchasing.form.article') }}
              </th>
              <th class="p-3 text-right">
                {{ t('purchasing.form.ordered') }}
              </th>
              <th class="p-3 text-right">
                {{ t('purchasing.form.received') }}
              </th>
              <th class="p-3 text-right">
                {{ t('purchasing.form.pending') }}
              </th>
              <th class="p-3 text-right">
                {{ t('purchasing.form.unitCost') }}
              </th>
              <th class="p-3 text-right">
                {{ t('purchasing.form.total') }}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-default">
            <tr
              v-for="line in order.lines"
              :key="line.id"
              class="bg-default"
            >
              <td class="p-3">
                <p class="font-medium">
                  {{ line.item_name }}
                </p>
                <p class="text-xs text-subtle">
                  {{ line.item_code }}
                  <span v-if="line.tracks_lots"> · {{ t('purchasing.form.lotTracked') }}</span>
                </p>
              </td>
              <td class="p-3 text-right tabular-nums">
                {{ amount(line.quantity_ordered) }} {{ line.base_unit }}
              </td>
              <td class="p-3 text-right tabular-nums">
                {{ amount(line.quantity_received) }}
              </td>
              <td class="p-3 text-right tabular-nums">
                <span :class="amount(line.quantity_pending) > 0 ? 'font-semibold' : 'text-subtle'">
                  {{ amount(line.quantity_pending) }}
                </span>
              </td>
              <td class="p-3 text-right tabular-nums">
                {{ amount(line.unit_cost) }}
              </td>
              <td class="p-3 text-right tabular-nums">
                {{ amount(line.line_total).toFixed(2) }}
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr class="bg-elevated">
              <td
                class="p-3 text-right font-medium"
                colspan="5"
              >
                {{ t('purchasing.form.total') }}
              </td>
              <td class="p-3 text-right font-semibold tabular-nums">
                {{ amount(order.total).toFixed(2) }}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <p class="mt-3 text-xs text-subtle">
        {{ t('purchasing.orders.ledgerHint') }}
      </p>

      <ReceiveOrderModal
        v-model:open="receiveOpen"
        :order="order"
        @received="load"
      />
    </template>
  </UContainer>
</template>
