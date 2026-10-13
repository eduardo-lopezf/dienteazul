<script setup lang="ts">
/**
 * The clinic's consent texts: one per procedure for informed consent, and
 * the privacy notice a patient accepts for the use of their data.
 *
 * The wording is the clinic's and its lawyer's — nothing here is supplied
 * as legal text. Editing a template is a new version and never changes a
 * letter already written from it.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { ConsentKind, ConsentTemplate } from '../../composables/useConsents'

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const consents = useConsents()

const canEdit = computed(() => can(PERMISSIONS.consents.templatesWrite))

const templates = ref<ConsentTemplate[]>([])
const loading = ref(true)
const open = ref(false)
const editing = ref<ConsentTemplate | null>(null)
const kind = ref<ConsentKind>('informed')
const title = ref('')
const body = ref('')
const saving = ref(false)

const kindOptions = computed(() => [
  { label: t('consents.kinds.informed'), value: 'informed' },
  { label: t('consents.kinds.data_use'), value: 'data_use' },
  { label: t('consents.kinds.conformity'), value: 'conformity' }
])

// Whether a treatment plan waits for a signed informed consent.
const requireForPlan = ref(true)
const savingRule = ref(false)

async function setRequireForPlan(value: boolean) {
  savingRule.value = true
  try {
    requireForPlan.value = (await consents.saveSettings({ require_informed_for_plan: value })).require_informed_for_plan
    toast.add({ title: t('consents.rule.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    savingRule.value = false
  }
}

async function load() {
  loading.value = true
  try {
    requireForPlan.value = (await consents.getSettings()).require_informed_for_plan
    templates.value = await consents.listTemplates({ includeInactive: true })
  } catch {
    templates.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

function edit(template: ConsentTemplate | null) {
  editing.value = template
  kind.value = template?.kind ?? 'informed'
  title.value = template?.title ?? ''
  body.value = template?.body ?? ''
  open.value = true
}

async function save() {
  if (!title.value.trim() || !body.value.trim() || saving.value) return
  saving.value = true
  try {
    if (editing.value) {
      await consents.updateTemplate(editing.value.id, { title: title.value.trim(), body: body.value })
    } else {
      await consents.createTemplate({ kind: kind.value, title: title.value.trim(), body: body.value })
    }
    open.value = false
    await load()
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

async function toggle(template: ConsentTemplate) {
  try {
    await consents.updateTemplate(template.id, { is_active: !template.is_active })
    await load()
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  }
}
</script>

<template>
  <div
    class="space-y-4"
    data-testid="consent-templates"
  >
    <div
      class="rounded-md border border-default p-4 flex items-start gap-3"
      data-testid="consent-rule"
    >
      <USwitch
        :model-value="requireForPlan"
        :disabled="!canEdit || savingRule || loading"
        :aria-label="t('consents.rule.title')"
        class="mt-0.5"
        data-testid="consent-rule-switch"
        @update:model-value="(value: boolean) => setRequireForPlan(value)"
      />
      <div>
        <p class="font-medium text-default">
          {{ t('consents.rule.title') }}
        </p>
        <p class="text-caption text-muted">
          {{ t('consents.rule.description') }}
        </p>
      </div>
    </div>

    <div class="flex items-start justify-between gap-4 flex-wrap">
      <p class="text-sm text-muted max-w-2xl">
        {{ t('consents.templates.intro') }}
      </p>
      <UButton
        v-if="canEdit"
        icon="i-lucide-plus"
        data-testid="consent-template-new"
        @click="edit(null)"
      >
        {{ t('consents.templates.new') }}
      </UButton>
    </div>

    <USkeleton
      v-if="loading"
      class="h-24 w-full"
    />

    <EmptyState
      v-else-if="templates.length === 0"
      icon="i-lucide-file-text"
      :title="t('consents.templates.emptyTitle')"
      :description="t('consents.templates.emptyDescription')"
    />

    <UCard v-else>
      <ul class="divide-y divide-[var(--color-border-subtle)]">
        <li
          v-for="template in templates"
          :key="template.id"
          class="flex items-center gap-3 py-3 first:pt-0 last:pb-0 flex-wrap"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span
                class="font-medium"
                :class="template.is_active ? 'text-default' : 'text-subtle line-through'"
              >{{ template.title }}</span>
              <UBadge
                color="neutral"
                variant="subtle"
                size="xs"
              >
                {{ t(`consents.kinds.${template.kind}`) }}
              </UBadge>
              <span class="text-caption text-subtle">v{{ template.version }}</span>
            </div>
            <p class="text-caption text-muted truncate">
              {{ template.body }}
            </p>
          </div>
          <div
            v-if="canEdit"
            class="flex gap-2"
          >
            <UButton
              size="xs"
              variant="ghost"
              color="neutral"
              icon="i-lucide-pencil"
              @click="edit(template)"
            >
              {{ t('common.edit') }}
            </UButton>
            <UButton
              size="xs"
              variant="ghost"
              color="neutral"
              @click="toggle(template)"
            >
              {{ t(template.is_active ? 'consents.templates.retire' : 'consents.templates.restore') }}
            </UButton>
          </div>
        </li>
      </ul>
    </UCard>

    <UModal v-model:open="open">
      <template #content>
        <UCard>
          <template #header>
            <h2 class="text-lg font-semibold">
              {{ t(editing ? 'consents.templates.editTitle' : 'consents.templates.new') }}
            </h2>
          </template>
          <div class="space-y-4">
            <UFormField
              v-if="!editing"
              :label="t('consents.form.kind')"
            >
              <USelect
                v-model="kind"
                :items="kindOptions"
                value-key="value"
                class="w-full"
              />
            </UFormField>
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
              :label="t('consents.form.body')"
              :hint="t({ informed: 'consents.form.bodyHintInformed', data_use: 'consents.form.bodyHintData', conformity: 'consents.form.bodyHintConformity' }[kind])"
              required
            >
              <UTextarea
                v-model="body"
                :rows="10"
                class="w-full"
              />
            </UFormField>
          </div>
          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                color="neutral"
                variant="ghost"
                @click="open = false"
              >
                {{ t('common.cancel') }}
              </UButton>
              <UButton
                :loading="saving"
                :disabled="!title.trim() || !body.trim()"
                data-testid="consent-template-save"
                @click="save"
              >
                {{ t('common.save') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
