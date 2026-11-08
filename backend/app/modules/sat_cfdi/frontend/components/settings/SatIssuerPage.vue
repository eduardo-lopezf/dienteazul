<script setup lang="ts">
/**
 * Settings → Billing → SAT: the clinic as issuer of CFDIs.
 *
 * Top-down: whether the clinic can issue (and what is missing), the
 * issuer's RFC and legal name (the clinic's own, edited in Clinic info),
 * the SAT's settings, and the CSD.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import { errorMessage } from '~~/app/utils/error'
import { TAX_REGIMES } from '../../composables/useSatCfdi'
import type { SatEnvironment, SatSettings } from '../../composables/useSatCfdi'

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const sat = useSatCfdi()

const canConfigure = computed(() => can(PERMISSIONS.satCfdi.settingsConfigure))

const settings = ref<SatSettings | null>(null)
const loadFailed = ref(false)

const taxRegime = ref<string | undefined>(undefined)
const postalCode = ref('')
const environment = ref<SatEnvironment>('sandbox')
const productCode = ref('')
const unitCode = ref('E48')
const stampDelay = ref(30)
const saving = ref(false)

const accounts = reactive<Record<SatEnvironment, { user: string, password: string, show: boolean, saving: boolean }>>({
  sandbox: { user: '', password: '', show: false, saving: false },
  production: { user: '', password: '', show: false, saving: false }
})

async function saveAccount(environment: SatEnvironment) {
  const account = accounts[environment]
  if (!account.user.trim()) return
  account.saving = true
  try {
    apply(await sat.saveCredentials(environment, account.user.trim(), account.password || null))
    toast.add({ title: t('satCfdi.facturama.saved'), color: 'success' })
  } catch (e: unknown) {
    toast.add({ title: t('errors.updateFailed'), description: errorMessage(e, ''), color: 'error' })
  } finally {
    account.saving = false
  }
}

const cer = ref<File | null>(null)
const key = ref<File | null>(null)
const password = ref('')
const showPassword = ref(false)
const uploading = ref(false)
const uploadError = ref<string | null>(null)
const cerInput = ref<HTMLInputElement | null>(null)
const keyInput = ref<HTMLInputElement | null>(null)

const regimeItems = TAX_REGIMES.map(r => ({ value: r.value, label: `${r.value} — ${r.label}` }))
const environmentItems = computed(() => (['sandbox', 'production'] as const).map(value => ({
  value,
  label: t(`satCfdi.settings.environment.${value}`),
  description: t(`satCfdi.settings.environment.${value}Hint`)
})))

function apply(next: SatSettings) {
  settings.value = next
  taxRegime.value = next.tax_regime ?? undefined
  postalCode.value = next.expedition_postal_code ?? ''
  environment.value = next.environment
  productCode.value = next.product_code ?? ''
  unitCode.value = next.unit_code
  stampDelay.value = next.stamp_delay_minutes
  for (const environment of ['sandbox', 'production'] as const) {
    accounts[environment].user = next.facturama[environment].user ?? ''
    accounts[environment].password = ''
  }
}

async function load() {
  try {
    apply(await sat.getSettings())
    loadFailed.value = false
  } catch {
    loadFailed.value = true
  }
}

const postalCodeValid = computed(() => /^\d{5}$/.test(postalCode.value))
const productCodeValid = computed(() => productCode.value === '' || /^\d{8}$/.test(productCode.value))
const unitCodeValid = computed(() => /^[A-Z0-9]{2,3}$/i.test(unitCode.value))
const stampDelayValid = computed(() => Number.isInteger(stampDelay.value) && stampDelay.value >= 0 && stampDelay.value <= 720)
const canSave = computed(() => canConfigure.value && !!taxRegime.value && postalCodeValid.value
  && productCodeValid.value && unitCodeValid.value && stampDelayValid.value && !saving.value)

async function save() {
  if (!canSave.value || !taxRegime.value) return
  saving.value = true
  try {
    apply(await sat.saveSettings({
      tax_regime: taxRegime.value,
      expedition_postal_code: postalCode.value,
      environment: environment.value,
      product_code: productCode.value || null,
      unit_code: unitCode.value.toUpperCase(),
      stamp_delay_minutes: stampDelay.value
    }))
    toast.add({ title: t('satCfdi.settings.saved'), color: 'success' })
  } catch (e: unknown) {
    toast.add({ title: t('errors.updateFailed'), description: errorMessage(e, ''), color: 'error' })
  } finally {
    saving.value = false
  }
}

function pick(target: 'cer' | 'key', event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  if (target === 'cer') cer.value = file
  else key.value = file
  uploadError.value = null
  // Picking the same file again still fires `change`.
  input.value = ''
}

const canUpload = computed(() => canConfigure.value && !!cer.value && !!key.value && password.value.length > 0 && !uploading.value)

async function upload() {
  if (!canUpload.value || !cer.value || !key.value) return
  uploading.value = true
  uploadError.value = null
  try {
    await sat.uploadCertificate(cer.value, key.value, password.value)
    cer.value = null
    key.value = null
    password.value = ''
    toast.add({ title: t('satCfdi.certificate.uploaded'), color: 'success' })
    await load()
  } catch (e: unknown) {
    uploadError.value = errorMessage(e, t('satCfdi.certificate.uploadFailed'))
  } finally {
    uploading.value = false
  }
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(iso))
}

const daysLeft = computed(() => {
  const until = settings.value?.certificate?.valid_until
  if (!until) return null
  return Math.floor((new Date(until).getTime() - Date.now()) / 86_400_000)
})

const registered = computed(() => {
  const s = settings.value
  return !!s?.certificate && s.certificate.registered_in.includes(s.environment)
})
const registering = ref(false)

async function register() {
  registering.value = true
  try {
    await sat.registerCertificate()
    toast.add({ title: t('satCfdi.certificate.registered'), color: 'success' })
  } catch (e: unknown) {
    toast.add({ title: t('satCfdi.certificate.registerFailed'), description: errorMessage(e, ''), color: 'error' })
  } finally {
    registering.value = false
    await load()
  }
}

const expiry = computed(() => {
  const days = daysLeft.value
  if (days === null) return null
  if (days < 0) return { color: 'error' as const, label: t('satCfdi.certificate.expired') }
  if (days < 30) return { color: 'warning' as const, label: t('satCfdi.certificate.expiresIn', { days }) }
  return { color: 'success' as const, label: t('satCfdi.certificate.validFor', { days }) }
})

onMounted(load)
</script>

<template>
  <div class="space-y-6 max-w-3xl">
    <UAlert
      v-if="loadFailed"
      color="error"
      variant="soft"
      icon="i-lucide-alert-triangle"
      :title="t('errors.loadFailed')"
    />

    <template v-else-if="settings">
      <!-- Can the clinic issue? -->
      <UAlert
        v-if="settings.ready"
        color="success"
        variant="soft"
        icon="i-lucide-shield-check"
        :title="t('satCfdi.status.ready')"
        :description="settings.environment === 'sandbox' ? t('satCfdi.status.sandbox') : t('satCfdi.status.production')"
        data-testid="sat-status"
      />
      <UAlert
        v-else
        color="warning"
        variant="soft"
        icon="i-lucide-alert-triangle"
        :title="t('satCfdi.status.notReady')"
        :description="settings.missing ?? undefined"
        data-testid="sat-status"
      />

      <!-- The issuer: the clinic's own -->
      <UCard>
        <template #header>
          <h2 class="font-semibold">
            {{ t('satCfdi.issuer.title') }}
          </h2>
        </template>
        <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt class="text-muted text-xs">
              {{ t('satCfdi.issuer.rfc') }}
            </dt>
            <dd class="font-mono">
              {{ settings.rfc || '—' }}
            </dd>
          </div>
          <div>
            <dt class="text-muted text-xs">
              {{ t('satCfdi.issuer.legalName') }}
            </dt>
            <dd>{{ settings.legal_name || '—' }}</dd>
          </div>
        </dl>
        <p class="text-xs text-muted mt-4">
          {{ t('satCfdi.issuer.hint') }}
          <NuxtLink
            to="/settings/general/clinic"
            class="text-primary hover:underline"
          >
            {{ t('satCfdi.issuer.edit') }}
          </NuxtLink>
        </p>
      </UCard>

      <!-- What the SAT adds -->
      <UCard>
        <template #header>
          <h2 class="font-semibold">
            {{ t('satCfdi.settings.formTitle') }}
          </h2>
        </template>
        <form
          class="space-y-5"
          @submit.prevent="save"
        >
          <UFormField
            :label="t('satCfdi.settings.taxRegime')"
            :help="t('satCfdi.settings.taxRegimeHint')"
          >
            <USelect
              v-model="taxRegime"
              :items="regimeItems"
              value-key="value"
              :placeholder="t('satCfdi.settings.taxRegimePlaceholder')"
              :disabled="!canConfigure"
              class="w-full"
              data-testid="sat-tax-regime"
            />
          </UFormField>

          <UFormField
            :label="t('satCfdi.settings.postalCode')"
            :help="t('satCfdi.settings.postalCodeHint')"
            :error="postalCode && !postalCodeValid ? t('satCfdi.settings.postalCodeInvalid') : undefined"
          >
            <UInput
              v-model="postalCode"
              inputmode="numeric"
              maxlength="5"
              autocomplete="postal-code"
              :disabled="!canConfigure"
              class="w-32"
              data-testid="sat-postal-code"
            />
          </UFormField>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField
              :label="t('satCfdi.settings.productCode')"
              :help="t('satCfdi.settings.productCodeHint')"
              :error="!productCodeValid ? t('satCfdi.settings.productCodeInvalid') : undefined"
            >
              <UInput
                v-model="productCode"
                inputmode="numeric"
                maxlength="8"
                :disabled="!canConfigure"
                class="w-40"
                data-testid="sat-product-code"
              />
            </UFormField>
            <UFormField
              :label="t('satCfdi.settings.unitCode')"
              :help="t('satCfdi.settings.unitCodeHint')"
              :error="!unitCodeValid ? t('satCfdi.settings.unitCodeInvalid') : undefined"
            >
              <UInput
                v-model="unitCode"
                maxlength="3"
                :disabled="!canConfigure"
                class="w-24 uppercase"
                data-testid="sat-unit-code"
              />
            </UFormField>
          </div>

          <UFormField
            :label="t('satCfdi.settings.stampDelay')"
            :help="t('satCfdi.settings.stampDelayHint')"
            :error="!stampDelayValid ? t('satCfdi.settings.stampDelayInvalid') : undefined"
          >
            <UInputNumber
              v-model="stampDelay"
              :min="0"
              :max="720"
              :disabled="!canConfigure"
              class="w-32"
              data-testid="sat-stamp-delay"
            />
          </UFormField>

          <UFormField :label="t('satCfdi.settings.environment.label')">
            <URadioGroup
              v-model="environment"
              :items="environmentItems"
              value-key="value"
              :disabled="!canConfigure"
              data-testid="sat-environment"
            />
          </UFormField>

          <UButton
            v-if="canConfigure"
            type="submit"
            :loading="saving"
            :disabled="!canSave"
            data-testid="sat-save"
          >
            {{ t('satCfdi.settings.save') }}
          </UButton>
        </form>
      </UCard>

      <!-- The clinic's own Facturama account -->
      <UCard>
        <template #header>
          <h2 class="font-semibold">
            {{ t('satCfdi.facturama.title') }}
          </h2>
          <p class="text-sm text-muted mt-1">
            {{ t('satCfdi.facturama.intro') }}
          </p>
        </template>
        <div class="space-y-6">
          <form
            v-for="env in (['sandbox', 'production'] as const)"
            :key="env"
            class="space-y-3"
            :data-testid="`sat-facturama-${env}`"
            @submit.prevent="saveAccount(env)"
          >
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-sm font-medium">
                {{ t(`satCfdi.settings.environment.${env}`) }}
              </h3>
              <UBadge
                :color="settings.facturama[env].user && settings.facturama[env].has_password ? 'success' : 'neutral'"
                variant="subtle"
                size="sm"
              >
                {{ settings.facturama[env].user && settings.facturama[env].has_password
                  ? t('satCfdi.facturama.configured')
                  : t('satCfdi.facturama.notConfigured') }}
              </UBadge>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <UFormField :label="t('satCfdi.facturama.user')">
                <UInput
                  v-model="accounts[env].user"
                  autocomplete="off"
                  :disabled="!canConfigure"
                  class="w-full"
                />
              </UFormField>
              <UFormField
                :label="t('satCfdi.facturama.password')"
                :help="settings.facturama[env].has_password ? t('satCfdi.facturama.passwordKept') : undefined"
              >
                <UInput
                  v-model="accounts[env].password"
                  :type="accounts[env].show ? 'text' : 'password'"
                  autocomplete="new-password"
                  :disabled="!canConfigure"
                  class="w-full"
                  :ui="{ trailing: 'pe-1' }"
                >
                  <template #trailing>
                    <UButton
                      :icon="accounts[env].show ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                      size="xs"
                      color="neutral"
                      variant="ghost"
                      :aria-label="t('satCfdi.certificate.togglePassword')"
                      @click="accounts[env].show = !accounts[env].show"
                    />
                  </template>
                </UInput>
              </UFormField>
            </div>
            <UButton
              v-if="canConfigure"
              type="submit"
              variant="soft"
              :loading="accounts[env].saving"
              :disabled="!accounts[env].user.trim() || (!accounts[env].password && !settings.facturama[env].has_password)"
            >
              {{ t('satCfdi.facturama.save') }}
            </UButton>
          </form>
          <p class="text-xs text-muted">
            <UIcon
              name="i-lucide-lock"
              class="inline-block align-text-bottom mr-1"
            />
            {{ t('satCfdi.facturama.encryptionNote') }}
          </p>
        </div>
      </UCard>

      <!-- The CSD -->
      <UCard>
        <template #header>
          <h2 class="font-semibold">
            {{ t('satCfdi.certificate.title') }}
          </h2>
        </template>

        <div
          v-if="settings.certificate"
          class="mb-6"
          data-testid="sat-certificate"
        >
          <div class="flex flex-wrap items-center gap-2 mb-3">
            <UBadge
              v-if="expiry"
              :color="expiry.color"
              variant="subtle"
            >
              {{ expiry.label }}
            </UBadge>
            <UBadge
              :color="registered ? 'success' : 'warning'"
              variant="subtle"
              data-testid="sat-registration"
            >
              {{ registered
                ? t('satCfdi.certificate.registeredIn', { environment: t(`satCfdi.settings.environment.${settings.environment}`) })
                : t('satCfdi.certificate.notRegisteredIn', { environment: t(`satCfdi.settings.environment.${settings.environment}`) }) }}
            </UBadge>
          </div>
          <div
            v-if="!registered"
            class="mb-4 space-y-3"
          >
            <p
              v-if="settings.certificate.registration_error"
              class="text-sm text-muted"
            >
              {{ t('satCfdi.certificate.lastAttempt', { error: settings.certificate.registration_error }) }}
            </p>
            <UButton
              v-if="canConfigure"
              icon="i-lucide-refresh-cw"
              variant="soft"
              :loading="registering"
              data-testid="sat-register"
              @click="register"
            >
              {{ t('satCfdi.certificate.register') }}
            </UButton>
          </div>
          <dl class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <dt class="text-muted text-xs">
                {{ t('satCfdi.certificate.number') }}
              </dt>
              <dd class="font-mono">
                {{ settings.certificate.certificate_number }}
              </dd>
            </div>
            <div>
              <dt class="text-muted text-xs">
                {{ t('satCfdi.issuer.rfc') }}
              </dt>
              <dd class="font-mono">
                {{ settings.certificate.rfc }}
              </dd>
            </div>
            <div>
              <dt class="text-muted text-xs">
                {{ t('satCfdi.certificate.validFrom') }}
              </dt>
              <dd>{{ formatDate(settings.certificate.valid_from) }}</dd>
            </div>
            <div>
              <dt class="text-muted text-xs">
                {{ t('satCfdi.certificate.validUntil') }}
              </dt>
              <dd>{{ formatDate(settings.certificate.valid_until) }}</dd>
            </div>
          </dl>
        </div>
        <p
          v-else
          class="text-sm text-muted mb-6"
        >
          {{ t('satCfdi.certificate.none') }}
        </p>

        <form
          v-if="canConfigure"
          class="space-y-5"
          @submit.prevent="upload"
        >
          <h3 class="text-sm font-medium">
            {{ settings.certificate ? t('satCfdi.certificate.replace') : t('satCfdi.certificate.upload') }}
          </h3>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField :label="t('satCfdi.certificate.cer')">
              <input
                ref="cerInput"
                type="file"
                accept=".cer"
                class="hidden"
                data-testid="sat-cer-input"
                @change="pick('cer', $event)"
              >
              <UButton
                :icon="cer ? 'i-lucide-file-check-2' : 'i-lucide-upload'"
                :color="cer ? 'success' : 'neutral'"
                variant="outline"
                block
                class="justify-start truncate"
                @click="cerInput?.click()"
              >
                {{ cer?.name ?? t('satCfdi.certificate.pickCer') }}
              </UButton>
            </UFormField>
            <UFormField :label="t('satCfdi.certificate.key')">
              <input
                ref="keyInput"
                type="file"
                accept=".key"
                class="hidden"
                data-testid="sat-key-input"
                @change="pick('key', $event)"
              >
              <UButton
                :icon="key ? 'i-lucide-file-check-2' : 'i-lucide-upload'"
                :color="key ? 'success' : 'neutral'"
                variant="outline"
                block
                class="justify-start truncate"
                @click="keyInput?.click()"
              >
                {{ key?.name ?? t('satCfdi.certificate.pickKey') }}
              </UButton>
            </UFormField>
          </div>

          <UFormField
            :label="t('satCfdi.certificate.password')"
            :help="t('satCfdi.certificate.passwordHint')"
          >
            <UInput
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="off"
              class="w-full sm:w-80"
              :ui="{ trailing: 'pe-1' }"
              data-testid="sat-password"
            >
              <template #trailing>
                <UButton
                  :icon="showPassword ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                  size="xs"
                  color="neutral"
                  variant="ghost"
                  :aria-label="t('satCfdi.certificate.togglePassword')"
                  @click="showPassword = !showPassword"
                />
              </template>
            </UInput>
          </UFormField>

          <UAlert
            v-if="uploadError"
            color="error"
            variant="soft"
            icon="i-lucide-alert-triangle"
            :title="uploadError"
            data-testid="sat-upload-error"
          />

          <UButton
            type="submit"
            icon="i-lucide-shield-check"
            :loading="uploading"
            :disabled="!canUpload"
            data-testid="sat-upload"
          >
            {{ t('satCfdi.certificate.submit') }}
          </UButton>

          <p class="text-xs text-muted">
            <UIcon
              name="i-lucide-lock"
              class="inline-block align-text-bottom mr-1"
            />
            {{ t('satCfdi.certificate.encryptionNote') }}
          </p>
        </form>
      </UCard>
    </template>
  </div>
</template>
