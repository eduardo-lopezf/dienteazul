<script setup lang="ts">
/**
 * The patient reads the letter and signs it — or declines, which is
 * recorded too. Once signed it cannot be edited: this is the last screen
 * on which the text can still be anything but a record.
 *
 * Two ways to sign. On screen, on the pad. Or on paper: the letter is
 * printed, filled in and signed by hand, and its scan is filed with the
 * patient's documents — the scan is then the signature.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { Consent, SignatureMethod, SignerCapacity } from '../../composables/useConsents'

const props = defineProps<{
  open: boolean
  consent: Consent | null
  /** Offered as the signer's name; the patient, unless someone signs for them. */
  patientName: string
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  'done': [consent: Consent]
}>()

const { t, locale } = useI18n()
const { regulation, load: loadRegulation } = useRecordRegulation()
const toast = useToast()
const { can } = usePermissions()
const { isActive } = useModules()
const consents = useConsents()

const method = ref<SignatureMethod>('screen')
const scan = ref<File | null>(null)
// The scan is a document of the patient: the Media module has to be
// running, and whoever is at the screen allowed to file one.
const canFileScan = computed(() => isActive('media') && can(PERMISSIONS.documents.write))
const methodOptions = computed(() => (['screen', 'paper'] as const).map(value => ({
  label: t(`consents.sign.method.${value}`), value
})))
const SCAN_TYPES = 'application/pdf,image/jpeg,image/png'

const signerName = ref('')
const capacity = ref<SignerCapacity>('patient')
const signature = ref<string | null>(null)
const busy = ref(false)

const capacityOptions = computed(() => (['patient', 'guardian', 'representative'] as const).map(value => ({
  label: t(`consents.capacity.${value}`), value
})))

// An informed consent has to name who explained it; the server refuses
// otherwise, and the screen should not let the patient sign for nothing.
const missingProfessional = computed(() =>
  props.consent?.kind === 'informed' && !props.consent.explained_by_professional_id
)
const canSign = computed(() =>
  signerName.value.trim().length > 0
  && !missingProfessional.value
  && (method.value === 'paper' ? scan.value !== null : signature.value !== null)
)

watch(() => props.open, (opened) => {
  if (!opened) return
  void loadRegulation()
  signerName.value = props.patientName
  capacity.value = 'patient'
  signature.value = null
  method.value = 'screen'
  scan.value = null
})

function pickScan(event: Event) {
  scan.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function print() {
  if (!props.consent) return
  const tab = consents.reserveTab()
  try {
    await consents.openPdf(props.consent.id, locale.value, tab)
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  }
}

async function run(action: () => Promise<Consent>) {
  if (busy.value) return
  busy.value = true
  try {
    emit('done', await action())
    emit('update:open', false)
  } catch (error: unknown) {
    const e = error as { data?: { detail?: string } }
    toast.add({ title: t('errors.updateFailed'), description: e?.data?.detail, color: 'error' })
  } finally {
    busy.value = false
  }
}

function sign() {
  if (!props.consent || !canSign.value) return
  const { id, patient_id: patientId, title } = props.consent
  const who = { signed_by_name: signerName.value.trim(), signer_capacity: capacity.value }
  if (method.value === 'paper') {
    const file = scan.value!
    run(async () => consents.sign(id, {
      ...who,
      method: 'paper',
      document_id: await consents.uploadScan(patientId, file, title)
    }))
    return
  }
  run(() => consents.sign(id, { ...who, method: 'screen', signature_data: { png: signature.value! } }))
}

function decline() {
  if (!props.consent) return
  const id = props.consent.id
  run(() => consents.act(id, 'decline'))
}
</script>

<template>
  <UModal
    :open="open"
    @update:open="(v) => emit('update:open', v)"
  >
    <template #content>
      <UCard
        v-if="consent"
        data-testid="consent-sign"
      >
        <template #header>
          <h2 class="text-lg font-semibold">
            {{ consent.title }}
          </h2>
          <p
            v-if="consent.procedure_label"
            class="text-sm text-muted"
          >
            {{ consent.procedure_label }}
          </p>
        </template>

        <div class="space-y-4">
          <div class="max-h-64 overflow-y-auto rounded-md border border-default p-3 text-sm whitespace-pre-line">
            {{ consent.body }}
          </div>

          <p
            v-if="consent.explained_by_name"
            class="text-sm text-muted"
          >
            {{ t('consents.sign.explainedBy', { name: consent.explained_by_name }) }}
            <span v-if="consent.explained_by_license">· {{ consent.explained_by_license }}</span>
          </p>
          <UAlert
            v-if="missingProfessional"
            color="warning"
            icon="i-lucide-triangle-alert"
            :title="t('consents.sign.missingProfessional')"
          />

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField
              :label="t('consents.sign.signerName')"
              required
            >
              <UInput
                v-model="signerName"
                class="w-full"
              />
            </UFormField>
            <UFormField :label="t('consents.sign.capacity')">
              <USelect
                v-model="capacity"
                :items="capacityOptions"
                value-key="value"
                class="w-full"
              />
            </UFormField>
          </div>

          <UFormField
            v-if="canFileScan"
            :label="t('consents.sign.method.label')"
          >
            <URadioGroup
              v-model="method"
              :items="methodOptions"
              value-key="value"
              orientation="horizontal"
              data-testid="consent-sign-method"
            />
          </UFormField>

          <!-- What the record is kept under, said where the patient signs. -->
          <p
            v-if="regulation?.text"
            class="text-caption text-subtle"
            data-testid="consent-regulation"
          >
            {{ t('regulation.label') }}: {{ regulation.text }}
          </p>

          <div v-if="method === 'screen'">
            <p class="text-xs text-muted mb-2">
              {{ t('consents.sign.signHere') }}
            </p>
            <SignaturePad v-model="signature" />
          </div>

          <div
            v-else
            class="space-y-3 rounded-md border border-default p-3"
          >
            <p class="text-sm text-muted">
              {{ t('consents.sign.paperSteps') }}
            </p>
            <UButton
              color="neutral"
              variant="soft"
              icon="i-lucide-printer"
              data-testid="consent-print"
              @click="print"
            >
              {{ t('consents.print') }}
            </UButton>
            <UFormField
              :label="t('consents.sign.scan')"
              :hint="t('consents.sign.scanHint')"
              required
            >
              <input
                type="file"
                :accept="SCAN_TYPES"
                class="block w-full text-sm text-default file:mr-3 file:rounded-md file:border-0 file:bg-elevated file:px-3 file:py-2 file:text-sm file:text-default"
                data-testid="consent-scan-input"
                @change="pickScan"
              >
            </UFormField>
          </div>
        </div>

        <template #footer>
          <div class="flex justify-between gap-2 flex-wrap">
            <UButton
              color="neutral"
              variant="soft"
              :loading="busy"
              data-testid="consent-decline"
              @click="decline"
            >
              {{ t('consents.sign.decline') }}
            </UButton>
            <div class="flex gap-2">
              <UButton
                color="neutral"
                variant="ghost"
                @click="emit('update:open', false)"
              >
                {{ t('common.cancel') }}
              </UButton>
              <UButton
                :disabled="!canSign"
                :loading="busy"
                :icon="method === 'paper' ? 'i-lucide-file-up' : 'i-lucide-pen-line'"
                data-testid="consent-sign-confirm"
                @click="sign"
              >
                {{ method === 'paper' ? t('consents.sign.confirmPaper') : t('consents.sign.confirm') }}
              </UButton>
            </div>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
