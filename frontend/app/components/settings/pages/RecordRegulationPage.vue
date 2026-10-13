<script setup lang="ts">
/**
 * The regulation the clinic's clinical record refers to (Settings →
 * General → Normativa del expediente).
 *
 * One line of text, the clinic's. It is set here, in the Workspace,
 * because the health questionnaire prints it too and that one belongs to
 * another App than the record.
 */
import { PERMISSIONS } from '~/config/permissions'

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { regulation, load, save } = useRecordRegulation()

const canEdit = computed(() => can(PERMISSIONS.admin.clinicWrite))
const text = ref('')
const loaded = ref(false)
const saving = ref(false)

function show() {
  text.value = regulation.value?.text ?? ''
}

onMounted(async () => {
  await load(true)
  show()
  loaded.value = true
})

const dirty = computed(() => text.value.trim() !== (regulation.value?.text ?? ''))

async function store(value: string | null) {
  saving.value = true
  try {
    await save(value)
    show()
    toast.add({ title: t('regulation.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <SectionCard
    icon="i-lucide-scale"
    :title="t('regulation.title')"
  >
    <p class="text-caption text-muted mb-4">
      {{ t('regulation.intro') }}
    </p>

    <USkeleton
      v-if="!loaded"
      class="h-20 w-full"
    />

    <div
      v-else
      class="space-y-3"
      data-testid="record-regulation"
    >
      <UFormField
        :label="t('regulation.field')"
        :help="regulation?.is_default && regulation.default ? t('regulation.usingDefault') : t('regulation.emptyHint')"
      >
        <UInput
          v-model="text"
          class="w-full"
          :maxlength="300"
          :disabled="!canEdit"
          :placeholder="t('regulation.placeholder')"
          data-testid="record-regulation-input"
        />
      </UFormField>

      <div
        v-if="canEdit"
        class="flex items-center gap-2 flex-wrap"
      >
        <UButton
          icon="i-lucide-save"
          :disabled="!dirty"
          :loading="saving"
          data-testid="record-regulation-save"
          @click="store(text.trim())"
        >
          {{ t('regulation.save') }}
        </UButton>
        <UButton
          v-if="regulation?.default && !regulation.is_default"
          color="neutral"
          variant="ghost"
          icon="i-lucide-rotate-ccw"
          :disabled="saving"
          data-testid="record-regulation-restore"
          @click="store(null)"
        >
          {{ t('regulation.restore') }}
        </UButton>
      </div>
    </div>
  </SectionCard>
</template>
