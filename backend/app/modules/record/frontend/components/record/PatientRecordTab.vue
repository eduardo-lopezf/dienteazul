<script setup lang="ts">
/**
 * The "Expediente" tab of the patient record (`patient.detail.tabs`).
 *
 * The whole clinical record in the order a paper *expediente* reads:
 * identification, antecedents, the dental and periodontal charts,
 * evolution, plans, imaging, consents. Nothing is stored here — every
 * section is asked of the module that owns the data, so this screen
 * cannot disagree with the screens where the data is written.
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import type { PatientRecord, RecordEntry, RecordSection } from '../../composables/useRecord'
import { detailLines, formatDate, planItems } from './recordFormat'

const props = defineProps<{ ctx: { patient: PatientExtended } }>()

const { t, te, locale } = useI18n()
const toast = useToast()
const recordApi = useRecord()
const { can } = usePermissions()

// Printing is handing the record over, and that is its own permission.
const canDisclose = computed(() => can(PERMISSIONS.record.disclose))
const discloseOpen = ref(false)
const patientName = computed(() => `${props.ctx.patient.first_name} ${props.ctx.patient.last_name}`.trim())
// Only what holds something can be handed over — retracted entries never.
const disclosable = computed(() => (record.value?.sections ?? []).filter(
  section => section.entries.some(entry => entry.status !== 'retracted')
))

async function openDisclosed(entry: RecordEntry) {
  if (!entry.source_id) return
  const tab = recordApi.reserveTab()
  try {
    await recordApi.openDocument(entry.source_id, tab)
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  }
}

const record = ref<PatientRecord | null>(null)
const loading = ref(true)
const includeRetracted = ref(false)
const hideEmpty = ref(true)

async function load() {
  loading.value = true
  try {
    record.value = await recordApi.compose(props.ctx.patient.id, includeRetracted.value)
  } catch {
    record.value = null
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loading.value = false
  }
}

onMounted(load)

const { regulation, load: loadRegulation } = useRecordRegulation()
onMounted(() => loadRegulation())
watch([() => props.ctx.patient.id, includeRetracted], load)

const professionals = computed(() => new Map(
  (record.value?.professionals ?? []).map(p => [p.id, p])
))

function author(entry: RecordEntry): string {
  const professional = entry.authored_by_professional_id
    ? professionals.value.get(entry.authored_by_professional_id)
    : undefined
  if (!professional) return ''
  const name = `${professional.first_name} ${professional.last_name}`.trim()
  return professional.license_number
    ? `${name} · ${t('record.license', { number: professional.license_number })}`
    : name
}

// Newest first inside a section: the reader wants the latest note, not the
// first one ever written. The server sorts by clinical time, oldest first.
const sections = computed(() => (record.value?.sections ?? [])
  .filter(section => !hideEmpty.value || section.entries.length > 0)
  .map(section => ({ ...section, entries: [...section.entries].reverse() }))
)

function title(section: RecordSection): string {
  return te(section.title_key) ? t(section.title_key) : section.name
}

function lines(entry: RecordEntry) {
  return detailLines(entry.detail, entry.summary, t, te, locale.value)
}

function itemStatus(status: string): string {
  const key = `record.value.status.${status}`
  return te(key) ? t(key) : status
}

const coverage = computed(() => record.value?.coverage ?? [])
const coverageMet = computed(() => coverage.value.filter(item => item.met).length)

function missingFields(fields: string[]): string {
  return fields.map(name => te(`record.field.${name}`) ? t(`record.field.${name}`) : name).join(', ')
}

const composedAt = computed(() => record.value
  ? new Date(record.value.composed_at).toLocaleString(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
  : ''
)
</script>

<template>
  <UCard
    class="mt-4"
    data-testid="patient-record"
  >
    <SectionHeader
      icon="i-lucide-book-open-text"
      class="mb-2"
    >
      <span class="truncate">{{ t('record.title') }}</span>
      <template
        v-if="canDisclose"
        #action
      >
        <UButton
          size="sm"
          icon="i-lucide-printer"
          :disabled="disclosable.length === 0"
          data-testid="record-disclose-open"
          @click="discloseOpen = true"
        >
          {{ t('record.disclose.action') }}
        </UButton>
      </template>
    </SectionHeader>

    <div class="flex items-center justify-between gap-4 flex-wrap mb-4">
      <p class="text-caption text-muted">
        {{ t('record.intro') }}
        <span v-if="composedAt">· {{ t('record.composedAt', { when: composedAt }) }}</span>
        <span
          v-if="regulation?.text"
          class="block mt-0.5"
          data-testid="record-regulation-line"
        >{{ t('regulation.label') }}: {{ regulation.text }}</span>
      </p>
      <div class="flex items-center gap-4 flex-wrap">
        <USwitch
          v-model="hideEmpty"
          size="sm"
          :label="t('record.hideEmpty')"
        />
        <USwitch
          v-model="includeRetracted"
          size="sm"
          :label="t('record.includeRetracted')"
          data-testid="record-include-retracted"
        />
      </div>
    </div>

    <div
      v-if="loading"
      class="space-y-3"
    >
      <USkeleton
        v-for="i in 4"
        :key="i"
        class="h-16 w-full"
      />
    </div>

    <EmptyState
      v-else-if="!record || sections.length === 0"
      icon="i-lucide-book-open-text"
      :title="t('record.empty.title')"
      :description="t('record.empty.description')"
    />

    <div
      v-else
      class="space-y-6"
    >
      <!-- What a dental record is expected to hold, and whether this one does. -->
      <div
        v-if="coverage.length"
        class="rounded-md border border-default p-3"
        data-testid="record-coverage"
      >
        <div class="flex items-baseline justify-between gap-2 flex-wrap mb-2">
          <h3 class="text-sm font-medium text-default">
            {{ t('record.coverage.title') }}
          </h3>
          <span class="text-caption text-muted tabular-nums">
            {{ t('record.coverage.summary', { met: coverageMet, total: coverage.length }) }}
          </span>
        </div>
        <ul class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1">
          <li
            v-for="item in coverage"
            :key="item.key"
            class="flex items-start gap-2 text-sm"
            :data-testid="`record-coverage-${item.key}`"
            :data-met="item.met"
          >
            <UIcon
              :name="item.met ? 'i-lucide-circle-check' : 'i-lucide-circle-dashed'"
              class="w-4 h-4 mt-0.5 shrink-0"
              :class="item.met ? 'text-success' : 'text-warning'"
            />
            <span :class="item.met ? 'text-muted' : 'text-default'">
              {{ t(`record.coverage.items.${item.key}`) }}
              <span
                v-if="item.missing.length"
                class="block text-caption text-subtle"
              >{{ t('record.coverage.missingFields', { fields: missingFields(item.missing) }) }}</span>
            </span>
          </li>
        </ul>
        <p class="text-caption text-subtle mt-2">
          {{ t('record.coverage.disclaimer') }}
        </p>
      </div>

      <section
        v-for="section in sections"
        :key="`${section.module}.${section.name}`"
        :data-testid="`record-section-${section.module}.${section.name}`"
      >
        <div class="flex items-baseline gap-2 border-b border-default pb-1 mb-2">
          <h3 class="text-h3 text-default">
            {{ title(section) }}
          </h3>
          <span class="text-caption text-subtle">{{ section.entries.length }}</span>
        </div>

        <p
          v-if="section.entries.length === 0"
          class="text-sm text-subtle"
        >
          {{ t('record.sectionEmpty') }}
        </p>

        <ul
          v-else
          class="divide-y divide-[var(--color-border-subtle)]"
        >
          <li
            v-for="(entry, index) in section.entries"
            :key="entry.source_id ?? index"
            class="py-2.5 grid grid-cols-1 sm:grid-cols-[7.5rem_1fr] gap-x-4 gap-y-1"
            :class="{ 'opacity-60': entry.status === 'retracted' }"
          >
            <div class="text-caption text-muted tabular-nums">
              {{ formatDate(entry.occurred_at, locale) }}
            </div>
            <div class="min-w-0 space-y-1">
              <div class="flex items-start gap-2 flex-wrap">
                <p
                  v-if="entry.summary"
                  class="text-sm text-default whitespace-pre-line min-w-0"
                  :class="{ 'line-through': entry.status === 'retracted' }"
                >
                  {{ entry.summary }}
                </p>
                <UBadge
                  v-if="entry.status !== 'active'"
                  color="neutral"
                  variant="subtle"
                  size="xs"
                >
                  {{ t(`record.status.${entry.status}`) }}
                </UBadge>
              </div>

              <dl
                v-if="lines(entry).length"
                class="flex flex-wrap gap-x-4 gap-y-0.5 text-caption"
              >
                <div
                  v-for="line in lines(entry)"
                  :key="line.key"
                  class="min-w-0"
                >
                  <dt class="inline text-subtle">
                    {{ line.label }}:
                  </dt>
                  <dd class="inline text-muted whitespace-pre-line">
                    {{ line.value }}
                  </dd>
                </div>
              </dl>

              <ul
                v-if="planItems(entry.detail).length"
                class="text-caption text-muted list-disc pl-4"
              >
                <li
                  v-for="(item, i) in planItems(entry.detail)"
                  :key="i"
                >
                  {{ item.treatment || '—' }}<span v-if="item.teeth.length"> · {{ item.teeth.join(', ') }}</span>
                  · {{ itemStatus(item.status) }}
                </li>
              </ul>

              <UButton
                v-if="canDisclose && section.name === 'disclosures' && section.module === 'record'"
                size="xs"
                color="neutral"
                variant="soft"
                icon="i-lucide-file-text"
                data-testid="record-disclosure-document"
                @click="openDisclosed(entry)"
              >
                {{ t('record.disclose.viewDocument') }}
              </UButton>

              <p
                v-if="author(entry)"
                class="text-caption text-subtle"
              >
                {{ author(entry) }}
              </p>
            </div>
          </li>
        </ul>
      </section>
    </div>

    <RecordDiscloseModal
      v-model:open="discloseOpen"
      :patient-id="ctx.patient.id"
      :patient-name="patientName"
      :sections="disclosable"
      @done="load"
    />
  </UCard>
</template>
