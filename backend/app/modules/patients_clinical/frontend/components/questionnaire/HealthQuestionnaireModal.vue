<script setup lang="ts">
/**
 * The health questionnaire: answered on screen, or filed as the scan of
 * the sheet the patient filled in by hand. Once saved it is what the
 * patient declared that day and is not edited — a new visit is a new one.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { QuestionAnswer, SignerCapacity } from '../../composables/useHealthQuestionnaires'
import { CONDITION_GROUPS, QUESTIONS, SIGNER_CAPACITIES } from '../../composables/useHealthQuestionnaires'

const props = defineProps<{
  open: boolean
  patientId: string
  /** Offered as the name of whoever signs; they may be someone else. */
  patientName?: string
}>()
const emit = defineEmits<{ 'update:open': [value: boolean], 'saved': [] }>()

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { isActive } = useModules()
const { regulation, load: loadRegulation } = useRecordRegulation()
onMounted(() => loadRegulation())
const questionnaires = useHealthQuestionnaires()

type Mode = 'screen' | 'paper'
const mode = ref<Mode>('screen')
const canFileScan = computed(() => isActive('media') && can(PERMISSIONS.documents.write))
const modeOptions = computed(() => (['screen', 'paper'] as const).map(value => ({
  label: t(value === 'screen' ? 'healthQuestionnaire.onScreen' : 'healthQuestionnaire.paper'), value
})))

const chiefComplaint = ref('')
const bloodType = ref('')
const allergies = ref('')
// 'yes' | 'no' | undefined: a question left alone was not asked.
const answers = ref<Record<string, 'yes' | 'no' | undefined>>({})
const details = ref<Record<string, string>>({})
const ticked = ref<Record<string, boolean>>({})
const drugsDetail = ref('')
const other = ref('')
const scan = ref<File | null>(null)
const busy = ref(false)

const yesNo = computed(() => [
  { label: t('common.yes'), value: 'yes' },
  { label: t('common.no'), value: 'no' }
])

watch(() => props.open, (opened) => {
  if (!opened) return
  mode.value = 'screen'
  chiefComplaint.value = ''
  bloodType.value = ''
  allergies.value = ''
  answers.value = {}
  details.value = {}
  ticked.value = {}
  drugsDetail.value = ''
  other.value = ''
  scan.value = null
  signature.value = null
  signerName.value = props.patientName ?? ''
  signerCapacity.value = 'patient'
})

// The patient's signature. Required on screen; the other valid way is the
// "on paper" mode, where the signed sheet is uploaded.
const signature = ref<string | null>(null)
const signerName = ref('')
const signerCapacity = ref<SignerCapacity>('patient')
const capacityItems = computed(() => SIGNER_CAPACITIES.map(value => ({
  value,
  label: t(`healthQuestionnaire.sign.capacities.${value}`)
})))
/** A signature is a drawing with a name under it. */
const signed = computed(() => signature.value !== null && signerName.value.trim().length > 0)

const conditions = computed(() => Object.keys(ticked.value).filter(key => ticked.value[key]))
const answered = computed(() => {
  const out: Record<string, QuestionAnswer> = {}
  for (const key of QUESTIONS) {
    const value = answers.value[key]
    if (!value) continue
    out[key] = { answer: value === 'yes', detail: details.value[key]?.trim() || null }
  }
  return out
})

const canSave = computed(() => mode.value === 'paper'
  ? scan.value !== null
  : signed.value
    && (chiefComplaint.value.trim().length > 0 || Object.keys(answered.value).length > 0 || conditions.value.length > 0)
)

function pickScan(event: Event) {
  scan.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function save() {
  if (!canSave.value || busy.value) return
  busy.value = true
  try {
    const common = { chief_complaint: chiefComplaint.value.trim() || null }
    if (mode.value === 'paper') {
      const documentId = await questionnaires.uploadScan(props.patientId, scan.value!, t('healthQuestionnaire.title'))
      await questionnaires.create(props.patientId, { ...common, scan_document_id: documentId })
    } else {
      await questionnaires.create(props.patientId, {
        ...common,
        blood_type: bloodType.value.trim() || null,
        declared_allergies: allergies.value.trim() || null,
        answers: answered.value,
        conditions: conditions.value,
        drugs_detail: drugsDetail.value.trim() || null,
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
            {{ t('healthQuestionnaire.title') }}
          </h2>
          <p class="text-caption text-muted">
            {{ t('healthQuestionnaire.confidential') }}
          </p>
        </template>

        <div class="space-y-5">
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
              {{ t('healthQuestionnaire.paperSteps') }}
            </p>
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

          <!-- What the questionnaire is kept under, said where the
               patient declares. -->
          <p
            v-if="regulation?.text"
            class="text-caption text-subtle"
            data-testid="questionnaire-regulation"
          >
            {{ t('regulation.label') }}: {{ regulation.text }}
          </p>

          <!-- The patient signs what they declared. On paper the signature
               is on the sheet. -->
          <div
            v-if="mode === 'screen'"
            class="space-y-3 border-t border-default pt-4"
            data-testid="questionnaire-signature"
          >
            <div>
              <p class="font-medium text-default">
                {{ t('healthQuestionnaire.sign.title') }}
              </p>
              <p class="text-caption text-muted">
                {{ t('healthQuestionnaire.sign.statement') }}
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
              <UFormField :label="t('healthQuestionnaire.sign.capacity')">
                <USelect
                  v-model="signerCapacity"
                  :items="capacityItems"
                  value-key="value"
                  class="w-full"
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
                : t('healthQuestionnaire.sign.required') }}
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
