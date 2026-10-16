<script setup lang="ts">
/**
 * Por cobrar — the clinic's receivable as a list of people, oldest first.
 *
 * The aging report could already say "seven patients owe 12.400 at 90+",
 * and gave no way to learn which seven: clicking any of the four buckets
 * went to `/patients?with_debt=true`, the same place for all of them, with
 * the age thrown away. So the number was looked at and nothing followed
 * from it. Budgets have a cron that chases them; money owed had nothing.
 *
 * The order is the argument: oldest debt on top, because that is the money
 * most at risk and the order a person would work in. Everything a call
 * needs is on the row — the phone, how long it has been, when they last
 * paid anything — so that working the list never means opening eight
 * records to find eight phone numbers.
 *
 * Each row also carries when it was last chased, and the note button adds
 * to that. It is what keeps two people from calling the same patient on the
 * same morning, and it is deliberately a note about an *attempt*: if the
 * call worked there is a payment to show for it, so the row can say "called
 * yesterday, still owes 300" — a sentence neither record could make alone.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import { formatDateOnly } from '~~/app/utils/date'

interface ReceivablePatient {
  id: string
  first_name: string
  last_name: string
  phone: string | null
}

interface ReceivableRow {
  patient: ReceivablePatient
  receivable: string
  oldest_unpaid_at: string | null
  age_days: number
  bucket: string
  last_payment_at: string | null
  last_contact_at: string | null
  last_contact_channel: string | null
}

const { t, locale } = useI18n()
const api = useApi()
const { can } = usePermissions()
const { patientsAvailable } = useFinanceLinks()
const { format: money } = useCurrency()

const BUCKETS = ['0-30', '31-60', '61-90', '90+'] as const

const route = useRoute()
const router = useRouter()

const rows = ref<ReceivableRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

/**
 * Hydrated from the URL so the aging report's buckets can land here
 * already filtered — clicking "90+" and arriving at everything would throw
 * away the only thing that click said.
 */
function bucketFromQuery(): string | null {
  const wanted = route.query.bucket
  return typeof wanted === 'string' && (BUCKETS as readonly string[]).includes(wanted)
    ? wanted
    : null
}

const bucket = ref<string | null>(bucketFromQuery())
const search = ref('')
const loading = ref(true)
const failed = ref(false)

const collecting = ref<ReceivableRow | null>(null)
const contacting = ref<ReceivableRow | null>(null)

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(search, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    void load()
  }, 300)
})

watch(bucket, (next) => {
  page.value = 1
  // Mirrored back so the filter survives a reload and can be linked to.
  void router.replace({ query: { ...route.query, bucket: next ?? undefined } })
  void load()
})

