<script setup lang="ts">
/**
 * Record one movement: stock arriving, stock used, stock thrown away or
 * returned.
 *
 * An adjustment is deliberately absent. It is not a kind of movement
 * somebody picks from a list — it is the outcome of a physical count, and
 * the API refuses it here so the reason stays bound to what was counted
 * (ADR 0065).
 *
 * A lot-tracked article asks for its lot, and offers to create one on the
 * spot: the delivery is in your hands with a batch number printed on it,
 * and sending the user to another screen first is how the lot ends up
 * being skipped.
 */
import type {
  InventoryItem,
  InventoryLocation,
  InventoryLot,
  PostableReason
} from '../composables/useInventory'

const props = defineProps<{
  open: boolean
  items: InventoryItem[]
  locations: InventoryLocation[]
  /** Pre-selected when opened from a stock row. */
  itemId?: string | null
  /** What the button that opened this meant. */
  reason?: PostableReason
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': []
}>()

const { t } = useI18n()
const toast = useToast()
const { recordMovement, lots, createLot } = useInventory()
const inventoryError = useInventoryErrors()

/** Sentinel: Reka UI's SelectItem reserves the empty string. */
const NEW_LOT = '__new__'

const REASONS: PostableReason[] = [
  'purchase_receipt',
  'consumption',
  'expiry_write_off',
  'return'
]

const reasonOptions = computed(() =>
  REASONS.map(value => ({ value, label: t(`inventory.reasons.${value}`) }))
)

const itemOptions = computed(() =>
  props.items.map(item => ({ value: item.id, label: `${item.code} · ${item.name}` }))
)

const locationOptions = computed(() =>
  props.locations.map(location => ({ value: location.id, label: location.name }))
)

const form = ref({
  item_id: '',
  location_id: '',
  lot_id: '',
  quantity_base: '',
  reason: 'purchase_receipt' as PostableReason,
  note: ''
})

const availableLots = ref<InventoryLot[]>([])
const newLotCode = ref('')
const newLotExpiry = ref('')
const isSaving = ref(false)

const selectedItem = computed(() => props.items.find(item => item.id === form.value.item_id))
const needsLot = computed(() => selectedItem.value?.tracks_lots === true)
const isCreatingLot = computed(() => needsLot.value && form.value.lot_id === NEW_LOT)

const lotOptions = computed(() => [
  ...availableLots.value.map(lot => ({
    value: lot.id,
    label: lot.expires_on ? `${lot.lot_code} · ${lot.expires_on}` : lot.lot_code
  })),
  { value: NEW_LOT, label: t('inventory.form.newLot') }
])

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.value = {
      item_id: props.itemId ?? '',
      location_id: props.locations.find(l => l.is_default)?.id ?? props.locations[0]?.id ?? '',
      lot_id: '',
      quantity_base: '',
      reason: props.reason ?? 'purchase_receipt',
      note: ''
    }
    newLotCode.value = ''
    newLotExpiry.value = ''
  }
)

watch(
  () => form.value.item_id,
  async (itemId) => {
    form.value.lot_id = ''
    availableLots.value = []
    if (!itemId || !needsLot.value) return
    availableLots.value = (await lots(itemId)).data
  }
)

const canSave = computed(() => {
  if (!form.value.item_id || !form.value.location_id) return false
  const amount = Number.parseFloat(form.value.quantity_base)
  if (!Number.isFinite(amount) || amount <= 0) return false
  if (!needsLot.value) return true
  return isCreatingLot.value ? newLotCode.value.trim().length > 0 : form.value.lot_id !== ''
})

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  try {
    let lotId: string | null = null
    if (needsLot.value) {
      lotId = isCreatingLot.value
        ? (
            await createLot(form.value.item_id, {
              lot_code: newLotCode.value.trim(),
              expires_on: newLotExpiry.value || null
            })
          ).data.id
        : form.value.lot_id
    }
    await recordMovement({
      item_id: form.value.item_id,
      location_id: form.value.location_id,
      lot_id: lotId,
      quantity_base: form.value.quantity_base,
      reason: form.value.reason,
      note: form.value.note || null
    })
    toast.add({ title: t('inventory.movements.recorded'), color: 'success' })
    emit('saved')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.movements.failed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('inventory.movements.addTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-4">
        <UFormField :label="t('inventory.form.reason')">
          <USelect
            v-model="form.reason"
            class="w-full"
            :items="reasonOptions"
            value-key="value"
            :aria-label="t('inventory.form.reason')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.item')">
          <USelect
            v-model="form.item_id"
            class="w-full"
            :items="itemOptions"
            value-key="value"
            :aria-label="t('inventory.form.item')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.location')">
          <USelect
            v-model="form.location_id"
            class="w-full"
            :items="locationOptions"
            value-key="value"
            :aria-label="t('inventory.form.location')"
          />
        </UFormField>

        <UFormField
          v-if="needsLot"
          :label="t('inventory.form.lot')"
        >
          <USelect
            v-model="form.lot_id"
            class="w-full"
            :items="lotOptions"
            value-key="value"
            :aria-label="t('inventory.form.lot')"
          />
        </UFormField>

        <div
          v-if="isCreatingLot"
          class="grid gap-4 sm:grid-cols-2"
        >
          <UFormField :label="t('inventory.form.lotCode')">
            <UInput
              v-model="newLotCode"
              class="w-full"
              :aria-label="t('inventory.form.lotCode')"
            />
          </UFormField>
          <UFormField
            :label="t('inventory.form.expiresOn')"
            :description="t('inventory.form.expiresOnHint')"
          >
            <UInput
              v-model="newLotExpiry"
              class="w-full"
              type="date"
              :aria-label="t('inventory.form.expiresOn')"
            />
          </UFormField>
        </div>

        <UFormField
          :label="t('inventory.form.quantity')"
          :description="
            selectedItem ? t('inventory.form.quantityIn', { unit: selectedItem.base_unit }) : ''
          "
        >
          <UInput
            v-model="form.quantity_base"
            class="w-full"
            type="number"
            min="0"
            step="0.001"
            :aria-label="t('inventory.form.quantity')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.note')">
          <UInput
            v-model="form.note"
            class="w-full"
            :aria-label="t('inventory.form.note')"
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
          :label="t('inventory.movements.record')"
          :loading="isSaving"
          :disabled="!canSave"
          @click="save"
        />
      </div>
    </template>
  </UModal>
</template>
