<script setup lang="ts">
/**
 * Patient record → Administración → Facturas: what the SAT needs of the
 * patient's billing RFC (``patient.detail.administracion.billing``).
 *
 * The profile is kept by RFC, not by patient: a relative who pays with
 * their own RFC is asked once. The RFC itself is the patient's billing
 * data, edited in the patient's information. Shown only in Mexican
 * clinics.
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorMessage } from '~~/app/utils/error'
import { CFDI_USES, PUBLIC_RFC, TAX_REGIMES } from '../../composables/useSatCfdi'
import type { SatReceiver } from '../../composables/useSatCfdi'

const props = defineProps<{ ctx: { patient?: PatientExtended | null, patientId: string } }>()

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { currentClinic } = useClinic()
const sat = useSatCfdi()

// `country` is set from Clinic info; the shared `Clinic` type does not list it.
const inMexico = computed(() =>
  (currentClinic.value?.settings as { country?: string } | undefined)?.country === 'MX')
const canWrite = computed(() => can(PERMISSIONS.satCfdi.receiverWrite))
const rfc = computed(() => (props.ctx.patient?.billing_tax_id ?? '').trim().toUpperCase())
const isPublic = computed(() => rfc.value === PUBLIC_RFC)

const profile = ref<SatReceiver | null>(null)
const loading = ref(false)
const editing = ref(false)
const saving = ref(false)

const taxRegime = ref<string | undefined>(undefined)
const taxZipCode = ref('')
const cfdiUse = ref('D01')

const regimeItems = TAX_REGIMES.map(r => ({ value: r.value, label: `${r.value} — ${r.label}` }))
const useItems = CFDI_USES.map(u => ({ value: u.value, label: `${u.value} — ${u.label}` }))

function label(items: { value: string, label: string }[], value: string): string {
  return items.find(item => item.value === value)?.label ?? value
}

async function load() {
  profile.value = null
  if (!inMexico.value || !rfc.value || isPublic.value) return
  loading.value = true
  try {
    profile.value = await sat.getReceiver(rfc.value)
  } catch {
    profile.value = null
  } finally {
    loading.value = false
  }
}

function edit() {
  taxRegime.value = profile.value?.tax_regime
  taxZipCode.value = profile.value?.tax_zip_code ?? ''
  cfdiUse.value = profile.value?.cfdi_use ?? 'D01'
  editing.value = true
}

const zipValid = computed(() => /^\d{5}$/.test(taxZipCode.value))
const canSave = computed(() => !!taxRegime.value && zipValid.value && !!cfdiUse.value && !saving.value)

async function save() {
  if (!canSave.value || !taxRegime.value) return
  saving.value = true
  try {
    profile.value = await sat.saveReceiver(rfc.value, {
      tax_regime: taxRegime.value,
      tax_zip_code: taxZipCode.value,
      cfdi_use: cfdiUse.value
    })
    editing.value = false
    toast.add({ title: t('satCfdi.receiver.saved'), color: 'success' })
  } catch (e: unknown) {
    toast.add({ title: t('errors.updateFailed'), description: errorMessage(e, ''), color: 'error' })
  } finally {
    saving.value = false
  }
}

watch(rfc, load)
watch(inMexico, load)
onMounted(load)
</script>

<template>
  <UCard
    v-if="inMexico"
    class="mb-4"
    data-testid="sat-fiscal-profile"
  >
    <template #header>
      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 min-w-0">
          <UIcon
            name="i-lucide-landmark"
            class="w-5 h-5 shrink-0"
            aria-hidden="true"
          />
          <h3 class="font-semibold truncate">
            {{ t('satCfdi.receiver.title') }}
          </h3>
        </div>
        <UButton
          v-if="canWrite && rfc && !isPublic && !editing && !loading"
          variant="soft"
          color="neutral"
          icon="i-lucide-pencil"
          size="sm"
          data-testid="sat-fiscal-edit"
          @click="edit"
        >
          {{ profile ? t('common.edit') : t('satCfdi.receiver.add') }}
        </UButton>
      </div>
    </template>

    <p
      v-if="!rfc"
      class="text-sm text-muted"
    >
      {{ t('satCfdi.receiver.noRfc') }}
    </p>

    <p
      v-else-if="isPublic"
      class="text-sm text-muted"
    >
      {{ t('satCfdi.receiver.public') }}
    </p>

    <form
      v-else-if="editing"
      class="space-y-4"
      @submit.prevent="save"
    >
      <p class="text-sm">
        RFC <span class="font-mono">{{ rfc }}</span>
      </p>
      <UFormField :label="t('satCfdi.receiver.taxRegime')">
        <USelect
          v-model="taxRegime"
          :items="regimeItems"
          value-key="value"
          :placeholder="t('satCfdi.settings.taxRegimePlaceholder')"
          class="w-full"
          data-testid="sat-fiscal-regime"
        />
      </UFormField>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <UFormField
          :label="t('satCfdi.receiver.taxZipCode')"
          :help="t('satCfdi.receiver.taxZipCodeHint')"
          :error="taxZipCode && !zipValid ? t('satCfdi.settings.postalCodeInvalid') : undefined"
        >
          <UInput
            v-model="taxZipCode"
            inputmode="numeric"
            maxlength="5"
            class="w-32"
            data-testid="sat-fiscal-zip"
          />
        </UFormField>
        <UFormField :label="t('satCfdi.receiver.cfdiUse')">
          <USelect
            v-model="cfdiUse"
            :items="useItems"
            value-key="value"
            class="w-full"
            data-testid="sat-fiscal-use"
          />
        </UFormField>
      </div>
      <div class="flex flex-wrap gap-2">
        <UButton
          type="submit"
          :loading="saving"
          :disabled="!canSave"
          data-testid="sat-fiscal-save"
        >
          {{ t('satCfdi.settings.save') }}
        </UButton>
        <UButton
          variant="ghost"
          color="neutral"
          @click="editing = false"
        >
          {{ t('common.cancel') }}
        </UButton>
      </div>
    </form>

    <template v-else-if="!loading">
      <dl
        v-if="profile"
        class="grid grid-cols-1 md:grid-cols-3 gap-x-6 gap-y-3 text-sm"
      >
        <div>
          <dt class="text-muted text-xs">
            RFC
          </dt>
          <dd class="font-mono">
            {{ profile.rfc }}
          </dd>
        </div>
        <div>
          <dt class="text-muted text-xs">
            {{ t('satCfdi.receiver.taxRegime') }}
          </dt>
          <dd>{{ label(regimeItems, profile.tax_regime) }}</dd>
        </div>
        <div>
          <dt class="text-muted text-xs">
            {{ t('satCfdi.receiver.taxZipCode') }}
          </dt>
          <dd>{{ profile.tax_zip_code }}</dd>
        </div>
        <div class="md:col-span-3">
          <dt class="text-muted text-xs">
            {{ t('satCfdi.receiver.cfdiUse') }}
          </dt>
          <dd>{{ label(useItems, profile.cfdi_use) }}</dd>
        </div>
      </dl>
      <UAlert
        v-else
        color="warning"
        variant="soft"
        icon="i-lucide-alert-triangle"
        :title="t('satCfdi.receiver.missing', { rfc })"
        :description="t('satCfdi.receiver.missingHint')"
        data-testid="sat-fiscal-missing"
      />
    </template>
  </UCard>
</template>