async function load() {
  loading.value = rows.value.length === 0
  failed.value = false
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize)
    })
    if (bucket.value) params.set('bucket', bucket.value)
    if (search.value.trim()) params.set('q', search.value.trim())
    const response = await api.get<{ data: ReceivableRow[], total: number }>(
      `/api/v1/payments/receivables?${params.toString()}`
    )
    rows.value = response.data ?? []
    total.value = response.total ?? 0
  } catch {
    failed.value = true
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

onMounted(load)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

function changePage(next: number) {
  page.value = next
  void load()
}

function patientName(row: ReceivableRow): string {
  return `${row.patient.first_name} ${row.patient.last_name}`.trim()
}

/** Colour by how long it has been. Ninety days is a different conversation. */
function bucketColor(value: string): 'neutral' | 'warning' | 'error' {
  if (value === '90+') return 'error'
  if (value === '61-90' || value === '31-60') return 'warning'
  return 'neutral'
}

function call(row: ReceivableRow) {
  if (!row.patient.phone) return
  window.location.href = `tel:${row.patient.phone}`
}

function whatsapp(row: ReceivableRow) {
  if (!row.patient.phone) return
  window.open(`https://wa.me/${row.patient.phone.replace(/\D/g, '')}`, '_blank', 'noopener')
}

function onCollected() {
  collecting.value = null
  void load()
}

function onContacted() {
  contacting.value = null
  void load()
}

/**
 * Chased today, by anyone. Shown as a state on the row rather than as a
 * filter, because a patient rung this morning is still owed money and
 * hiding them would make the list disagree with the total above it.
 */
function chasedToday(row: ReceivableRow): boolean {
  if (!row.last_contact_at) return false
  const when = new Date(row.last_contact_at)
  const now = new Date()
  return when.toDateString() === now.toDateString()
}
</script>

<template>
  <div class="receivables">
    <!-- A row is a patient to call: none is listed while Patients is off. -->
    <UAlert
      v-if="!patientsAvailable"
      color="info"
      variant="subtle"
      icon="i-lucide-info"
      :description="t('finance.appsOff.patients')"
      data-testid="receivables-patients-off"
    />
    <div class="receivables-toolbar">
      <UInput
        v-model="search"
        :placeholder="t('payments.receivables.search')"
        icon="i-lucide-search"
        class="max-w-xs"
      />
      <div class="bucket-chips">
        <UButton
          v-for="value in BUCKETS"
          :key="value"
          size="xs"
          :color="bucket === value ? 'primary' : 'neutral'"
          :variant="bucket === value ? 'solid' : 'outline'"
          @click="bucket = bucket === value ? null : value"
        >
          {{ t('payments.receivables.bucket', { range: value }) }}
        </UButton>
      </div>
    </div>

    <div
      v-if="loading"
      class="receivables-state"
    >
      <USkeleton class="h-16 w-full" />
      <USkeleton class="h-16 w-full" />
    </div>

    <div
      v-else-if="failed"
      class="receivables-state text-caption text-muted"
    >
      {{ t('payments.receivables.failed') }}
    </div>

    <div
      v-else-if="rows.length === 0"
      class="receivables-empty"
    >
      <UIcon
        name="i-lucide-check-circle-2"
        class="w-6 h-6 text-success-accent"
      />
      <p>{{ bucket || search ? t('payments.receivables.noMatches') : t('payments.receivables.allSettled') }}</p>
    </div>

    <ul
      v-else
      class="receivables-list"
    >
      <li
        v-for="row in rows"
        :key="row.patient.id"
        class="receivable-row"
      >
        <div class="min-w-0 flex-1">
          <NuxtLink
            :to="`/patients/${row.patient.id}`"
            class="receivable-name"
          >
            {{ patientName(row) }}
          </NuxtLink>
          <p class="receivable-meta">
            <UBadge
              :color="bucketColor(row.bucket)"
              variant="subtle"
              size="xs"
            >
              {{ t('payments.receivables.days', { n: row.age_days }) }}
            </UBadge>
            <span v-if="row.last_payment_at">
              · {{ t('payments.receivables.lastPaid', {
                date: formatDateOnly(row.last_payment_at, locale)
              }) }}
            </span>
            <span v-else>· {{ t('payments.receivables.neverPaid') }}</span>
            <!-- The half that stops two people ringing the same patient
                 before lunch. Today's chase is called out; an older one
                 just carries its date. -->
            <UBadge
              v-if="chasedToday(row)"
              color="info"
              variant="subtle"
              size="xs"
            >
              {{ t('payments.receivables.chasedToday', {
                channel: t(`payments.contact.channels.${row.last_contact_channel}`)
              }) }}
            </UBadge>
            <span v-else-if="row.last_contact_at">
              · {{ t('payments.receivables.lastChased', {
                date: formatDateOnly(row.last_contact_at, locale)
              }) }}
            </span>
          </p>
        </div>

        <span class="receivable-amount">{{ money(row.receivable) }}</span>

        <div class="receivable-actions">
          <UButton
            v-if="row.patient.phone"
            color="neutral"
            variant="ghost"
            icon="i-lucide-phone"
            size="sm"
            :aria-label="t('payments.receivables.call')"
            :title="row.patient.phone"
            @click="call(row)"
          />
          <UButton
            v-if="row.patient.phone"
            color="neutral"
            variant="ghost"
            icon="i-lucide-message-circle"
            size="sm"
            :aria-label="t('payments.receivables.whatsapp')"
            @click="whatsapp(row)"
          />
          <UButton
            v-if="can(PERMISSIONS.payments.recordWrite)"
            color="neutral"
            variant="ghost"
            icon="i-lucide-notebook-pen"
            size="sm"
            :aria-label="t('payments.receivables.logContact')"
            @click="contacting = row"
          />
          <UButton
            v-if="can(PERMISSIONS.payments.recordWrite)"
            color="primary"
            variant="soft"
            size="sm"
            icon="i-lucide-hand-coins"
            @click="collecting = row"
          >
            {{ t('payments.receivables.collect') }}
          </UButton>
        </div>
      </li>
    </ul>

    <PaginationBar
      v-if="totalPages > 1"
      :page="page"
      :total-pages="totalPages"
      :total="total"
      :page-size="pageSize"
      @update:page="changePage"
    />

    <CollectionContactModal
      v-if="contacting"
      :open="true"
      :patient-id="contacting.patient.id"
      :patient-name="patientName(contacting)"
      @update:open="(v) => { if (!v) contacting = null }"
      @saved="onContacted"
    />

    <PaymentCreateModal
      v-if="collecting"
      :open="true"
      :default-patient-id="collecting.patient.id"
      :default-patient-name="patientName(collecting)"
      :suggested-amount="Number(collecting.receivable)"
      @update:open="(v) => { if (!v) collecting = null }"
      @created="onCollected"
    />
  </div>
</template>

<style scoped>
.receivables {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.receivables-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.bucket-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.receivables-state {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.receivables-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 16px;
  text-align: center;
  font-size: 14px;
  color: var(--ui-text-muted);
}

.receivables-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.receivable-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 4px;
  border-top: 1px solid var(--ui-border);
  flex-wrap: wrap;
}

.receivable-name {
  font-weight: 500;
  font-size: 14px;
}

.receivable-name:hover {
  text-decoration: underline;
}

.receivable-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
  font-size: 12px;
  color: var(--ui-text-muted);
}

.receivable-amount {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  white-space: nowrap;
}

.receivable-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
</style>
