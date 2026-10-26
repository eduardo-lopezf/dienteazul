<script setup lang="ts">
/**
 * The "Cuestionario de salud" tab of the patient record
 * (`patient.detail.tabs`): what the patient declared at each visit.
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import type { FormKind, HealthQuestionnaire } from '../../composables/useHealthQuestionnaires'
import { FORM_KINDS, questionsOf, suggestedForm } from '../../composables/useHealthQuestionnaires'

const props = defineProps<{ ctx: { patient: PatientExtended } }>()

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const questionnaires = useHealthQuestionnaires()

const canWrite = computed(() => can(PERMISSIONS.medicalHistory.write))
const items = ref<HealthQuestionnaire[]>([])
const loading = ref(true)
const formOpen = ref(false)
/** The saved questionnaire open read-only, if any. */
const viewed = ref<HealthQuestionnaire | null>(null)
const viewOpen = ref(false)

function view(item: HealthQuestionnaire) {
  viewed.value = item
  viewOpen.value = true
}

async function load() {
  loading.value = true
  try {
    items.value = await questionnaires.list(props.ctx.patient.id)
  } catch {
    items.value = []
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => props.ctx.patient.id, load)

function when(item: HealthQuestionnaire): string {
  return new Date(item.taken_at).toLocaleDateString(locale.value, { day: '2-digit', month: 'short', year: 'numeric' })
}

function positives(item: HealthQuestionnaire): string[] {
  return questionsOf(item.form_kind).filter(key => item.answers[key]?.answer)
}

function summary(item: HealthQuestionnaire): string {
  if (item.scan_document_id) return t('healthQuestionnaire.onPaper')
  const yes = positives(item).length
  return [
    yes ? t('healthQuestionnaire.positives', { count: yes }) : t('healthQuestionnaire.noPositives'),
    item.conditions.length && t('healthQuestionnaire.conditionsCount', { count: item.conditions.length })
  ].filter(Boolean).join(' · ')
}

async function show(action: (tab: Window | null) => Promise<void>) {
  const tab = questionnaires.reserveTab()
  try {
    await action(tab)
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  }
}

function printBlank(kind: FormKind) {
  show(tab => questionnaires.openBlankForm(props.ctx.patient.id, locale.value, tab, kind))
}

// Both blank forms, the one for this patient's age first.
const printItems = computed(() => {
  const first = suggestedForm(props.ctx.patient.date_of_birth)
  return [first, ...FORM_KINDS.filter(kind => kind !== first)].map(kind => ({
    label: t(`healthQuestionnaire.forms.${kind}`),
    icon: kind === 'pediatric' ? 'i-lucide-baby' : 'i-lucide-user',
    onSelect: () => printBlank(kind)
  }))
})

async function retract(item: HealthQuestionnaire) {
  // Taken back, with a reason — never deleted (ADR 0032).
  const reason = window.prompt(t('healthQuestionnaire.retractPrompt'))
  if (reason === null) return
  try {
    await questionnaires.retract(props.ctx.patient.id, item.id, reason)
    await load()
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  }
}
</script>

<template>
  <UCard
    class="mt-4"
    data-testid="patient-questionnaires"
  >
    <SectionHeader
      icon="i-lucide-clipboard-list"
      class="mb-4"
    >
      <span class="truncate">{{ t('healthQuestionnaire.title') }}</span>
      <template #action>
        <div class="flex gap-2">
          <UDropdownMenu :items="printItems">
            <UButton
              size="sm"
              color="neutral"
              variant="soft"
              icon="i-lucide-printer"
              trailing-icon="i-lucide-chevron-down"
              data-testid="questionnaire-print-blank"
            >
              {{ t('healthQuestionnaire.printBlank') }}
            </UButton>
          </UDropdownMenu>
          <UButton
            v-if="canWrite"
            size="sm"
            icon="i-lucide-plus"
            data-testid="questionnaire-new"
            @click="formOpen = true"
          >
            {{ t('healthQuestionnaire.new') }}
          </UButton>
        </div>
      </template>
    </SectionHeader>

    <div
      v-if="loading"
      class="space-y-3"
    >
      <USkeleton
        v-for="i in 2"
        :key="i"
        class="h-14 w-full"
      />
    </div>

    <EmptyState
      v-else-if="items.length === 0"
      icon="i-lucide-clipboard-list"
      :title="t('healthQuestionnaire.empty.title')"
      :description="t('healthQuestionnaire.empty.description')"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="item in items"
        :key="item.id"
        class="py-3 first:pt-0 last:pb-0"
        data-testid="questionnaire-row"
      >
        <div class="flex items-center gap-3 flex-wrap">
          <div class="min-w-0 flex-1">
            <p class="font-medium text-default">
              {{ item.chief_complaint || t('healthQuestionnaire.title') }}
            </p>
            <p class="text-caption text-muted">
              <UBadge
                v-if="item.form_kind === 'pediatric'"
                color="info"
                variant="subtle"
                size="xs"
                class="mr-1"
                icon="i-lucide-baby"
                data-testid="questionnaire-pediatric"
              >
                {{ t('healthQuestionnaire.pediatric.badge') }}
              </UBadge>
              {{ when(item) }} · {{ summary(item) }}
              <UBadge
                v-if="item.signed_at"
                color="success"
                variant="subtle"
                size="xs"
                class="ml-1"
                icon="i-lucide-pen-line"
                data-testid="questionnaire-signed"
              >
                {{ t('healthQuestionnaire.sign.signed') }}
              </UBadge>
            </p>
          </div>
          <div class="flex gap-2">
            <UButton
              v-if="item.scan_document_id"
              size="xs"
              variant="ghost"
              color="neutral"
              icon="i-lucide-file-check"
              @click="show(tab => questionnaires.openScan(item.scan_document_id!, tab))"
            >
              {{ t('healthQuestionnaire.viewScan') }}
            </UButton>
            <UButton
              v-else
              size="xs"
              variant="ghost"
              color="neutral"
              icon="i-lucide-eye"
              data-testid="questionnaire-view-open"
              @click="view(item)"
            >
              {{ t('healthQuestionnaire.view') }}
            </UButton>
            <UButton
              v-if="canWrite"
              size="xs"
              variant="ghost"
              color="warning"
              icon="i-lucide-undo-2"
              @click="retract(item)"
            >
              {{ t('healthQuestionnaire.retract') }}
            </UButton>
          </div>
        </div>
      </li>
    </ul>

    <HealthQuestionnaireModal
      v-model:open="formOpen"
      :patient-id="ctx.patient.id"
      :patient-name="`${ctx.patient.first_name} ${ctx.patient.last_name}`.trim()"
      :patient-birth-date="ctx.patient.date_of_birth"
      @saved="load"
    />
    <HealthQuestionnaireModal
      v-model:open="viewOpen"
      :patient-id="ctx.patient.id"
      :questionnaire="viewed"
    />
  </UCard>
</template>
