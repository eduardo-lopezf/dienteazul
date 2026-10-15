<script setup lang="ts">
/**
 * DataExportPanel — the clinic written out to a sealed `.dpm` file, the
 * same format the import reads. The file holds patients' data, so it is
 * always encrypted with a passphrase the person chooses here; the server
 * never stores it. Each export stays listed as the record that the data
 * left; its file can be downloaded, and removed from the server.
 */
import { PERMISSIONS } from '~~/app/config/permissions'

interface ExportJob {
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'deleted' | 'expired'
  error: string | null
  file_size: number
  entity_counts: Record<string, number>
  created_at: string
  completed_at: string | null
  /** When its file is removed from the server. */
  expires_at?: string | null
}

const MIN_PASSPHRASE = 12
const BASE = '/api/v1/migration_import/exports'

const { t, te, locale } = useI18n()
const toast = useToast()
const api = useApi()
const { can } = usePermissions()

const canExport = computed(() => can(PERMISSIONS.migrationImport.exportRun))
const exports = ref<ExportJob[]>([])
const passphrase = ref('')
const repeated = ref('')
/** Radiographs, photos and scans travel inside the file. */
const includeDocuments = ref(true)
const starting = ref(false)
let poll: ReturnType<typeof setInterval> | null = null

const passphraseError = computed(() => {
  if (!passphrase.value) return ''
  if (passphrase.value.length < MIN_PASSPHRASE) return t('migrationImport.export.tooShort', { n: MIN_PASSPHRASE })
  if (repeated.value && repeated.value !== passphrase.value) return t('migrationImport.export.mismatch')
  return ''
})
const ready = computed(() =>
  passphrase.value.length >= MIN_PASSPHRASE && passphrase.value === repeated.value
)
const busy = computed(() => exports.value.some(job => job.status === 'pending' || job.status === 'running'))

async function load() {
  try {
    exports.value = (await api.get<{ data: ExportJob[] }>(BASE)).data
  } catch {
    exports.value = []
  }
  if (busy.value && !poll) poll = setInterval(load, 2000)
  if (!busy.value && poll) {
    clearInterval(poll)
    poll = null
  }
}

async function start() {
  if (!ready.value) return
  starting.value = true
  try {
    await api.post(BASE, { passphrase: passphrase.value, include_documents: includeDocuments.value })
    passphrase.value = ''
    repeated.value = ''
    await load()
  } catch (err) {
    toast.add({ title: t('migrationImport.export.failed'), description: said(err), color: 'error' })
  } finally {
    starting.value = false
  }
}

/** What the server said — e.g. that the export does not fit in the space left. */
function said(err: unknown): string | undefined {
  const data = (err as { data?: { message?: unknown } })?.data
  return typeof data?.message === 'string' ? data.message : undefined
}

async function download(job: ExportJob) {
  const blob = await api.$api<Blob>(`${BASE}/${job.id}/download`, { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `dienteazul-${(job.completed_at ?? job.created_at).slice(0, 10)}.dpm`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

async function removeFile(job: ExportJob) {
  await api.$api(`${BASE}/${job.id}/file`, { method: 'DELETE' })
  await load()
}

function when(iso: string): string {
  return new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))
}

function size(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function contents(job: ExportJob): string {
  return Object.entries(job.entity_counts)
    .map(([type, n]) => `${te(`migrationImport.export.types.${type}`) ? t(`migrationImport.export.types.${type}`) : type}: ${n}`)
    .join(' · ')
}

const statusColor = {
  pending: 'neutral',
  running: 'info',
  completed: 'success',
  failed: 'error',
  deleted: 'neutral',
  expired: 'neutral'
} as const

onMounted(load)
onBeforeUnmount(() => {
  if (poll) clearInterval(poll)
})
</script>

<template>
  <div class="space-y-6">
    <header>
      <h2 class="text-xl font-semibold">
        {{ t('migrationImport.export.title') }}
      </h2>
      <p class="text-sm text-muted">
        {{ t('migrationImport.export.subtitle') }}
      </p>
    </header>

    <UAlert
      color="warning"
      variant="subtle"
      icon="i-lucide-shield-alert"
      :title="t('migrationImport.export.sensitiveTitle')"
      :description="`${t('migrationImport.export.sensitive')} ${t('migrationImport.export.retention')}`"
    />

    <UCard v-if="canExport">
      <div class="space-y-4">
        <UFormField
          :label="t('migrationImport.export.passphrase')"
          :help="t('migrationImport.export.passphraseHelp', { n: MIN_PASSPHRASE })"
          :error="passphraseError || undefined"
        >
          <UInput
            v-model="passphrase"
            type="password"
            autocomplete="new-password"
            class="w-full max-w-md"
            data-testid="export-passphrase"
          />
        </UFormField>
        <UFormField :label="t('migrationImport.export.repeat')">
          <UInput
            v-model="repeated"
            type="password"
            autocomplete="new-password"
            class="w-full max-w-md"
            data-testid="export-passphrase-repeat"
          />
        </UFormField>
        <UCheckbox
          v-model="includeDocuments"
          :label="t('migrationImport.export.includeDocuments')"
          :description="t('migrationImport.export.includeDocumentsHelp')"
          data-testid="export-include-documents"
        />
        <UButton
          icon="i-lucide-hard-drive-download"
          :disabled="!ready || busy"
          :loading="starting"
          data-testid="export-start"
          @click="start"
        >
          {{ t('migrationImport.export.start') }}
        </UButton>
      </div>
    </UCard>

    <section>
      <h3 class="font-semibold">
        {{ t('migrationImport.export.history') }}
      </h3>
      <p
        v-if="!exports.length"
        class="mt-2 text-sm text-muted"
      >
        {{ t('migrationImport.export.none') }}
      </p>
      <ul
        v-else
        class="mt-2 divide-y divide-default"
      >
        <li
          v-for="job in exports"
          :key="job.id"
          class="flex flex-wrap items-center justify-between gap-3 py-3"
          data-testid="export-row"
        >
          <div class="min-w-0 space-y-1 text-sm">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-medium">{{ when(job.created_at) }}</span>
              <UBadge
                :color="statusColor[job.status]"
                variant="subtle"
                size="sm"
              >
                {{ t(`migrationImport.export.status.${job.status}`) }}
              </UBadge>
              <span
                v-if="job.status === 'completed'"
                class="text-muted"
              >{{ size(job.file_size) }}</span>
            </div>
            <p
              v-if="job.status === 'completed' || job.status === 'deleted' || job.status === 'expired'"
              class="text-muted"
            >
              {{ contents(job) }}
            </p>
            <p
              v-if="job.expires_at"
              class="text-caption text-subtle"
              data-testid="export-expires"
            >
              {{ t('migrationImport.export.expires', { when: when(job.expires_at) }) }}
            </p>
            <p
              v-if="job.error"
              class="text-error"
            >
              {{ job.error }}
            </p>
          </div>
          <div
            v-if="job.status === 'completed' && canExport"
            class="flex gap-2"
          >
            <UButton
              icon="i-lucide-download"
              variant="soft"
              data-testid="export-download"
              @click="download(job)"
            >
              {{ t('migrationImport.export.download') }}
            </UButton>
            <UButton
              icon="i-lucide-trash-2"
              color="error"
              variant="ghost"
              data-testid="export-remove"
              @click="removeFile(job)"
            >
              {{ t('migrationImport.export.remove') }}
            </UButton>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
