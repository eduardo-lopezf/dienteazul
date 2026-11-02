<script setup lang="ts">
/**
 * Create or edit a location: the storeroom, a cabinet, the fridge.
 *
 * `is_default` is where a receipt or a consumption lands when nobody
 * picks a place. Exactly one location holds it; setting it here moves it
 * off whichever location had it, which the service does rather than the
 * form — so two tabs open at once cannot leave the clinic with two
 * defaults or none.
 */
import type { InventoryLocation, LocationInput, LocationKind } from '../composables/useInventory'

const props = defineProps<{
  open: boolean
  /** Null for a new location. */
  location?: InventoryLocation | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': []
}>()

const { t } = useI18n()
const toast = useToast()
const { createLocation, updateLocation } = useInventory()
const inventoryError = useInventoryErrors()

const KINDS: LocationKind[] = ['warehouse', 'cabinet', 'fridge', 'other']

const kindOptions = computed(() =>
  KINDS.map(value => ({ value, label: t(`inventory.locationKinds.${value}`) }))
)

const isEditing = computed(() => props.location != null)

function empty(): LocationInput {
  return { name: '', kind: 'warehouse', is_default: false }
}

const form = ref<LocationInput>(empty())
const isSaving = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.value = props.location
      ? {
          name: props.location.name,
          kind: props.location.kind,
          is_default: props.location.is_default
        }
      : empty()
  }
)

const canSave = computed(() => form.value.name.trim().length > 0)

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  const payload = { ...form.value, name: form.value.name.trim() }
  try {
    if (props.location) {
      await updateLocation(props.location.id, payload)
    } else {
      await createLocation(payload)
    }
    toast.add({
      title: isEditing.value
        ? t('inventory.locations.updated')
        : t('inventory.locations.created'),
      color: 'success'
    })
    emit('saved')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.locations.saveFailed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="isEditing ? t('inventory.locations.editTitle') : t('inventory.locations.addTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-4">
        <UFormField :label="t('inventory.form.name')">
          <UInput
            v-model="form.name"
            class="w-full"
            :aria-label="t('inventory.form.name')"
          />
        </UFormField>

        <UFormField :label="t('inventory.form.kind')">
          <USelect
            v-model="form.kind"
            class="w-full"
            :items="kindOptions"
            value-key="value"
            :aria-label="t('inventory.form.kind')"
          />
        </UFormField>

        <UFormField :description="t('inventory.form.isDefaultHint')">
          <UCheckbox
            v-model="form.is_default"
            :label="t('inventory.form.isDefault')"
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
