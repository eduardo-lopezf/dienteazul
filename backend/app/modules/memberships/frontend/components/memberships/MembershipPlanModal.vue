<script setup lang="ts">
/**
 * A membership plan: its fee and period, a general discount, and the
 * treatments it treats apart — included (N a year, free) or with a
 * discount of their own. Saved whole. Periods already paid keep the terms
 * they were paid on, so editing never changes what a patient has.
 */
import type {
  BenefitKind,
  MembershipPlan,
  MembershipTreatment,
  PlanPeriod
} from '../../composables/useMemberships'
import { treatmentLabel } from '../../composables/useMemberships'

const props = defineProps<{
  open: boolean
  /** The plan to edit; none to create one. */
  plan: MembershipPlan | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': [plan: MembershipPlan]
}>()

const { t, locale } = useI18n()
const toast = useToast()
const { savePlan, listTreatments } = useMemberships()

interface BenefitRow {
  catalog_item_id: string
  kind: BenefitKind
  quantity: string
  discount_percent: string
  label: string
}

const loading = ref(false)
const saving = ref(false)
const name = ref('')
const description = ref('')
const fee = ref('')
const period = ref<PlanPeriod>('monthly')
const generalDiscount = ref('')
const benefits = ref<BenefitRow[]>([])
const treatments = ref<MembershipTreatment[]>([])

const periodOptions = computed(() => [
  { value: 'monthly' as PlanPeriod, label: t('memberships.period.monthly') },
  { value: 'annual' as PlanPeriod, label: t('memberships.period.annual') }
])

const kindOptions = computed(() => [
  { value: 'included' as BenefitKind, label: t('memberships.benefit.included') },
  { value: 'discount' as BenefitKind, label: t('memberships.benefit.discount') }
])

function label(code: string | null | undefined, names: Record<string, string> | null | undefined) {
  return treatmentLabel(locale.value, code, names, t('memberships.unnamedTreatment'))
}

/** The treatments not already in the plan. */
const treatmentOptions = computed(() => {
  const taken = new Set(benefits.value.map(b => b.catalog_item_id))
  return treatments.value
    .filter(item => !taken.has(item.id))
    .map(item => ({ value: item.id, label: label(item.internal_code, item.names) }))
})

