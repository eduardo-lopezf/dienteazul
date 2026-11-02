<script setup lang="ts">
/**
 * What one treatment is expected to consume.
 *
 * The treatment list comes from the Treatments App through a contract,
 * so with that App off the picker is empty and the dialog says why
 * rather than pretending (ADR 0037). An existing list keeps its
 * treatment fixed: the list *is* that treatment's, and moving it to
 * another one is writing a different list.
 */
import type { CatalogTreatmentOption, InventoryItem, TreatmentMaterials } from '../composables/useInventory'

const props = defineProps<{
  open: boolean
  /** Null when writing a new list. */
  materials?: TreatmentMaterials | null
  treatments: CatalogTreatmentOption[]
  articles: InventoryItem[]
  /** Treatments that already have a list, so the picker can skip them. */
  taken: string[]
}>()

const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [] }>()

const { t } = useI18n()
const toast = useToast()
const { setMaterials } = useInventory()
const inventoryError = useInventoryErrors()

interface DraftLine { key: number, item_id: string, quantity_base: string | number }

let nextKey = 0

function emptyLine(): DraftLine {
  return { key: nextKey++, item_id: '', quantity_base: '' }
}

const treatmentId = ref('')
const lines = ref<DraftLine[]>([emptyLine()])
const isSaving = ref(false)

const isEditing = computed(() => props.materials != null)

const treatmentOptions = computed(() =>
  props.treatments
    .filter(treatment => !props.taken.includes(treatment.id) || treatment.id === treatmentId.value)
    .map(treatment => ({
      value: treatment.id,
      label: `${treatment.internal_code} · ${treatment.name}`
    }))
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

function tracksLots(line: DraftLine): boolean {
  return props.articles.find(article => article.id === line.item_id)?.tracks_lots ?? false
}

const filledLines = computed(() =>
  lines.value.filter(line => line.item_id && Number(line.quantity_base) > 0)
)

const canSave = computed(() => treatmentId.value !== '' && filledLines.value.length > 0)

watch(
  () => props.open,
  (open) => {
    if (!open) return
    treatmentId.value = props.materials?.catalog_item_id ?? ''
    lines.value = props.materials?.lines.length
      ? props.materials.lines.map(line => ({
          key: nextKey++,
          item_id: line.item_id,
          quantity_base: line.quantity_base
        }))
      : [emptyLine()]
  }
)

async function save() {
  if (!canSave.value) return
  isSaving.value = true
  try {
    await setMaterials(
      treatmentId.value,
      filledLines.value.map(line => ({
        item_id: line.item_id,
        quantity_base: String(line.quantity_base)
      }))
    )
    toast.add({ title: t('inventory.materials.saved'), color: 'success' })
    emit('saved')
    emit('update:open', false)
  } catch (error: unknown) {
    toast.add({ title: inventoryError(error, t('inventory.materials.saveFailed')), color: 'error' })
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="isEditing ? t('inventory.materials.editTitle') : t('inventory.materials.addTitle')"
    :ui="{ content: 'max-w-2xl' }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <p
        v-if="treatments.length === 0"
        class="rounded-token-md border border-default bg-default p-4 text-sm text-subtle"
      >
        {{ t('inventory.materials.noTreatments') }}
      </p>

      <div
        v-else
        class="space-y-4"
      >
        <UFormField
          :label="t('inventory.materials.treatment')"
          :description="isEditing ? t('inventory.materials.treatmentFixed') : undefined"
        >
          <USelect
            v-model="treatmentId"
            class="w-full"
            :items="treatmentOptions"
            value-key="value"
            :disabled="isEditing"
            :aria-label="t('inventory.materials.treatment')"
          />
        </UFormField>

        <div class="space-y-2">
          <p class="text-sm font-medium">
            {{ t('inventory.materials.lines') }}
          </p>

          <div
            v-for="line in lines"
            :key="line.key"
            class="grid items-end gap-2 sm:grid-cols-[1fr_8rem_auto]"
          >
            <div>
              <USelect
                v-model="line.item_id"
                class="w-full"
                :items="articleOptions"
                value-key="value"
                :aria-label="t('inventory.form.item')"
              />
              <p
                v-if="tracksLots(line)"
                class="mt-1 text-xs text-warning"
              >
                {{ t('inventory.materials.lotWarning') }}
              </p>
            </div>
            <UInput
              v-model.number="line.quantity_base"
              type="number"
              min="0"
              step="0.001"
              :placeholder="unitOf(line) || t('inventory.form.quantity')"
              :aria-label="t('inventory.form.quantity')"
            />
            <UButton
              variant="ghost"
              icon="i-lucide-trash-2"
              :disabled="lines.length === 1"
              :aria-label="t('inventory.materials.removeLine')"
              @click="lines = lines.filter(l => l.key !== line.key)"
            />
          </div>

          <UButton
            variant="ghost"
            icon="i-lucide-plus"
            :label="t('inventory.materials.addLine')"
            @click="lines.push(emptyLine())"
          />
        </div>
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
