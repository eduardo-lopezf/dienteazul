<script setup lang="ts">
/** Create or edit a supplier. */
import type { Supplier, SupplierInput } from '../composables/usePurchasing'

const props = defineProps<{ open: boolean, supplier?: Supplier | null }>()

const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [] }>()

const { t } = useI18n()
const toast = useToast()
const { createSupplier, updateSupplier } = usePurchasing()
const purchasingError = usePurchasingErrors()

const isEditing = computed(() => props.supplier != null)

function empty(): SupplierInput {
  return { name: '', tax_id: '', contact_name: '', email: '', phone: '', notes: '' }
}

const form = ref<SupplierInput>(empty())
const isSaving = ref(false)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    form.value = props.supplier
      ? {
          name: props.supplier.name,
          tax_id: props.supplier.tax_id ?? '',
          contact_name: props.supplier.contact_name ?? '',
          email: props.supplier.email ?? '',
          phone: props.supplier.phone ?? '',
          notes: props.supplier.notes ?? ''
        }
      : empty()
  }
)

const canSave = computed(() => form.value.name.trim().length > 0)

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  const payload = {
    ...form.value,
    name: form.value.name.trim(),
    // Empty is "not recorded", not an empty string on file.
    tax_id: form.value.tax_id || null,
    contact_name: form.value.contact_name || null,
    email: form.value.email || null,
    phone: form.value.phone || null,
    notes: form.value.notes || null
  }
  try {
    if (props.supplier) {
      await updateSupplier(props.supplier.id, payload)
    } else {
      await createSupplier(payload)
    }
    toast.add({
      title: isEditing.value
        ? t('purchasing.suppliers.updated')
        : t('purchasing.suppliers.created'),
      color: 'success'
    })
    emit('saved')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({
      title: purchasingError(error, t('purchasing.suppliers.saveFailed')),
      color: 'error'
    })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="isEditing ? t('purchasing.suppliers.editTitle') : t('purchasing.suppliers.addTitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <div class="space-y-4">
        <UFormField :label="t('purchasing.form.name')">
          <UInput
            v-model="form.name"
            class="w-full"
            :aria-label="t('purchasing.form.name')"
          />
        </UFormField>

        <div class="grid gap-4 sm:grid-cols-2">
          <UFormField :label="t('purchasing.form.taxId')">
            <UInput
              v-model="form.tax_id"
              class="w-full"
              :aria-label="t('purchasing.form.taxId')"
            />
          </UFormField>
          <UFormField :label="t('purchasing.form.contactName')">
            <UInput
              v-model="form.contact_name"
              class="w-full"
              :aria-label="t('purchasing.form.contactName')"
            />
          </UFormField>
        </div>

        <div class="grid gap-4 sm:grid-cols-2">
          <UFormField :label="t('purchasing.form.email')">
            <UInput
              v-model="form.email"
              class="w-full"
              type="email"
              :aria-label="t('purchasing.form.email')"
            />
          </UFormField>
          <UFormField :label="t('purchasing.form.phone')">
            <UInput
              v-model="form.phone"
              class="w-full"
              :aria-label="t('purchasing.form.phone')"
            />
          </UFormField>
        </div>

        <UFormField :label="t('purchasing.form.notes')">
          <UInput
            v-model="form.notes"
            class="w-full"
            :aria-label="t('purchasing.form.notes')"
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
