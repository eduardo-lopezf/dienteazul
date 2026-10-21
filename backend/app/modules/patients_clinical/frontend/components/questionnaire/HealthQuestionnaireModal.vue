<script setup lang="ts">
/**
 * The health questionnaire: answered on screen, or filed as the scan of
 * the sheet filled in by hand. Once saved it is what was declared that day
 * and is not edited — a new visit is a new one.
 *
 * Two forms: the adult one, and the pediatric one (odontología pediátrica),
 * which a parent, guardian or representative answers and signs for a child
 * — on the tablet, or on the printed sheet whose foot carries their consent.
 * The pediatric form is offered first under 18; the clinician may pick the
 * other one.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { FormKind, QuestionAnswer, SignerCapacity } from '../../composables/useHealthQuestionnaires'
import {
  CONDITION_GROUPS,
  FORM_KINDS,
  PEDIATRIC_CONDITIONS,
  PEDIATRIC_FIELD_GROUPS,
  PEDIATRIC_QUESTION_GROUPS,
  QUESTIONS,
  SIGNER_CAPACITIES,
  questionsOf,
  suggestedForm
} from '../../composables/useHealthQuestionnaires'

const props = defineProps<{
  open: boolean
  patientId: string
  /** Offered as the name of whoever signs; they may be someone else. */
  patientName?: string
  /** Decides which form is offered first. */
  patientBirthDate?: string | null
}>()
const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [] }>()

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { isActive } = useModules()
const { regulation, load: loadRegulation } = useRecordRegulation()
onMounted(() => loadRegulation())
const questionnaires = useHealthQuestionnaires()

type Mode = 'screen' | 'paper'
const mode = ref<Mode>('screen')
const formKind = ref<FormKind>('adult')
const isPediatric = computed(() => formKind.value === 'pediatric')
const canFileScan = computed(() => isActive('media') && can(PERMISSIONS.documents.write))
const modeOptions = computed(() => (['screen', 'paper'] as const).map(value => ({
  label: t(value === 'screen' ? 'healthQuestionnaire.onScreen' : 'healthQuestionnaire.paper'), value
})))
const formOptions = computed(() => FORM_KINDS.map(value => ({
  label: t(`healthQuestionnaire.forms.${value}`), value
})))

const chiefComplaint = ref('')
const bloodType = ref('')
const allergies = ref('')
// 'yes' | 'no' | undefined: a question left alone was not asked.
const answers = ref<Record<string, 'yes' | 'no' | undefined>>({})
const details = ref<Record<string, string>>({})
const ticked = ref<Record<string, boolean>>({})
const formData = ref<Record<string, string>>({})
const drugsDetail = ref('')
const other = ref('')
const scan = ref<File | null>(null)
const busy = ref(false)

const yesNo = computed(() => [
  { label: t('common.yes'), value: 'yes' },
  { label: t('common.no'), value: 'no' }
])

// Who signs. Required on screen; on paper the signature is on the sheet.
const signature = ref<string | null>(null)
const signerName = ref('')
const signerCapacity = ref<SignerCapacity>('patient')
/** A child does not sign their own questionnaire. */
const capacityItems = computed(() => SIGNER_CAPACITIES
  .filter(value => !isPediatric.value || value !== 'patient')
  .map(value => ({ value, label: t(`healthQuestionnaire.sign.capacities.${value}`) })))
/** A signature is a drawing with a name under it. */
const signed = computed(() => signature.value !== null && signerName.value.trim().length > 0)

/** Start a form afresh: its own questions, and its own signer. */
async function startForm(kind: FormKind) {
  formKind.value = kind
  answers.value = {}
  details.value = {}
  ticked.value = {}
  formData.value = {}
  drugsDetail.value = ''
  signature.value = null
  if (kind === 'pediatric') {
    signerCapacity.value = 'guardian'
    signerName.value = ''
    // The guardian on file, if there is one: written once, not twice.
    const guardian = await questionnaires.legalGuardian(props.patientId)
    if (guardian && formKind.value === 'pediatric') {
      signerName.value = guardian.name
      formData.value = { guardian_name: guardian.name, ...(guardian.phone ? { guardian_phone: guardian.phone } : {}) }
    }
  } else {
    signerCapacity.value = 'patient'
    signerName.value = props.patientName ?? ''
  }
}

