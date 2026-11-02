<script setup lang="ts">
/**
 * Book a delivery in.
 *
 * One row per line that is still pending, prefilled with what is
 * pending — the common case is "everything arrived" and nobody should
 * have to retype it. A row left at zero is not received.
 *
 * Each row becomes a movement in the stock ledger, so what is typed here
 * is a claim about a box somebody is holding. That is why the numbers
 * cannot exceed what was ordered: a surplus is a different conversation
 * with the supplier, recorded as its own stock movement.
 */
import type { PurchaseOrder, ReceiptLineInput } from '../composables/usePurchasing'
import { amount } from '../composables/usePurchasing'

const props = defineProps<{ open: boolean, order: PurchaseOrder | null }>()

const emit = defineEmits<{ 'update:open': [value: boolean], 'received': [] }>()

const { t } = useI18n()
const toast = useToast()
const { receiveOrder } = usePurchasing()
const purchasingError = usePurchasingErrors()

interface DraftReceipt {
  line_id: string
  label: string
  unit: string
  pending: number
  tracks_lots: boolean
  quantity: string | number
  lot_code: string
  expires_on: string
}

const rows = ref<DraftReceipt[]>([])
const note = ref('')
const isSaving = ref(false)

watch(
  () => [props.open, props.order] as const,
  ([open, order]) => {
    if (!open || !order) return
    rows.value = order.lines
      .filter(line => amount(line.quantity_pending) > 0)
      .map(line => ({
        line_id: line.id,
        label: `${line.item_code} · ${line.item_name}`,
        unit: line.base_unit,
        pending: amount(line.quantity_pending),
        tracks_lots: line.tracks_lots,
        quantity: amount(line.quantity_pending),
        lot_code: '',
        expires_on: ''
      }))
    note.value = ''
  },
  { immediate: true }
)

function quantityOf(row: DraftReceipt): number {
  const value = typeof row.quantity === 'number' ? row.quantity : Number.parseFloat(row.quantity)
  return Number.isFinite(value) ? value : 0
}

const payload = computed<ReceiptLineInput[]>(() =>
  rows.value
    .filter(row => quantityOf(row) > 0)
    .map(row => ({
      line_id: row.line_id,
      quantity: String(row.quantity),
      lot_code: row.tracks_lots ? row.lot_code.trim() : null,
      expires_on: row.tracks_lots && row.expires_on ? row.expires_on : null
    }))
)

const canSave = computed(
  () =>
    payload.value.length > 0
    && rows.value.every(
      row =>
        quantityOf(row) <= row.pending
        && (!row.tracks_lots || quantityOf(row) === 0 || row.lot_code.trim().length > 0)
    )
)

async function save() {
  if (!canSave.value || !props.order) return
  isSaving.value = true
  try {
    const result = await receiveOrder(props.order.id, {
      lines: payload.value,
      note: note.value || null
    })
    toast.add({
      title:
        result.data.order_status === 'received'
          ? t('purchasing.receipt.received_full')
          : t('purchasing.receipt.partially_received'),
      color: 'success'
    })
    emit('received')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: purchasingError(error, t('purchasing.receipt.failed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('purchasing.receipt.title')"
    :ui="{ content: 'max-w-3xl' }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <p class="mb-3 text-sm text-subtle">
        {{ t('purchasing.receipt.subtitle') }}
      </p>

      <div class="space-y-3">
        <div
          v-for="row in rows"
          :key="row.line_id"
          class="rounded-token-md border border-default p-3"
        >
          <div class="flex flex-wrap items-end justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-medium">
                {{ row.label }}
              </p>
              <p class="text-xs text-subtle">
                {{ t('purchasing.receipt.pending', { pending: row.pending, unit: row.unit }) }}
              </p>
            </div>
            <UInput
              v-model="row.quantity"
              class="w-28"
              type="number"
              min="0"
              :max="row.pending"
              step="0.001"
              :aria-label="`${t('purchasing.receipt.received')}: ${row.label}`"
            />
          </div>

          <div
            v-if="row.tracks_lots"
            class="mt-3 grid gap-3 sm:grid-cols-2"
          >
            <UFormField :label="t('purchasing.receipt.lotCode')">
              <UInput
                v-model="row.lot_code"
                class="w-full"
                :aria-label="`${t('purchasing.receipt.lotCode')}: ${row.label}`"
              />
            </UFormField>
            <UFormField :label="t('purchasing.receipt.expiresOn')">
              <UInput
                v-model="row.expires_on"
                class="w-full"
                type="date"
                :aria-label="`${t('purchasing.receipt.expiresOn')}: ${row.label}`"
              />
            </UFormField>
          </div>
        </div>

        <UFormField
          :label="t('purchasing.receipt.note')"
          :description="t('purchasing.receipt.noteHint')"
        >
          <UInput
            v-model="note"
            class="w-full"
            :aria-label="t('purchasing.receipt.note')"
          />
        </UFormField>
      </div>
    </template>

    <template #footer>
      <div class="flex w-full justify-end gap-2">
        <UButton
          variant="ghost"
          :label="t('common.cancel')"
          @click="emit('update:open', false)"
        />
        <UButton
          :label="t('purchasing.receipt.confirm')"
          :loading="isSaving"
          :disabled="!canSave"
          @click="save"
        />
      </div>
    </template>
  </UModal>
</template>
