<script setup lang="ts">
/**
 * AsaCard — the patient's ASA physical status on the Resumen.
 *
 * Shows the current class with its date and who made it, and opens the
 * dialog where a clinician assesses again and reads the history. An
 * assessment is never edited: a new one supersedes it, a mistaken one is
 * retracted (ADR 0032).
 *
 * Registered into ``patient.summary.cards`` by patients_clinical.
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~/config/permissions'
import type { AsaStatus } from '../../composables/useAsaAssessments'
import { ASA_CLASSES, ASA_NUMERALS } from '../../composables/useAsaAssessments'

interface Ctx {
  patient: PatientExtended
}

const props = defineProps<{ ctx: Ctx }>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const toast = useToast()
const asa = useAsaAssessments()
// Inside a widget example nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

const patientId = computed(() => props.ctx.patient.id)
const canAssess = computed(() => can(PERMISSIONS.asa.write))

const state = ref<AsaStatus>({ current: null, history: [] })
const loading = ref(true)
const open = ref(false)
const saving = ref(false)

const draftClass = ref<number | null>(null)
const draftEmergency = ref(false)
const draftRationale = ref('')

async function load() {
  if (preview) {
    loading.value = false
    return
  }
  try {
    state.value = await asa.status(patientId.value)
  } catch {
    state.value = { current: null, history: [] }
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(patientId, load)

const current = computed(() => state.value.current)

/** III asks for precautions; IV and above is not for the chair. */
const severity = computed<'neutral' | 'success' | 'warning' | 'danger'>(() => {
  const value = current.value?.asa_class
  if (!value) return 'neutral'
  if (value >= 4) return 'danger'
  if (value === 3) return 'warning'
  return 'success'
})

function day(value: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium' }).format(new Date(value))
}

function openDialog() {
  draftClass.value = null
  draftEmergency.value = false
  draftRationale.value = ''
  open.value = true
}

