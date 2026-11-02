<script setup lang="ts">
/**
 * Write a purchase order.
 *
 * Quantities are in the article's **base unit**, like everything the
 * inventory counts — the box of 100 is converted by whoever types the
 * line, and the unit cost is per base unit. Mixing the two is how an
 * order for 4 boxes becomes an order for 4 gloves.
 */
import type { OrderLineInput } from '../composables/usePurchasing'
import { amount } from '../composables/usePurchasing'

interface ArticleOption {
  id: string
  code: string
  name: string
  base_unit: string
  cost_per_base_unit: string | null
}

const props = defineProps<{
  open: boolean
  suppliers: { id: string, name: string }[]
  articles: ArticleOption[]
}>()

const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [orderId: string] }>()

const { t } = useI18n()
const toast = useToast()
const { createOrder } = usePurchasing()
const purchasingError = usePurchasingErrors()

interface DraftLine extends OrderLineInput { key: number }

let nextKey = 0

function emptyLine(): DraftLine {
  return { key: nextKey++, item_id: '', quantity_ordered: '', unit_cost: '' }
}

const supplierId = ref('')
const orderDate = ref('')
const expectedDate = ref('')
const notes = ref('')
const lines = ref<DraftLine[]>([emptyLine()])
const isSaving = ref(false)

const supplierOptions = computed(() =>
  props.suppliers.map(supplier => ({ value: supplier.id, label: supplier.name }))
)

const articleOptions = computed(() =>
  props.articles.map(article => ({
    value: article.id,
    label: `${article.code} · ${article.name}`
  }))
)

function unitOf(line: DraftLine): string {
  return props.articles.find(article => article.id === line.item_id)?.base_unit ?? ''
}

const total = computed(() =>
  lines.value.reduce(
    (sum, line) => sum + amount(line.quantity_ordered || '0') * amount(line.unit_cost || '0'),
    0
  )
)

const filledLines = computed(() =>
  lines.value.filter(
    line => line.item_id && amount(line.quantity_ordered || '0') > 0 && line.unit_cost !== ''
  )
)

const canSave = computed(
  () => supplierId.value !== '' && orderDate.value !== '' && filledLines.value.length > 0
)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    supplierId.value = props.suppliers[0]?.id ?? ''
    orderDate.value = new Date().toISOString().slice(0, 10)
    expectedDate.value = ''
    notes.value = ''
    lines.value = [emptyLine()]
  }
)

/**
 * Prefill the price with what the article last cost. It is the number
 * whoever writes the order would otherwise look up, and it is overwritten
 * the moment the supplier quotes a different one.
 */
function onItemChosen(line: DraftLine) {
  const article = props.articles.find(a => a.id === line.item_id)
  if (article?.cost_per_base_unit && line.unit_cost === '') {
    line.unit_cost = article.cost_per_base_unit
  }
}

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  try {
    const response = await createOrder({
      supplier_id: supplierId.value,
      order_date: orderDate.value,
      expected_date: expectedDate.value || null,
      notes: notes.value || null,
      lines: filledLines.value.map(({ item_id, quantity_ordered, unit_cost }) => ({
        item_id,
        quantity_ordered,
        unit_cost
      }))
    })
    toast.add({ title: t('purchasing.orders.created'), color: 'success' })
    emit('saved', response.data.id)
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: purchasingError(error, t('purchasing.orders.saveFailed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('purchasing.orders.addTitle')"
    :ui="{ content: 'max-w-3xl' }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-4">
        <div class="grid gap-4 sm:grid-cols-3">
          <UFormField :label="t('purchasing.form.supplier')">
            <USelect
              v-model="supplierId"
              class="w-full"
              :items="supplierOptions"
              value-key="value"
              :aria-label="t('purchasing.form.supplier')"
            />
          </UFormField>
          <UFormField :label="t('purchasing.form.orderDate')">
            <UInput
              v-model="orderDate"
              class="w-full"
              type="date"
              :aria-label="t('purchasing.form.orderDate')"
            />
          </UFormField>
          <UFormField :label="t('purchasing.form.expectedDate')">
            <UInput
              v-model="expectedDate"
              class="w-full"
              type="date"
              :aria-label="t('purchasing.form.expectedDate')"
            />
          </UFormField>
        </div>

        <div class="space-y-2">
          <p class="text-sm font-medium">
            {{ t('purchasing.form.lines') }}
          </p>
          <div
            v-for="line in lines"
            :key="line.key"
            class="grid items-end gap-2 sm:grid-cols-[1fr_7rem_7rem_auto]"
          >
            <USelect
              v-model="line.item_id"
              :items="articleOptions"
              value-key="value"
              :aria-label="t('purchasing.form.article')"
              @update:model-value="onItemChosen(line)"
            />
            <UInput
              v-model="line.quantity_ordered"
              type="number"
              min="0"
              step="0.001"
              :placeholder="unitOf(line) || t('purchasing.form.quantity')"
              :aria-label="t('purchasing.form.quantity')"
            />
            <UInput
              v-model="line.unit_cost"
              type="number"
              min="0"
              step="0.0001"
              :placeholder="t('purchasing.form.unitCost')"
              :aria-label="t('purchasing.form.unitCost')"
            />
            <UButton
              variant="ghost"
              icon="i-lucide-trash-2"
              :disabled="lines.length === 1"
              :aria-label="t('purchasing.form.removeLine')"
              @click="lines = lines.filter(l => l.key !== line.key)"
            />
          </div>

          <UButton
            variant="ghost"
            icon="i-lucide-plus"
            :label="t('purchasing.form.addLine')"
            @click="lines.push(emptyLine())"
          />
        </div>

        <UFormField :label="t('purchasing.form.notes')">
          <UInput
            v-model="notes"
            class="w-full"
            :aria-label="t('purchasing.form.notes')"
          />
        </UFormField>

        <p class="text-right text-sm">
          {{ t('purchasing.form.total') }}
          <span class="font-semibold tabular-nums">{{ total.toFixed(2) }}</span>
        </p>
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
          :label="t('purchasing.orders.create')"
          :loading="isSaving"
          :disabled="!canSave"
          @click="save"
        />
      </div>
    </template>
  </UModal>
</template>
