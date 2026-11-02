<script setup lang="ts">
/**
 * Record a device placed in this patient.
 *
 * The patient is given, never picked: the dialog is only ever opened
 * from their own record. That is what keeps this module free of any
 * call into the Patients App.
 *
 * Only lot-tracked articles can be chosen, and the lot is required —
 * a trace without a batch traces nothing, which is the whole point of
 * the table behind it.
 */
import type { InventoryItem, InventoryLot } from '../composables/useInventory'

const props = defineProps<{ open: boolean, patientId: string }>()

const emit = defineEmits<{ 'update:open': [value: boolean], 'recorded': [] }>()

const { t } = useI18n()
const toast = useToast()
const { items: listItems, lots: listLots, createLot, recordImplant } = useInventory()
const inventoryError = useInventoryErrors()

/** Sentinel: Reka UI's SelectItem reserves the empty string. */
const NEW_LOT = '__new__'

const articles = ref<InventoryItem[]>([])
const availableLots = ref<InventoryLot[]>([])
const itemId = ref('')
const lotId = ref('')
const newLotCode = ref('')
const newLotExpiry = ref('')
const placedOn = ref('')
const toothNumber = ref<string | number>('')
const serialNumber = ref('')
const notes = ref('')
const isSaving = ref(false)

/** Only what can actually be traced. */
const articleOptions = computed(() =>
  articles.value
    .filter(article => article.tracks_lots)
    .map(article => ({ value: article.id, label: `${article.code} · ${article.name}` }))
)

const isCreatingLot = computed(() => lotId.value === NEW_LOT)

const lotOptions = computed(() => [
  ...availableLots.value.map(lot => ({
    value: lot.id,
    label: lot.expires_on ? `${lot.lot_code} · ${lot.expires_on}` : lot.lot_code
  })),
  { value: NEW_LOT, label: t('inventory.implants.newLot') }
])

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    itemId.value = ''
    lotId.value = ''
    newLotCode.value = ''
    newLotExpiry.value = ''
    placedOn.value = new Date().toISOString().slice(0, 10)
    toothNumber.value = ''
    serialNumber.value = ''
    notes.value = ''
    availableLots.value = []
    articles.value = (await listItems()).data
  }
)

watch(itemId, async (value) => {
  lotId.value = ''
  availableLots.value = value ? (await listLots(value)).data : []
})

const canSave = computed(() => {
  if (!itemId.value || !placedOn.value) return false
  return isCreatingLot.value ? newLotCode.value.trim().length > 0 : lotId.value !== ''
})

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  try {
    const resolvedLot = isCreatingLot.value
      ? (
          await createLot(itemId.value, {
            lot_code: newLotCode.value.trim(),
            expires_on: newLotExpiry.value || null
          })
        ).data.id
      : lotId.value

    await recordImplant({
      patient_id: props.patientId,
      item_id: itemId.value,
      lot_id: resolvedLot,
      placed_on: placedOn.value,
      tooth_number: toothNumber.value === '' ? null : Number(toothNumber.value),
      serial_number: serialNumber.value || null,
      notes: notes.value || null
    })
    toast.add({ title: t('inventory.implants.recorded'), color: 'success' })
    emit('recorded')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.implants.failed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('inventory.implants.addTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <p
        v-if="articleOptions.length === 0"
        class="rounded-token-md border border-default bg-default p-4 text-sm text-subtle"
      >
        {{ t('inventory.implants.noTraceableArticles') }}
      </p>

      <div
        v-else
        class="space-y-4"
      >
        <UFormField :label="t('inventory.implants.device')">
          <USelect
            v-model="itemId"
            class="w-full"
            :items="articleOptions"
            value-key="value"
            :aria-label="t('inventory.implants.device')"
          />
        </UFormField>

        <UFormField
          v-if="itemId"
          :label="t('inventory.lot')"
          :description="t('inventory.implants.lotRequired')"
        >
          <USelect
            v-model="lotId"
            class="w-full"
            :items="lotOptions"
            value-key="value"
            :aria-label="t('inventory.lot')"
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
          <UFormField :label="t('inventory.form.expiresOn')">
            <UInput
              v-model="newLotExpiry"
              class="w-full"
              type="date"
              :aria-label="t('inventory.form.expiresOn')"
            />
          </UFormField>
        </div>

        <div class="grid gap-4 sm:grid-cols-3">
          <UFormField :label="t('inventory.implants.placedOn')">
            <UInput
              v-model="placedOn"
              class="w-full"
              type="date"
              :aria-label="t('inventory.implants.placedOn')"
            />
          </UFormField>
          <UFormField :label="t('inventory.implants.tooth')">
            <UInput
              v-model="toothNumber"
              class="w-full"
              type="number"
              min="11"
              max="85"
              :aria-label="t('inventory.implants.tooth')"
            />
          </UFormField>
          <UFormField :label="t('inventory.implants.serial')">
            <UInput
              v-model="serialNumber"
              class="w-full"
              :aria-label="t('inventory.implants.serial')"
            />
          </UFormField>
        </div>

        <UFormField :label="t('inventory.form.note')">
          <UInput
            v-model="notes"
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
          :label="t('inventory.implants.record')"
          :loading="isSaving"
          :disabled="!canSave"
          @click="save"
        />
      </div>
    </template>
  </UModal>
</template>