async function save() {
  if (draftClass.value === null) return
  saving.value = true
  try {
    await asa.assess(patientId.value, {
      asa_class: draftClass.value,
      is_emergency: draftEmergency.value,
      rationale: draftRationale.value.trim() || null
    })
    await load()
    draftClass.value = null
    draftEmergency.value = false
    draftRationale.value = ''
    toast.add({ title: t('asa.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

async function retract(id: string) {
  // Taken back, with a reason — never deleted (ADR 0032).
  const reason = window.prompt(t('asa.retractPrompt'))
  if (reason === null) return
  try {
    await asa.retract(patientId.value, id, reason)
    await load()
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  }
}
</script>

<template>
  <!-- The dialog sits beside the card, not inside it: the card does not
       render its body while it has nothing to show. -->
  <div class="contents">
    <SummaryCard
      :title="t('asa.title')"
      icon="i-lucide-shield-plus"
      :severity="severity"
      :loading="loading"
      :empty="!current"
      data-testid="asa-card"
    >
      <template #empty>
        <p>{{ t('asa.empty') }}</p>
        <UButton
          size="xs"
          variant="soft"
          class="mt-2"
          :icon="canAssess ? 'i-lucide-plus' : 'i-lucide-history'"
          data-testid="asa-open"
          @click="openDialog"
        >
          {{ canAssess ? t('asa.assess') : t('asa.history') }}
        </UButton>
      </template>

      <div
        v-if="current"
        class="space-y-1"
      >
        <p
          class="text-2xl font-semibold text-default tabular-nums"
          data-testid="asa-current"
        >
          ASA {{ current.label }}
        </p>
        <p class="text-caption text-muted">
          {{ t(`asa.classes.${current.asa_class}`) }}
        </p>
        <p class="text-caption text-subtle">
          {{ day(current.assessed_at) }}<template v-if="current.assessed_by_name">
            · {{ current.assessed_by_name }}
          </template>
        </p>
        <UButton
          size="xs"
          variant="soft"
          class="mt-1"
          :icon="canAssess ? 'i-lucide-refresh-cw' : 'i-lucide-history'"
          data-testid="asa-open"
          @click="openDialog"
        >
          {{ canAssess ? t('asa.reassess') : t('asa.history') }}
        </UButton>
      </div>
    </SummaryCard>

    <UModal
      v-model:open="open"
      :title="t('asa.title')"
      :description="t('asa.description')"
    >
      <template #body>
        <div
          class="space-y-5"
          data-testid="asa-dialog"
        >
          <div
            v-if="canAssess"
            class="space-y-3"
          >
            <div
              class="space-y-1.5"
              role="radiogroup"
              :aria-label="t('asa.class')"
            >
              <button
                v-for="value in ASA_CLASSES"
                :key="value"
                type="button"
                role="radio"
                :aria-checked="draftClass === value"
                class="flex w-full items-baseline gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors"
                :class="draftClass === value
                  ? 'border-[var(--color-primary)] bg-[var(--color-primary-soft,transparent)] ring-1 ring-[var(--color-primary)]'
                  : 'border-default hover:bg-surface-muted'"
                :data-testid="`asa-class-${value}`"
                @click="draftClass = value"
              >
                <span class="w-8 shrink-0 font-semibold text-default">{{ ASA_NUMERALS[value] }}</span>
                <span class="text-muted">{{ t(`asa.classes.${value}`) }}</span>
              </button>
            </div>

            <UCheckbox
              v-model="draftEmergency"
              :label="t('asa.emergency')"
            />

            <UFormField :label="t('asa.rationale')">
              <UTextarea
                v-model="draftRationale"
                class="w-full"
                :rows="2"
                :maxlength="2000"
                :placeholder="t('asa.rationalePlaceholder')"
                data-testid="asa-rationale"
              />
            </UFormField>

            <div class="flex justify-end">
              <UButton
                :disabled="draftClass === null"
                :loading="saving"
                icon="i-lucide-check"
                data-testid="asa-save"
                @click="save"
              >
                {{ t('asa.save') }}
              </UButton>
            </div>
          </div>

          <div>
            <p class="text-caption font-medium uppercase tracking-wide text-muted mb-2">
              {{ t('asa.history') }}
            </p>
            <p
              v-if="state.history.length === 0"
              class="text-caption text-subtle"
            >
              {{ t('asa.noHistory') }}
            </p>
            <ul
              v-else
              class="divide-y divide-[var(--color-border-subtle)]"
              data-testid="asa-history"
            >
              <li
                v-for="(item, index) in state.history"
                :key="item.id"
                class="flex items-start gap-3 py-2 text-sm"
              >
                <span class="w-14 shrink-0 font-semibold text-default">ASA {{ item.label }}</span>
                <div class="min-w-0 flex-1">
                  <p class="text-muted">
                    {{ day(item.assessed_at) }}<template v-if="item.assessed_by_name">
                      · {{ item.assessed_by_name }}
                    </template>
                    <UBadge
                      v-if="index === 0"
                      color="primary"
                      variant="subtle"
                      size="xs"
                      class="ml-1"
                    >
                      {{ t('asa.current') }}
                    </UBadge>
                  </p>
                  <p
                    v-if="item.rationale"
                    class="text-caption text-subtle"
                  >
                    {{ item.rationale }}
                  </p>
                </div>
                <UButton
                  v-if="canAssess"
                  size="xs"
                  variant="ghost"
                  color="warning"
                  icon="i-lucide-undo-2"
                  :data-testid="`asa-retract-${index}`"
                  @click="retract(item.id)"
                >
                  {{ t('asa.retract') }}
                </UButton>
              </li>
            </ul>
          </div>

          <p class="text-caption text-subtle">
            {{ t('asa.note') }}
          </p>
        </div>
      </template>
    </UModal>
  </div>
</template>
