<script setup lang="ts">
/**
 * Write a consent draft, or edit one: pick the kind and a template, adjust
 * the text for this patient, and — for an informed consent — say who
 * explained it.
 */
import type { Consent, ConsentKind, ConsentTemplate } from '../../composables/useConsents'

const props = defineProps<{
  open: boolean
  patientId: string
  /** Set when editing an existing draft. */
  consent?: Consent | null
  /** The treatment plan a new letter is written for, when it is for one. */
  planId?: string | null
}>()
const emit = defineEmits<{
  'update:open': [value: boolean]
  'saved': [consent: Consent]
}>()

const { t } = useI18n()
const toast = useToast()
const consents = useConsents()
const { professionals, fetchProfessionals } = useProfessionals()
const { active, isActive } = useModules()

// The directory belongs to the Professionals App; with it off nobody can
// be named, and the form says so instead of offering an empty list.
const professionalsAvailable = computed(() => active.value === null || isActive('professionals'))

const kind = ref<ConsentKind>('informed')
const templateId = ref<string | undefined>(undefined)
const title = ref('')
const body = ref('')
const procedureLabel = ref('')
const professionalId = ref<string | undefined>(undefined)
const templates = ref<ConsentTemplate[]>([])
const saving = ref(false)

const kindOptions = computed(() => [
  { label: t('consents.kinds.informed'), value: 'informed' },
  { label: t('consents.kinds.data_use'), value: 'data_use' },
  { label: t('consents.kinds.conformity'), value: 'conformity' }
])
const templateOptions = computed(() =>
  templates.value.filter(tpl => tpl.kind === kind.value).map(tpl => ({ label: tpl.title, value: tpl.id }))
)
const professionalOptions = computed(() =>
  professionals.value.map(p => ({ label: `${p.first_name} ${p.last_name}`.trim(), value: p.id }))
)
const canSave = computed(() => title.value.trim().length > 0 && body.value.trim().length > 0)

watch(() => props.open, async (opened) => {
  if (!opened) return
  const existing = props.consent
  kind.value = existing?.kind ?? 'informed'
  templateId.value = existing?.template_id ?? undefined
  title.value = existing?.title ?? ''
  body.value = existing?.body ?? ''
  procedureLabel.value = existing?.procedure_label ?? ''
  professionalId.value = existing?.explained_by_professional_id ?? undefined
  try {
    templates.value = await consents.listTemplates()
  } catch {
    templates.value = []
  }
  if (professionalsAvailable.value && professionals.value.length === 0) fetchProfessionals()
})

// Choosing a template fills the text; what is typed afterwards is the
// letter's own copy.
watch(templateId, (id) => {
  const template = templates.value.find(tpl => tpl.id === id)
  if (!template || props.consent) return
  title.value = template.title
  body.value = template.body
})

async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const payload = {
      title: title.value.trim(),
      body: body.value,
      procedure_label: procedureLabel.value.trim() || null,
      explained_by_professional_id: professionalId.value ?? null
    }
    const saved = props.consent
      ? await consents.update(props.consent.id, payload)
      : await consents.create(props.patientId, {
          kind: kind.value,
          template_id: templateId.value ?? null,
          // Only an informed consent answers for a plan.
          plan_id: kind.value === 'informed' ? (props.planId ?? null) : null,
          ...payload
        })
    emit('saved', saved)
    emit('update:open', false)
  } catch (error: unknown) {
    const e = error as { data?: { detail?: string } }
    toast.add({ title: t('errors.createFailed'), description: e?.data?.detail, color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal
    :open="open"
    @update:open="(v) => emit('update:open', v)"
  >
    <template #content>
      <UCard data-testid="consent-form">
        <template #header>
          <h2 class="text-lg font-semibold">
            {{ t(consent ? 'consents.form.editTitle' : 'consents.form.newTitle') }}
          </h2>
        </template>

        <div class="space-y-4">
          <div
            v-if="!consent"
            class="grid grid-cols-1 sm:grid-cols-2 gap-4"
          >
            <UFormField :label="t('consents.form.kind')">
              <USelect
                v-model="kind"
                :items="kindOptions"
                value-key="value"
                class="w-full"
              />
            </UFormField>
            <UFormField :label="t('consents.form.template')">
              <USelect
                v-model="templateId"
                :items="templateOptions"
                value-key="value"
                class="w-full"
                :placeholder="templateOptions.length ? t('consents.form.templatePlaceholder') : t('consents.form.noTemplates')"
                :disabled="templateOptions.length === 0"
              />
            </UFormField>
          </div>

          <UFormField
            :label="t('consents.form.title')"
            required
          >
            <UInput
              v-model="title"
              class="w-full"
            />
          </UFormField>

          <UFormField
            v-if="kind !== 'data_use'"
            :label="t('consents.form.procedure')"
            :hint="t('consents.form.procedureHint')"
          >
            <UInput
              v-model="procedureLabel"
              class="w-full"
            />
          </UFormField>

          <UFormField
            :label="t('consents.form.body')"
            :hint="t({ informed: 'consents.form.bodyHintInformed', data_use: 'consents.form.bodyHintData', conformity: 'consents.form.bodyHintConformity' }[kind])"
            required
          >
            <UTextarea
              v-model="body"
              :rows="9"
              class="w-full"
            />
          </UFormField>

          <UFormField
            v-if="kind === 'informed'"
            :label="t('consents.form.explainedBy')"
            :hint="t('consents.form.explainedByHint')"
          >
            <USelect
              v-if="professionalsAvailable"
              v-model="professionalId"
              :items="professionalOptions"
              value-key="value"
              class="w-full"
              :placeholder="t('consents.form.explainedByPlaceholder')"
            />
            <p
              v-else
              class="text-sm text-muted"
            >
              {{ t('consents.form.professionalsUnavailable') }}
            </p>
          </UFormField>
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
              :loading="saving"
              data-testid="consent-form-save"
              @click="save"
            >
              {{ t('consents.form.saveDraft') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
