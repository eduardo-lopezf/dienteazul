<script setup lang="ts">
/**
 * SheetMappingStep — patients, appointments or balances from an Excel or
 * CSV file.
 *
 * The person picks what the sheet holds, uploads it, says which column is
 * which field (the server suggests it from the headers) and how dates are
 * written. Appointments and balances attach to patients the clinic already
 * has; a row without a professional takes the one chosen here. The server
 * then turns the sheet into a `.dpm` and the import goes on as any other:
 * validate, preview, import. Emits `ready` with that job.
 */
interface ImportJob {
  id: string
  status: string
  original_filename: string
  file_size: number
  [key: string]: unknown
}

interface SheetColumn {
  index: number
  name: string
  samples: string[]
  suggested_field: string | null
}

type SheetKind = 'patients' | 'appointments' | 'balances'

interface SheetUpload {
  job: ImportJob
  kind: SheetKind
  columns: SheetColumn[]
  row_count: number
  fields: string[]
  professionals: Array<{ id: string, name: string }>
}

/** Columns that say who the patient is (date of birth only narrows). */
const WHO = ['full_name', 'given_name', 'family_name', 'second_family_name', 'national_id', 'email', 'phone', 'patient_number']
/** Each group: at least one of its fields needs a column. Mirrors the server. */
const REQUIRED: Record<SheetKind, Array<{ fields: string[], message: string }>> = {
  patients: [{ fields: ['given_name', 'full_name'], message: 'needsName' }],
  appointments: [
    { fields: WHO, message: 'needsWho' },
    { fields: ['appointment_date'], message: 'needsDate' }
  ],
  balances: [
    { fields: WHO, message: 'needsWho' },
    { fields: ['balance', 'owed', 'credit'], message: 'needsAmount' }
  ]
}

const emit = defineEmits<{ ready: [job: ImportJob] }>()

const { t } = useI18n()
const api = useApi()
const toast = useToast()

const BASE = '/api/v1/migration_import/sheets'
const IGNORE = '__ignore'

const kind = ref<SheetKind>('patients')
const kindItems = computed(() => (['patients', 'appointments', 'balances'] as const).map(value => ({
  label: t(`migrationImport.sheet.kinds.${value}`),
  description: t(`migrationImport.sheet.kindHelp.${value}`),
  value
})))
const defaultProfessional = ref<string | undefined>()
const file = ref<File | null>(null)
const uploading = ref(false)
const converting = ref(false)
const error = ref('')
const sheet = ref<SheetUpload | null>(null)
const mapping = ref<Record<number, string>>({})
const dateOrder = ref<'dmy' | 'mdy' | 'ymd'>('dmy')

const fieldItems = computed(() => [
  { label: t('migrationImport.sheet.ignore'), value: IGNORE },
  ...(sheet.value?.fields ?? []).map(key => ({ label: t(`migrationImport.sheet.fields.${key}`), value: key }))
])
const dateItems = computed(() => (['dmy', 'mdy', 'ymd'] as const).map(value => ({
  label: t(`migrationImport.sheet.dateOrders.${value}`),
  value
})))

/** A field may be given to one column only. */
const repeated = computed(() => {
  const used = Object.values(mapping.value).filter(field => field !== IGNORE)
  return [...new Set(used.filter((field, i) => used.indexOf(field) !== i))]
})
const professionalItems = computed(() => (sheet.value?.professionals ?? []).map(p => ({ label: p.name, value: p.id })))
/** The required groups still without a column. */
const missing = computed(() => {
  if (!sheet.value) return []
  const used = new Set(Object.values(mapping.value))
  return REQUIRED[sheet.value.kind].filter(group => !group.fields.some(field => used.has(field)))
})
const canConvert = computed(() => !!sheet.value && missing.value.length === 0 && repeated.value.length === 0)

function onFile(evt: Event) {
  file.value = (evt.target as HTMLInputElement).files?.[0] ?? null
}

function failure(err: unknown, fallback: string): string {
  const data = (err as { data?: { detail?: unknown, message?: unknown } })?.data
  const detail = data?.detail ?? data?.message
  return typeof detail === 'string' ? detail : fallback
}

