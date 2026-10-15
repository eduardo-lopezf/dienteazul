<script setup lang="ts">
/**
 * ImportHistory — the clinic's imports, and undoing one.
 *
 * Undoing removes exactly what the import created (ADR 0055). The server
 * refuses when the clinic has worked on the imported data since — an
 * appointment booked, a note written — and says what it found; that
 * message is shown as it comes.
 */
import { PERMISSIONS } from '~~/app/config/permissions'

interface ImportJob {
  id: string
  status: string
  original_filename: string
  source_system: string | null
  total_entities: number
  processed_entities: number
  created_at: string
  tracks_created?: boolean
  undone_at?: string | null
  undo_error?: string | null
}

const { t, te, locale } = useI18n()
const api = useApi()
const toast = useToast()
const { can } = usePermissions()

const jobs = ref<ImportJob[]>([])
const asking = ref<ImportJob | null>(null)
const undoing = ref(false)
let poll: ReturnType<typeof setInterval> | null = null

const canUndo = computed(() => can(PERMISSIONS.migrationImport.jobExecute))
const showAsk = computed({
  get: () => asking.value !== null,
  set: (open) => { if (!open) asking.value = null }
})

function undoable(job: ImportJob): boolean {
  return !!job.tracks_created && (job.status === 'completed' || job.status === 'failed')
}

async function load() {
  try {
    jobs.value = (await api.get<{ data: ImportJob[] }>('/api/v1/migration_import/jobs?page_size=20')).data
  } catch {
    jobs.value = []
  }
  const busy = jobs.value.some(job => job.status === 'undoing')
  if (busy && !poll) poll = setInterval(load, 2000)
  if (!busy && poll) {
    clearInterval(poll)
    poll = null
  }
}

function failure(err: unknown): string {
  const data = (err as { data?: { message?: unknown, detail?: unknown } })?.data
  const said = data?.message ?? data?.detail
  return typeof said === 'string' ? said : t('migrationImport.history.undoFailed')
}

async function undo() {
  const job = asking.value
  if (!job) return
  undoing.value = true
  try {
    await api.post(`/api/v1/migration_import/jobs/${job.id}/undo`, {})
    toast.add({ title: t('migrationImport.history.undoStarted'), color: 'success' })
  } catch (err) {
    toast.add({ title: t('migrationImport.history.undoRefused'), description: failure(err), color: 'error' })
  } finally {
    undoing.value = false
    asking.value = null
    await load()
  }
}

function when(iso: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
}

function status(job: ImportJob): string {
  const key = `migrationImport.status.${job.status}`
  return te(key) ? t(key) : job.status
}

onMounted(load)
onBeforeUnmount(() => {
  if (poll) clearInterval(poll)
})
defineExpose({ load })
</script>

<template>
  <section v-if="jobs.length">
    <h3 class="font-semibold">
      {{ t('migrationImport.history.title') }}
    </h3>
    <ul class="mt-2 divide-y divide-default">
      <li
        v-for="job in jobs"
        :key="job.id"
        class="flex flex-wrap items-center justify-between gap-3 py-3"
        data-testid="import-row"
      >
        <div class="min-w-0 space-y-1 text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <span class="font-medium">{{ job.original_filename }}</span>
            <UBadge
              :color="job.status === 'undone' ? 'neutral' : job.status === 'failed' ? 'error' : job.status === 'completed' ? 'success' : 'info'"
              variant="subtle"
              size="sm"
            >
              {{ status(job) }}
            </UBadge>
          </div>
          <p class="text-muted">
            {{ when(job.created_at) }} · {{ t('migrationImport.history.records', { n: job.processed_entities }) }}
          </p>
          <p
            v-if="job.undo_error"
            class="text-error"
          >
            {{ job.undo_error }}
          </p>
        </div>
        <UButton
          v-if="canUndo && undoable(job)"
          icon="i-lucide-undo-2"
          color="error"
          variant="soft"
          size="sm"
          :data-testid="`import-undo-${job.id}`"
          @click="asking = job"
        >
          {{ t('migrationImport.history.undo') }}
        </UButton>
      </li>
    </ul>

    <UModal
      v-model:open="showAsk"
      :title="t('migrationImport.history.confirmTitle')"
      :description="t('migrationImport.history.confirmBody', { file: asking?.original_filename ?? '' })"
    >
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            @click="asking = null"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            color="error"
            icon="i-lucide-undo-2"
            :loading="undoing"
            data-testid="import-undo-confirm"
            @click="undo"
          >
            {{ t('migrationImport.history.undoConfirm') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </section>
</template>
