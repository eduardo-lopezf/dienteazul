<script setup lang="ts">
/**
 * Create or edit an article.
 *
 * Two fields are fixed once the article exists, and the dialog says so
 * rather than letting someone discover it: the **code**, which is how
 * everything else addresses the article, and **lot tracking**, because
 * turning it on would leave the stock already on the shelf in no lot and
 * turning it off would orphan the lots recorded. Both are absent from
 * `PUT /items/{id}` too — this is the API's rule, not the form's.
 */
import type { InventoryItem, ItemCategory, ItemInput } from '../composables/useInventory'

const props = defineProps<{
  open: boolean
  /** Null for a new article. */
  item?: InventoryItem | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': [itemId: string]
}>()

const { t } = useI18n()
const toast = useToast()
const { createItem, updateItem } = useInventory()
const inventoryError = useInventoryErrors()

const isEditing = computed(() => props.item != null)

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

const categoryOptions = computed(() =>
  CATEGORIES.map(value => ({ value, label: t(`inventory.categories.${value}`) }))
)

function empty(): ItemInput {
  return {
    code: '',
    name: '',
    base_unit: '',
    category: 'consumable',
    tracks_lots: false,
    reorder_point: '',
    reorder_quantity: ''
  }
}

function fromItem(item: InventoryItem): ItemInput {
  return {
    code: item.code,
    name: item.name,
    base_unit: item.base_unit,
    category: item.category,
    tracks_lots: item.tracks_lots,
    reorder_point: item.reorder_point ?? '',
    reorder_quantity: item.reorder_quantity ?? '',
    cost_per_base_unit: item.cost_per_base_unit ?? '',
    notes: item.notes ?? ''
  }
}

const form = ref<ItemInput>(empty())
const isSaving = ref(false)

watch(
  () => props.open,
  (open) => {
    if (open) form.value = props.item ? fromItem(props.item) : empty()
  }
)

const canSave = computed(
  () =>
    form.value.code.trim().length > 0
    && form.value.name.trim().length > 0
    && form.value.base_unit.trim().length > 0
)

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  const payload = {
    name: form.value.name.trim(),
    base_unit: form.value.base_unit.trim(),
    category: form.value.category,
    // An empty field is "the clinic has not said", not zero: a reorder
    // point of 0 would mean the article is never low.
    reorder_point: form.value.reorder_point || null,
    reorder_quantity: form.value.reorder_quantity || null,
    cost_per_base_unit: form.value.cost_per_base_unit || null,
    notes: form.value.notes || null
  }
  try {
    const response = props.item
      ? await updateItem(props.item.id, payload)
      : await createItem({
          ...payload,
          code: form.value.code.trim(),
          tracks_lots: form.value.tracks_lots
        })
    toast.add({
      title: isEditing.value ? t('inventory.items.updated') : t('inventory.items.created'),
      color: 'success'
    })
    emit('saved', response.data.id)
    emit('update:open', false)
  } catch (error: unknown) {
    const fallback = isEditing.value
      ? t('inventory.items.updateFailed')
      : t('inventory.items.createFailed')
    toast.add({ title: inventoryError(error, fallback), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="isEditing ? t('inventory.items.editTitle') : t('inventory.items.addTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-4">
        <UFormField
          :label="t('inventory.form.code')"
          :description="isEditing ? t('inventory.form.codeFixed') : undefined"
        >
          <UInput
            v-model="form.code"
            class="w-full"
            :disabled="isEditing"
            :aria-label="t('inventory.form.code')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.name')">
          <UInput
            v-model="form.name"
            class="w-full"
            :aria-label="t('inventory.form.name')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.category')">
          <USelect
            v-model="form.category"
            class="w-full"
            :items="categoryOptions"
            value-key="value"
            :aria-label="t('inventory.form.category')"
          />
        </UFormField>

        <UFormField
          :label="t('inventory.form.baseUnit')"
          :description="t('inventory.form.baseUnitHint')"
        >
          <UInput
            v-model="form.base_unit"
            class="w-full"
            :aria-label="t('inventory.form.baseUnit')"
          />
        </UFormField>

        <div class="grid gap-4 sm:grid-cols-2">
          <UFormField :label="t('inventory.form.reorderPoint')">
            <UInput
              v-model.nullable.optional="form.reorder_point"
              class="w-full"
              type="number"
              min="0"
              step="0.001"
              :aria-label="t('inventory.form.reorderPoint')"
            />
          </UFormField>

          <UFormField :label="t('inventory.form.reorderQuantity')">
            <UInput
              v-model.nullable.optional="form.reorder_quantity"
              class="w-full"
              type="number"
              min="0"
              step="0.001"
              :aria-label="t('inventory.form.reorderQuantity')"
            />
          </UFormField>
        </div>

        <UFormField
          :description="
            isEditing ? t('inventory.form.tracksLotsFixed') : t('inventory.form.tracksLotsHint')
          "
        >
          <UCheckbox
            v-model="form.tracks_lots"
            :disabled="isEditing"
            :label="t('inventory.form.tracksLots')"
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
          :label="t('common.save')"
          :loading="isSaving"
          :disabled="!canSave"
          @click="save"
        />
      </div>
    </template>
  </UModal>
</template>
