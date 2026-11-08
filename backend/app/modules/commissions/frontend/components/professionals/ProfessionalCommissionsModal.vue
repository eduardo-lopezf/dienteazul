<script setup lang="ts">
/**
 * What the clinic pays one professional: a general percentage, the figure
 * it is taken on, and a different percentage for the treatments that need
 * one. Saved whole — the form is the agreement.
 */
import type { Professional } from '~~/app/types'
import type { CommissionBasis, CommissionTreatment } from '../../composables/useCommissions'

const props = defineProps<{
  open: boolean
  professional: Professional
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const { t, locale } = useI18n()
const toast = useToast()
const { fetchAgreement, saveAgreement, fetchTreatments } = useCommissions()

interface RateRow { catalog_item_id: string, percent: string, label: string }

const loading = ref(false)
const saving = ref(false)
const basis = ref<CommissionBasis>('collected')
const defaultPercent = ref('')
const notes = ref('')
const rates = ref<RateRow[]>([])
const treatments = ref<CommissionTreatment[]>([])

const basisOptions = computed(() => [
  { value: 'collected' as CommissionBasis, label: t('commissions.basis.collected') },
  { value: 'earned' as CommissionBasis, label: t('commissions.basis.earned') }
])

function treatmentLabel(code: string | null | undefined, names: Record<string, string> | null | undefined): string {
  const name = names ? (names[locale.value] || names.es || names.en) : undefined
  if (!code && !name) return t('commissions.unnamedTreatment')
  return [code, name].filter(Boolean).join(' · ')
}

/** The treatments not already carrying a percentage of their own. */
const treatmentOptions = computed(() => {
  const taken = new Set(rates.value.map(r => r.catalog_item_id))
  return treatments.value
    .filter(item => !taken.has(item.id))
    .map(item => ({ value: item.id, label: treatmentLabel(item.internal_code, item.names) }))
})

async function load() {
  loading.value = true
  try {
    const [agreement, items] = await Promise.all([
      fetchAgreement(props.professional.id),
      fetchTreatments()
    ])
    treatments.value = items
    basis.value = agreement.basis
    defaultPercent.value = agreement.default_percent ?? ''
    notes.value = agreement.notes ?? ''
    rates.value = agreement.rates.map(rate => ({
      catalog_item_id: rate.catalog_item_id,
      percent: rate.percent,
      label: treatmentLabel(rate.internal_code, rate.names)
    }))
  } catch {
    toast.add({ title: t('commissions.loadFailed'), color: 'error' })
    emit('update:open', false)
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) load()
})

/** The picker holds no value of its own: choosing adds a row and it reads empty again. */
// USelectMenu keeps the chosen item internally even when bound to
// `undefined`, so the picker is remounted after each choice.
const pickerKey = ref(0)

function addRate(id: string | undefined) {
  if (!id) return
  pickerKey.value++
  const option = treatmentOptions.value.find(o => o.value === id)
  rates.value.push({ catalog_item_id: id, percent: defaultPercent.value ? String(defaultPercent.value) : '', label: option?.label ?? '' })
}

function removeRate(id: string) {
  rates.value = rates.value.filter(r => r.catalog_item_id !== id)
}

function isPercent(value: string | number): boolean {
  if (value === '' || value === null) return false
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 && n <= 100
}

const valid = computed(() =>
  (defaultPercent.value === '' || isPercent(defaultPercent.value))
  && rates.value.every(r => isPercent(r.percent))
)

async function save() {
  if (!valid.value) return
  saving.value = true
  try {
    await saveAgreement(props.professional.id, {
      basis: basis.value,
      default_percent: defaultPercent.value === '' ? null : String(defaultPercent.value),
      rates: rates.value.map(r => ({ catalog_item_id: r.catalog_item_id, percent: String(r.percent) })),
      notes: notes.value.trim() || null
    })
    toast.add({ title: t('commissions.saved'), color: 'success' })
    emit('update:open', false)
  } catch {
    toast.add({ title: t('commissions.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('commissions.title', { name: professional.full_name })"
    :description="t('commissions.description')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <!-- The trigger: whatever opens it (the button on the card). -->
    <slot />
    <template #body>
      <div
        v-if="loading"
        class="flex justify-center py-6"
      >
        <UIcon
          name="i-lucide-loader-2"
          class="w-5 h-5 animate-spin"
        />
      </div>
      <div
        v-else
        class="flex flex-col gap-4"
      >
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <UFormField
            :label="t('commissions.defaultPercent')"
            :description="t('commissions.defaultPercentHint')"
          >
            <UInput
              v-model="defaultPercent"
              class="w-full"
              type="number"
              step="0.01"
              min="0"
              max="100"
              :placeholder="t('commissions.none')"
            >
              <template #trailing>
                %
              </template>
            </UInput>
          </UFormField>
          <UFormField
            :label="t('commissions.basisLabel')"
            :description="t('commissions.basisHint')"
          >
            <USelect
              v-model="basis"
              class="w-full"
              :items="basisOptions"
              value-key="value"
              :aria-label="t('commissions.basisLabel')"
            />
          </UFormField>
        </div>

        <div class="flex flex-col gap-2">
          <p class="text-body font-medium m-0">
            {{ t('commissions.exceptions') }}
          </p>
          <p class="text-caption text-subtle m-0">
            {{ t('commissions.exceptionsHint') }}
          </p>

          <ul
            v-if="rates.length"
            class="flex flex-col gap-2 m-0 p-0 list-none"
          >
            <li
              v-for="rate in rates"
              :key="rate.catalog_item_id"
              class="flex items-center gap-2"
            >
              <span class="min-w-0 flex-1 truncate text-body">{{ rate.label }}</span>
              <UInput
                v-model="rate.percent"
                class="w-28"
                type="number"
                step="0.01"
                min="0"
                max="100"
                :aria-label="t('commissions.percentFor', { treatment: rate.label })"
              >
                <template #trailing>
                  %
                </template>
              </UInput>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-trash-2"
                :aria-label="t('commissions.remove', { treatment: rate.label })"
                @click="removeRate(rate.catalog_item_id)"
              />
            </li>
          </ul>

          <USelectMenu
            v-if="treatments.length"
            :key="pickerKey"
            :model-value="undefined"
            class="w-full"
            :items="treatmentOptions"
            value-key="value"
            icon="i-lucide-plus"
            :placeholder="t('commissions.addTreatment')"
            :aria-label="t('commissions.addTreatment')"
            @update:model-value="addRate"
          />
          <p
            v-else
            class="text-caption text-subtle m-0"
          >
            {{ t('commissions.noCatalogue') }}
          </p>
        </div>

        <UFormField :label="t('commissions.notes')">
          <UTextarea
            v-model="notes"
            class="w-full"
            :rows="2"
          />
        </UFormField>

        <p class="text-caption text-subtle m-0">
          {{ t('commissions.frozenNote') }}
        </p>
      </div>
    </template>
    <template #footer>
      <div class="flex justify-end gap-2 w-full">
        <UButton
          color="neutral"
          variant="ghost"
          @click="emit('update:open', false)"
        >
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          :loading="saving"
          :disabled="loading || !valid"
          @click="save"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