watch(() => props.open, (opened) => {
  if (!opened) return
  mode.value = 'screen'
  chiefComplaint.value = ''
  bloodType.value = ''
  allergies.value = ''
  other.value = ''
  scan.value = null
  void startForm(suggestedForm(props.patientBirthDate))
})

function chooseForm(kind: FormKind) {
  if (kind !== formKind.value) void startForm(kind)
}

const conditions = computed(() => Object.keys(ticked.value).filter(key => ticked.value[key]))
const filledData = computed(() => Object.fromEntries(
  Object.entries(formData.value).map(([k, v]) => [k, v.trim()]).filter(([, v]) => v)
))
const answered = computed(() => {
  const out: Record<string, QuestionAnswer> = {}
  for (const key of questionsOf(formKind.value)) {
    const value = answers.value[key]
    if (!value) continue
    out[key] = { answer: value === 'yes', detail: details.value[key]?.trim() || null }
  }
  return out
})

const canSave = computed(() => mode.value === 'paper'
  ? scan.value !== null
  : signed.value
    && (chiefComplaint.value.trim().length > 0
      || Object.keys(answered.value).length > 0
      || conditions.value.length > 0
      || Object.keys(filledData.value).length > 0)
)

function pickScan(event: Event) {
  scan.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

function printBlank() {
  const tab = questionnaires.reserveTab()
  questionnaires.openBlankForm(props.patientId, locale.value, tab, formKind.value).catch(() => {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  })
}

async function save() {
  if (!canSave.value || busy.value) return
  busy.value = true
  try {
    const common = { chief_complaint: chiefComplaint.value.trim() || null, form_kind: formKind.value }
    if (mode.value === 'paper') {
      const title = t(isPediatric.value ? 'healthQuestionnaire.pediatric.title' : 'healthQuestionnaire.title')
      const documentId = await questionnaires.uploadScan(props.patientId, scan.value!, title)
      await questionnaires.create(props.patientId, { ...common, scan_document_id: documentId })
    } else {
      await questionnaires.create(props.patientId, {
        ...common,
        blood_type: isPediatric.value ? null : bloodType.value.trim() || null,
        declared_allergies: isPediatric.value ? null : allergies.value.trim() || null,
        form_data: isPediatric.value ? filledData.value : {},
        answers: answered.value,
        conditions: conditions.value,
        drugs_detail: isPediatric.value ? null : drugsDetail.value.trim() || null,
        other_conditions: other.value.trim() || null,
        signature: signature.value
          ? { png: signature.value, signed_by_name: signerName.value.trim(), signer_capacity: signerCapacity.value }
          : null
      })
    }
    emit('saved')
    emit('update:open', false)
  } catch (error: unknown) {
    const e = error as { data?: { detail?: string } }
    toast.add({ title: t('errors.updateFailed'), description: e?.data?.detail, color: 'error' })
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    :ui="{ content: 'sm:max-w-3xl' }"
    @update:open="(v) => emit('update:open', v)"
  >
    <template #content>
      <UCard
        data-testid="questionnaire-form"
        :ui="{ body: 'max-h-[70vh] overflow-y-auto' }"
      >
        <template #header>
          <h2 class="text-lg font-semibold">
            {{ isPediatric ? t('healthQuestionnaire.pediatric.title') : t('healthQuestionnaire.title') }}
          </h2>
          <p class="text-caption text-muted">
            {{ t('healthQuestionnaire.confidential') }}
          </p>
        </template>

        <div class="space-y-5">
          <UFormField
            :label="t('healthQuestionnaire.form')"
            :description="t('healthQuestionnaire.formHint')"
          >
            <URadioGroup
              :model-value="formKind"
              :items="formOptions"
              value-key="value"
              orientation="horizontal"
              data-testid="questionnaire-form-kind"
              @update:model-value="(value) => chooseForm(value as FormKind)"
            />
          </UFormField>

          <UFormField
            v-if="canFileScan"
            :label="t('healthQuestionnaire.howFilled')"
          >
            <URadioGroup
              v-model="mode"
              :items="modeOptions"
              value-key="value"
              orientation="horizontal"
              data-testid="questionnaire-mode"
            />
          </UFormField>

          <UFormField :label="t('healthQuestionnaire.chiefComplaint')">
            <UTextarea
              v-model="chiefComplaint"
              class="w-full"
              :rows="2"
              data-testid="questionnaire-chief-complaint"
            />
          </UFormField>

          <template v-if="mode === 'paper'">
            <p class="text-sm text-muted">
              {{ isPediatric ? t('healthQuestionnaire.pediatric.paperSteps') : t('healthQuestionnaire.paperSteps') }}
            </p>
            <UButton
              size="sm"
              color="neutral"
              variant="soft"
              icon="i-lucide-printer"
              data-testid="questionnaire-modal-print-blank"
              @click="printBlank"
            >
              {{ t('healthQuestionnaire.printBlank') }} · {{ t(`healthQuestionnaire.forms.${formKind}`) }}
            </UButton>
            <UFormField
              :label="t('healthQuestionnaire.scan')"
              :hint="t('healthQuestionnaire.scanHint')"
              required
            >
              <input
                type="file"
                accept="application/pdf,image/jpeg,image/png"
                class="block w-full text-sm text-default file:mr-3 file:rounded-md file:border-0 file:bg-elevated file:px-3 file:py-2 file:text-sm file:text-default"
                data-testid="questionnaire-scan-input"
                @change="pickScan"
              >
            </UFormField>
          </template>

          <!-- The pediatric form, on screen. -->
          <template v-else-if="isPediatric">
            <section
              v-for="(keys, group) in PEDIATRIC_FIELD_GROUPS"
              :key="`fields-${group}`"
              class="space-y-2"
              :data-testid="`pediatric-fields-${group}`"
            >
              <h3
                v-if="group !== 'health'"
                class="text-sm font-semibold text-default"
              >
                {{ t(`healthQuestionnaire.pediatric.sections.${group}`) }}
              </h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                <UFormField
                  v-for="key in keys"
                  :key="key"
                  :label="t(`healthQuestionnaire.pediatric.fields.${key}`)"
                >
                  <UInput
                    v-model="formData[key]"
                    class="w-full"
                    :maxlength="300"
                    :data-testid="`pediatric-field-${key}`"
                  />
                </UFormField>
              </div>
            </section>

            <section
              v-for="(keys, group) in PEDIATRIC_QUESTION_GROUPS"
              :key="`questions-${group}`"
            >
              <h3 class="text-sm font-semibold text-default">
                {{ t(`healthQuestionnaire.pediatric.sections.${group}`) }}
              </h3>
              <ol class="divide-y divide-[var(--color-border-subtle)]">
                <li
                  v-for="key in keys"
                  :key="key"
                  class="py-2 space-y-2"
                  :data-testid="`question-${key}`"
                >
                  <div class="flex items-start justify-between gap-4 flex-wrap">
                    <span class="text-sm text-default min-w-0 flex-1">
                      {{ t(`healthQuestionnaire.questions.${key}`) }}
                    </span>
                    <URadioGroup
                      v-model="answers[key]"
                      :items="yesNo"
                      value-key="value"
                      orientation="horizontal"
                    />
                  </div>
                  <UInput
                    v-if="answers[key] === 'yes'"
                    v-model="details[key]"
                    class="w-full"
                    size="sm"
                    :placeholder="t('healthQuestionnaire.detail')"
                  />
                </li>
              </ol>
            </section>

            <div>
              <p class="text-sm font-medium text-default mb-2">
                {{ t('healthQuestionnaire.pediatric.conditionsIntro') }}
              </p>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5 pb-3 mb-3 border-b border-default">
                <UCheckbox
                  v-for="key in PEDIATRIC_CONDITIONS"
                  :key="key"
                  v-model="ticked[key]"
                  :label="t(`healthQuestionnaire.conditions.${key}`)"
                  :data-testid="`condition-${key}`"
                />
              </div>
              <UFormField :label="t('healthQuestionnaire.otherConditions')">
                <UTextarea
                  v-model="other"
                  class="w-full"
                  :rows="2"
                />
              </UFormField>
            </div>
          </template>

          <!-- The adult form, on screen. -->
          <template v-else>
            <div class="grid grid-cols-1 sm:grid-cols-[10rem_1fr] gap-4">
              <UFormField :label="t('healthQuestionnaire.bloodType')">
                <UInput
                  v-model="bloodType"
                  class="w-full"
                />
              </UFormField>
              <UFormField :label="t('healthQuestionnaire.allergies')">
                <UInput
                  v-model="allergies"
                  class="w-full"
                />
              </UFormField>
            </div>

            <ol class="divide-y divide-[var(--color-border-subtle)]">
              <li
                v-for="(key, index) in QUESTIONS"
                :key="key"
                class="py-2 space-y-2"
                :data-testid="`question-${key}`"
              >
                <div class="flex items-start justify-between gap-4 flex-wrap">
                  <span class="text-sm text-default min-w-0 flex-1">
                    {{ index + 1 }}. {{ t(`healthQuestionnaire.questions.${key}`) }}
                  </span>
                  <URadioGroup
                    v-model="answers[key]"
                    :items="yesNo"
                    value-key="value"
                    orientation="horizontal"
                  />
                </div>
                <UInput
                  v-if="answers[key] === 'yes'"
                  v-model="details[key]"
                  class="w-full"
                  size="sm"
                  :placeholder="t('healthQuestionnaire.detail')"
                />
              </li>
            </ol>

            <div>
              <p class="text-sm font-medium text-default mb-2">
                {{ t('healthQuestionnaire.conditionsIntro') }}
              </p>
              <div
                v-for="(group, g) in CONDITION_GROUPS"
                :key="g"
                class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1.5 pb-3 mb-3 border-b border-default"
              >
                <UCheckbox
                  v-for="key in group"
                  :key="key"
                  v-model="ticked[key]"
                  :label="t(`healthQuestionnaire.conditions.${key}`)"
                  :data-testid="`condition-${key}`"
                />
              </div>
              <UFormField
                v-if="ticked.drugs"
                :label="t('healthQuestionnaire.drugsDetail')"
                class="mb-3"
              >
                <UInput
                  v-model="drugsDetail"
                  class="w-full"
                />
              </UFormField>
              <UFormField :label="t('healthQuestionnaire.otherConditions')">
                <UTextarea
                  v-model="other"
                  class="w-full"
                  :rows="2"
                />
              </UFormField>
            </div>
          </template>

          <!-- What the questionnaire is kept under, said where it is declared. -->
          <p
            v-if="regulation?.text"
            class="text-caption text-subtle"
            data-testid="questionnaire-regulation"
          >
            {{ t('regulation.label') }}: {{ regulation.text }}
          </p>

          <!-- Whoever answered signs it — for a child, a parent or guardian,
               under the consent the paper form carries. On paper the
               signature is on the sheet. -->
          <div
            v-if="mode === 'screen'"
            class="space-y-3 border-t border-default pt-4"
            data-testid="questionnaire-signature"
          >
            <div>
              <p class="font-medium text-default">
                {{ isPediatric ? t('healthQuestionnaire.pediatric.signTitle') : t('healthQuestionnaire.sign.title') }}
              </p>
              <p
                class="text-caption text-muted"
                data-testid="questionnaire-sign-statement"
              >
                {{ isPediatric ? t('healthQuestionnaire.pediatric.consent') : t('healthQuestionnaire.sign.statement') }}
              </p>
            </div>
            <div class="grid gap-3 sm:grid-cols-2">
              <UFormField :label="t('healthQuestionnaire.sign.name')">
                <UInput
                  v-model="signerName"
                  class="w-full"
                  :maxlength="200"
                  data-testid="questionnaire-signer-name"
                />
              </UFormField>
              <UFormField
                :label="t('healthQuestionnaire.sign.capacity')"
                :description="isPediatric ? t('healthQuestionnaire.pediatric.guardianOnly') : undefined"
              >
                <USelect
                  v-model="signerCapacity"
                  :items="capacityItems"
                  value-key="value"
                  class="w-full"
                  data-testid="questionnaire-signer-capacity"
                />
              </UFormField>
            </div>
            <SignaturePad
              v-model="signature"
              testid="questionnaire-signature-pad"
            />
            <p
              class="text-caption"
              :class="signature !== null && !signed ? 'text-warning' : 'text-subtle'"
            >
              {{ signature !== null && !signed
                ? t('healthQuestionnaire.sign.needsName')
                : t(isPediatric ? 'healthQuestionnaire.pediatric.signRequired' : 'healthQuestionnaire.sign.required') }}
            </p>
          </div>
        </div>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="emit('update:open', false)"
            >
              {{ t('common.cancel') }}
            </UButton>
            <UButton
              :disabled="!canSave"
              :loading="busy"
              icon="i-lucide-save"
              data-testid="questionnaire-save"
              @click="save"
            >
              {{ t('healthQuestionnaire.save') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