async function downloadTemplate() {
  try {
    const blob = await api.$api<Blob>(`${BASE}/template?kind=${kind.value}`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = t(`migrationImport.sheet.templateNames.${kind.value}`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  } catch {
    toast.add({ title: t('migrationImport.sheet.templateFailed'), color: 'error' })
  }
}

async function upload() {
  if (!file.value) return
  uploading.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('kind', kind.value)
    sheet.value = (await api.post<{ data: SheetUpload }>(BASE, form)).data
    const offered = sheet.value.professionals
    defaultProfessional.value = offered.length === 1 ? offered[0]!.id : undefined
    mapping.value = Object.fromEntries(
      sheet.value.columns.map(column => [column.index, column.suggested_field ?? IGNORE])
    )
  } catch (err) {
    error.value = failure(err, t('migrationImport.sheet.uploadFailed'))
  } finally {
    uploading.value = false
  }
}

async function convert() {
  if (!sheet.value || !canConvert.value) return
  converting.value = true
  error.value = ''
  try {
    const chosen = Object.fromEntries(
      Object.entries(mapping.value).filter(([, field]) => field !== IGNORE)
    )
    const job = (await api.post<{ data: ImportJob }>(`${BASE}/${sheet.value.job.id}/convert`, {
      mapping: chosen,
      date_order: dateOrder.value,
      default_professional_id: sheet.value.kind === 'appointments' ? defaultProfessional.value ?? null : null
    })).data
    emit('ready', job)
  } catch (err) {
    error.value = failure(err, t('migrationImport.sheet.convertFailed'))
  } finally {
    converting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <template v-if="!sheet">
      <URadioGroup
        v-model="kind"
        :items="kindItems"
        value-key="value"
        :legend="t('migrationImport.sheet.kind')"
        data-testid="sheet-kind"
      />
      <p class="text-sm text-muted">
        {{ t(`migrationImport.sheet.intros.${kind}`) }}
      </p>
      <UButton
        icon="i-lucide-file-spreadsheet"
        variant="soft"
        data-testid="sheet-template"
        @click="downloadTemplate"
      >
        {{ t('migrationImport.sheet.template') }}
      </UButton>
      <UFormField :label="t('migrationImport.sheet.file')">
        <UInput
          type="file"
          accept=".xlsx,.csv"
          data-testid="sheet-file"
          @change="onFile"
        />
      </UFormField>
      <UButton
        :loading="uploading"
        :disabled="!file"
        data-testid="sheet-upload"
        @click="upload"
      >
        {{ t('migrationImport.sheet.upload') }}
      </UButton>
    </template>

    <template v-else>
      <p class="text-sm">
        {{ t('migrationImport.sheet.found', { rows: sheet.row_count, columns: sheet.columns.length }) }}
      </p>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b text-left">
              <th class="py-2 pr-3">
                {{ t('migrationImport.sheet.column') }}
              </th>
              <th class="py-2 pr-3">
                {{ t('migrationImport.sheet.samples') }}
              </th>
              <th class="py-2">
                {{ t('migrationImport.sheet.field') }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="column in sheet.columns"
              :key="column.index"
              class="border-b align-top"
              :data-testid="`sheet-column-${column.index}`"
            >
              <td class="py-2 pr-3 font-medium">
                {{ column.name }}
              </td>
              <td class="py-2 pr-3 text-muted">
                {{ column.samples.filter(Boolean).slice(0, 3).join(' · ') }}
              </td>
              <td class="py-2 min-w-48">
                <USelect
                  v-model="mapping[column.index]"
                  :items="fieldItems"
                  value-key="value"
                  class="w-full"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <UFormField
        :label="t('migrationImport.sheet.dateOrder')"
        :help="t('migrationImport.sheet.dateOrderHelp')"
      >
        <USelect
          v-model="dateOrder"
          :items="dateItems"
          value-key="value"
          class="w-full max-w-xs"
        />
      </UFormField>

      <UFormField
        v-if="sheet.kind === 'appointments' && professionalItems.length"
        :label="t('migrationImport.sheet.defaultProfessional')"
        :help="t('migrationImport.sheet.defaultProfessionalHelp')"
      >
        <USelect
          v-model="defaultProfessional"
          :items="professionalItems"
          value-key="value"
          class="w-full max-w-xs"
          data-testid="sheet-default-professional"
        />
      </UFormField>

      <UAlert
        v-for="group in missing"
        :key="group.message"
        color="warning"
        variant="subtle"
        :title="t(`migrationImport.sheet.${group.message}`)"
      />
      <UAlert
        v-if="repeated.length"
        color="warning"
        variant="subtle"
        :title="t('migrationImport.sheet.repeated', { fields: repeated.map(f => t(`migrationImport.sheet.fields.${f}`)).join(', ') })"
      />

      <div class="flex gap-2">
        <UButton
          :loading="converting"
          :disabled="!canConvert"
          data-testid="sheet-convert"
          @click="convert"
        >
          {{ t('migrationImport.sheet.convert') }}
        </UButton>
        <UButton
          variant="ghost"
          color="neutral"
          @click="sheet = null"
        >
          {{ t('migrationImport.sheet.other') }}
        </UButton>
      </div>
    </template>

    <UAlert
      v-if="error"
      color="error"
      variant="subtle"
      :description="error"
    />
  </div>
</template>