async function load() {
  loading.value = true
  const plan = props.plan
  name.value = plan?.name ?? ''
  description.value = plan?.description ?? ''
  fee.value = plan?.fee ?? ''
  period.value = plan?.period ?? 'monthly'
  generalDiscount.value = plan?.general_discount_percent ?? ''
  benefits.value = (plan?.benefits ?? []).map(b => ({
    catalog_item_id: b.catalog_item_id,
    kind: b.kind,
    quantity: b.quantity != null ? String(b.quantity) : '1',
    discount_percent: b.discount_percent ?? '',
    label: label(b.internal_code, b.names)
  }))
  try {
    treatments.value = await listTreatments()
  } catch {
    treatments.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.open, (open) => {
  if (open) load()
}, { immediate: true })

// USelectMenu keeps the chosen item internally even when bound to
// `undefined`, so the picker is remounted after each choice.
const pickerKey = ref(0)

function addBenefit(id: string | undefined) {
  if (!id) return
  pickerKey.value++
  const option = treatmentOptions.value.find(o => o.value === id)
  benefits.value.push({ catalog_item_id: id, kind: 'included', quantity: '1', discount_percent: '', label: option?.label ?? '' })
}

function removeBenefit(id: string) {
  benefits.value = benefits.value.filter(b => b.catalog_item_id !== id)
}

function isPercent(value: string | number): boolean {
  if (value === '' || value === null) return false
  const n = Number(value)
  return Number.isFinite(n) && n >= 0 && n <= 100
}

function isQuantity(value: string | number): boolean {
  const n = Number(value)
  return Number.isInteger(n) && n >= 1 && n <= 100
}

const valid = computed(() =>
  name.value.trim() !== ''
  && fee.value !== '' && Number(fee.value) >= 0
  && (generalDiscount.value === '' || isPercent(generalDiscount.value))
  && benefits.value.every(b => b.kind === 'included' ? isQuantity(b.quantity) : isPercent(b.discount_percent))
)

async function save() {
  if (!valid.value) return
  saving.value = true
  try {
    const saved = await savePlan({
      name: name.value.trim(),
      description: description.value.trim() || null,
      fee: String(fee.value),
      period: period.value,
      general_discount_percent: generalDiscount.value === '' ? null : String(generalDiscount.value),
      benefits: benefits.value.map(b => ({
        catalog_item_id: b.catalog_item_id,
        kind: b.kind,
        quantity: b.kind === 'included' ? Number(b.quantity) : null,
        discount_percent: b.kind === 'discount' ? String(b.discount_percent) : null
      }))
    }, props.plan?.id)
    toast.add({ title: t('memberships.plans.saved'), color: 'success' })
    emit('saved', saved)
    emit('update:open', false)
  } catch {
    toast.add({ title: t('memberships.plans.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="plan ? t('memberships.plans.edit') : t('memberships.plans.new')"
    :description="t('memberships.plans.formDescription')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
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
        data-testid="membership-plan-form"
      >
        <UFormField
          :label="t('memberships.plans.name')"
          required
        >
          <UInput
            v-model="name"
            class="w-full"
            maxlength="120"
            data-testid="membership-plan-name"
          />
        </UFormField>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <UFormField
            :label="t('memberships.plans.fee')"
            required
          >
            <UInput
              v-model="fee"
              class="w-full"
              type="number"
              step="0.01"
              min="0"
              data-testid="membership-plan-fee"
            />
          </UFormField>
          <UFormField :label="t('memberships.plans.period')">
            <USelect
              v-model="period"
              class="w-full"
              :items="periodOptions"
              value-key="value"
              :aria-label="t('memberships.plans.period')"
            />
          </UFormField>
          <UFormField
            :label="t('memberships.plans.generalDiscount')"
            :description="t('memberships.plans.generalDiscountHint')"
          >
            <UInput
              v-model="generalDiscount"
              class="w-full"
              type="number"
              step="0.01"
              min="0"
              max="100"
              :placeholder="t('memberships.plans.noDiscount')"
            >
              <template #trailing>
                %
              </template>
            </UInput>
          </UFormField>
        </div>

        <div class="flex flex-col gap-2">
          <p class="text-body font-medium m-0">
            {{ t('memberships.plans.benefits') }}
          </p>
          <p class="text-caption text-subtle m-0">
            {{ t('memberships.plans.benefitsHint') }}
          </p>

          <ul
            v-if="benefits.length"
            class="flex flex-col gap-2 m-0 p-0 list-none"
          >
            <li
              v-for="benefit in benefits"
              :key="benefit.catalog_item_id"
              class="flex flex-wrap items-center gap-2"
            >
              <span class="min-w-0 flex-1 truncate text-body">{{ benefit.label }}</span>
              <USelect
                v-model="benefit.kind"
                class="w-36"
                :items="kindOptions"
                value-key="value"
                :aria-label="t('memberships.benefit.kindFor', { treatment: benefit.label })"
              />
              <UInput
                v-if="benefit.kind === 'included'"
                v-model="benefit.quantity"
                class="w-28"
                type="number"
                step="1"
                min="1"
                max="100"
                :aria-label="t('memberships.benefit.quantityFor', { treatment: benefit.label })"
              >
                <template #trailing>
                  {{ t('memberships.benefit.perYear') }}
                </template>
              </UInput>
              <UInput
                v-else
                v-model="benefit.discount_percent"
                class="w-28"
                type="number"
                step="0.01"
                min="0"
                max="100"
                :aria-label="t('memberships.benefit.percentFor', { treatment: benefit.label })"
              >
                <template #trailing>
                  %
                </template>
              </UInput>
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-trash-2"
                :aria-label="t('memberships.benefit.remove', { treatment: benefit.label })"
                @click="removeBenefit(benefit.catalog_item_id)"
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
            :placeholder="t('memberships.plans.addTreatment')"
            :aria-label="t('memberships.plans.addTreatment')"
            @update:model-value="addBenefit"
          />
          <p
            v-else
            class="text-caption text-subtle m-0"
          >
            {{ t('memberships.plans.noCatalogue') }}
          </p>
        </div>

        <UFormField :label="t('memberships.plans.description')">
          <UTextarea
            v-model="description"
            class="w-full"
            :rows="2"
          />
        </UFormField>

        <p class="text-caption text-subtle m-0">
          {{ t('memberships.plans.frozenNote') }}
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
          :disabled="!valid || loading"
          data-testid="membership-plan-save"
          @click="save"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
