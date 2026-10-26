<script setup lang="ts">
import type { Patient, PatientCreate, PaginatedResponse, ApiResponse } from '~~/app/types'
import { PATIENT_STATUS_ROLE, type PatientStatus } from '~~/app/config/severity'

/**
 * /patients — list page.
 *
 * Filter + enrichment design:
 *   - Native filters (status, city, do_not_contact, search, sort) hit
 *     ``GET /api/v1/patients`` directly.
 *   - Row enrichment (debt, on-account credit) is rendered via the
 *     ``patients.list.row.financial`` slot. After each page loads, the
 *     page calls the registered entry's ``loader`` with the page's
 *     patient ids and passes each row its result through ``ctx``.
 *   - The module filter ("Con deuda") uses the ``patients.list.filter``
 *     slot. When it is on, the page calls the entry's ``loader`` for
 *     the ids it selects and intersects them with /patients via
 *     ``?patient_ids=``.
 *
 * This page knows neither who fills those slots nor what they call:
 * the endpoints live in the registering module (today, ``payments``).
 * With nobody registered there is no filter, no badge and no request.
 */

const { t } = useI18n()
const api = useApi()
const toast = useToast()
const router = useRouter()
const route = useRoute()
const { resolve } = useModuleSlots()

// --- Filter shape (URL-synced) ------------------------------------------
interface PatientListFilters {
  q: string
  status: string[]
  city: string
  do_not_contact: boolean | null
  with_debt: boolean
}

const defaults: PatientListFilters = {
  q: '',
  status: ['active'],
  city: '',
  do_not_contact: null,
  with_debt: false
}

// Map of patient_id → whatever the row slot's provider returned for that
// patient; filled after each page load and passed into the slot via ctx.
const debtSummaries = ref<Record<string, unknown>>({})

async function fetcher(q: {
  filters: PatientListFilters
  page: number
  pageSize: number
  sort: string
}) {
  // Step 1: when the module filter is on, ask whoever registered it for
  // the ids it selects. No provider (module off, or no permission) means
  // no filter.
  let patientIdsIntersect: string[] | undefined
  const filterEntry = resolve('patients.list.filter', {}).find(entry => entry.loader)
  if (q.filters.with_debt && filterEntry?.loader) {
    try {
      const res = await filterEntry.loader(api) as { patient_ids?: string[], truncated?: boolean }
      patientIdsIntersect = res.patient_ids ?? []
      if (res.truncated) {
        toast.add({ title: t('lists.truncatedWarning'), color: 'warning' })
      }
      if (!patientIdsIntersect.length) {
        debtSummaries.value = {}
        return { data: [], total: 0 }
      }
    } catch {
      patientIdsIntersect = undefined
    }
  }

  // Step 2: query /patients with the optional intersect + native filters.
  const params = new URLSearchParams()
  params.set('page', String(q.page))
  params.set('page_size', String(q.pageSize))
  if (q.filters.q) params.set('search', q.filters.q)
  if (q.filters.city) params.set('city', q.filters.city)
  if (q.filters.do_not_contact !== null) {
    params.set('do_not_contact', q.filters.do_not_contact ? 'true' : 'false')
  }
  if (q.filters.status.includes('archived')) params.set('include_archived', 'true')
  if (patientIdsIntersect) {
    for (const id of patientIdsIntersect) params.append('patient_ids', id)
  }
  if (q.sort) params.set('sort', q.sort)

  const response = await api.get<PaginatedResponse<Patient>>(`/api/v1/patients?${params.toString()}`)

  // Step 3: one bulk request for the page's rows, made by the row
  // slot's provider. The slot renders nothing for ids missing from the map.
  const rowEntry = resolve('patients.list.row.financial', {}).find(entry => entry.loader)
  if (rowEntry?.loader && response.data.length) {
    try {
      debtSummaries.value = await rowEntry.loader(
        api,
        response.data.map(x => x.id)
      ) as Record<string, unknown>
    } catch {
      debtSummaries.value = {}
    }
  } else {
    debtSummaries.value = {}
  }

  return { data: response.data, total: response.total }
}

const {
  filters,
  page,
  pageSize,
  sort,
  rows: patients,
  total,
  totalPages,
  isLoading,
  error,
  setFilter,
  resetFilters,
  refresh
} = useListQuery<PatientListFilters, Patient>({
  defaults,
  pageSize: 20,
  sortable: ['last_visit', 'last_name', 'first_name', 'created_at', 'updated_at'],
  defaultSort: 'last_visit:desc',
  searchKey: 'q',
  fetcher
})

const statusItems = computed(() => [
  { label: t('patients.status.active'), value: 'active' },
  { label: t('patients.status.archived'), value: 'archived' }
])

const sortOptions = computed(() => [
  { field: 'last_visit', label: t('patients.sort.lastVisit'), defaultDir: 'desc' as const },
  { field: 'last_name', label: t('patients.sort.lastName'), defaultDir: 'asc' as const },
  { field: 'first_name', label: t('patients.sort.firstName'), defaultDir: 'asc' as const },
  { field: 'created_at', label: t('patients.sort.createdAt'), defaultDir: 'desc' as const },
  { field: 'updated_at', label: t('patients.sort.updatedAt'), defaultDir: 'desc' as const }
])

const activeFilterCount = computed(() => {
  let n = 0
  if (filters.value.status.length && filters.value.status.join(',') !== 'active') n++
  if (filters.value.city) n++
  if (filters.value.do_not_contact !== null) n++
  if (filters.value.with_debt) n++
  return n
})

function debtFilterCtx() {
  return {
    value: filters.value.with_debt,
    onChange: (v: boolean | null) => setFilter('with_debt', Boolean(v))
  }
}

// --- Create modal (preserved) -------------------------------------------
const isCreateModalOpen = ref(false)
const isSubmitting = ref(false)
const newPatient = reactive<PatientCreate>({
  first_name: '',
  last_name: '',
  phone: '',
  email: '',
  date_of_birth: '',
  notes: ''
})

onMounted(() => {
  if (route.query.new === '1') {
    isCreateModalOpen.value = true
    router.replace({ query: { ...route.query, new: undefined } })
  }
})

// Same rules as ``PatientCreate`` in the backend. Optional fields are
// only validated when filled in.
const NAME_RE = /^[\p{L} '.-]+$/u
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PHONE_SEPARATORS_RE = /[\s\-().]/g
const PHONE_DIGITS_RE = /^\+?\d{7,15}$/
const MAX_PATIENT_AGE_YEARS = 130
const NOTES_MAX_LENGTH = 5000

type PatientFormField = 'first_name' | 'last_name' | 'phone' | 'email' | 'date_of_birth' | 'notes'
const formErrors = reactive<Record<PatientFormField, string>>({
  first_name: '',
  last_name: '',
  phone: '',
  email: '',
  date_of_birth: '',
  notes: ''
})

function validateName(value: string): string {
  const name = value.trim()
  if (!name) return t('patients.validation.required')
  if (name.length > 100) return t('patients.validation.tooLong', { max: 100 })
  if (!NAME_RE.test(name)) return t('patients.validation.nameInvalid')
  return ''
}

function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function validateForm(): boolean {
  formErrors.first_name = validateName(newPatient.first_name)
  formErrors.last_name = validateName(newPatient.last_name)

  const phone = (newPatient.phone || '').trim()
  formErrors.phone = phone && (phone.length > 20 || !PHONE_DIGITS_RE.test(phone.replace(PHONE_SEPARATORS_RE, '')))
    ? t('patients.validation.phoneInvalid')
    : ''

  const email = (newPatient.email || '').trim()
  formErrors.email = email && !EMAIL_RE.test(email) ? t('patients.validation.emailInvalid') : ''

  const dob = newPatient.date_of_birth || ''
  const today = new Date()
  formErrors.date_of_birth = ''
  if (dob > toIsoDate(today)) {
    formErrors.date_of_birth = t('patients.validation.dateOfBirthFuture')
  } else if (dob && Number(dob.slice(0, 4)) < today.getFullYear() - MAX_PATIENT_AGE_YEARS) {
    formErrors.date_of_birth = t('patients.validation.dateOfBirthTooOld', { years: MAX_PATIENT_AGE_YEARS })
  }

  formErrors.notes = (newPatient.notes || '').length > NOTES_MAX_LENGTH
    ? t('patients.validation.tooLong', { max: NOTES_MAX_LENGTH })
    : ''

  return Object.values(formErrors).every(error => !error)
}

function resetForm() {
  Object.keys(formErrors).forEach((key) => {
    formErrors[key as PatientFormField] = ''
  })
  Object.assign(newPatient, {
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
    date_of_birth: '',
    notes: ''
  })
}

async function createPatient() {
  if (!validateForm()) return
  isSubmitting.value = true
  try {
    const response = await api.post<ApiResponse<Patient>>('/api/v1/patients', {
      first_name: newPatient.first_name.trim(),
      last_name: newPatient.last_name.trim(),
      phone: newPatient.phone?.trim() || null,
      email: newPatient.email?.trim() || null,
      date_of_birth: newPatient.date_of_birth || null,
      notes: newPatient.notes || null
    })
    toast.add({
      title: t('common.success'),
      description: t('patients.created'),
      color: 'success'
    })
    isCreateModalOpen.value = false
    resetForm()
    await refresh()
    await router.push(`/patients/${response.data.id}`)
  } catch (e: unknown) {
    const fetchError = e as { statusCode?: number, data?: { message?: string } }
    toast.add({
      title: t('common.error'),
      description: fetchError.data?.message || t('common.serverError'),
      color: 'error'
    })
  } finally {
    isSubmitting.value = false
  }
}

function patientCity(p: Patient): string {
  const addr = (p as Patient & { address?: { city?: string } }).address
  return addr?.city || ''
}
</script>

<template>
  <DataListLayout
    :title="t('patients.title')"
    :loading="isLoading"
    :empty="!patients.length"
    :error="error"
    :page="page"
    :page-size="pageSize"
    :total="total"
    :total-pages="totalPages"
    @update:page="(v) => (page = v)"
  >
    <template #actions>
      <UButton
        color="primary"
        variant="soft"
        icon="i-lucide-plus"
        @click="isCreateModalOpen = true"
      >
        {{ t('patients.create') }}
      </UButton>
    </template>

    <template #toolbar>
      <FilterBar
        :active-count="activeFilterCount"
        @reset="resetFilters"
      >
        <template #search>
          <SearchBar
            :model-value="filters.q"
            :placeholder="t('patients.searchPlaceholder')"
            max-width="max-w-md"
            @update:model-value="(v) => setFilter('q', v)"
          />
        </template>

        <FilterChipMulti
          :model-value="filters.status"
          :items="statusItems"
          :label="t('patients.filters.status')"
          icon="i-lucide-circle-dot"
          @update:model-value="(v) => setFilter('status', v)"
        />

        <FilterToggle
          :model-value="filters.do_not_contact"
          :label="t('patients.filters.doNotContactOnly')"
          :label-false="t('patients.filters.doNotContactOnlyContactable')"
          icon="i-lucide-bell-off"
          tristate
          @update:model-value="(v) => setFilter('do_not_contact', v)"
        />

        <ModuleSlot
          name="patients.list.filter"
          :ctx="debtFilterCtx()"
        />

        <template #right>
          <SortMenu
            :model-value="sort"
            :options="sortOptions"
            @update:model-value="(v) => (sort = v)"
          />
        </template>
      </FilterBar>
    </template>

    <template #empty>
      <EmptyState
        icon="i-lucide-users"
        :title="activeFilterCount || filters.q ? t('patients.noResults') : t('patients.empty')"
        :description="activeFilterCount || filters.q ? undefined : t('dashboard.welcomeMessage')"
      >
        <template
          v-if="!activeFilterCount && !filters.q"
          #actions
        >
          <UButton
            color="primary"
            variant="soft"
            icon="i-lucide-plus"
            @click="isCreateModalOpen = true"
          >
            {{ t('patients.emptyAction') }}
          </UButton>
        </template>
      </EmptyState>
    </template>

    <template #rows>
      <DataListItem
        v-for="patient in patients"
        :key="patient.id"
        :to="`/patients/${patient.id}`"
      >
        <template #row>
          <UAvatar
            :alt="patient.first_name"
            size="sm"
          />
          <div class="flex-1 min-w-0">
            <div class="text-ui text-default truncate flex items-center gap-2">
              {{ patient.last_name }}, {{ patient.first_name }}
              <UIcon
                v-if="patient.do_not_contact"
                name="i-lucide-bell-off"
                class="w-3.5 h-3.5 text-warning shrink-0"
                :title="t('patients.doNotContact.label')"
              />
            </div>
            <div class="text-caption text-subtle truncate">
              <span v-if="patientCity(patient)">{{ patientCity(patient) }} · </span>{{ patient.phone || patient.email || '—' }}
            </div>
          </div>
          <div class="shrink-0 flex items-center gap-3 ml-auto">
            <ModuleSlot
              name="patients.list.row.financial"
              :ctx="{ patient_id: patient.id, summary: debtSummaries[patient.id] ?? null }"
            />
            <StatusBadge
              :role="PATIENT_STATUS_ROLE[patient.status as PatientStatus] || 'neutral'"
              :label="t(`patients.status.${patient.status}`)"
            />
            <UIcon
              name="i-lucide-chevron-right"
              class="text-subtle"
            />
          </div>
        </template>

        <template #card>
          <div class="flex items-center gap-3">
            <UAvatar
              :alt="patient.first_name"
              size="md"
            />
            <div class="flex-1 min-w-0">
              <div class="font-medium text-default truncate flex items-center gap-2">
                {{ patient.last_name }}, {{ patient.first_name }}
                <UIcon
                  v-if="patient.do_not_contact"
                  name="i-lucide-bell-off"
                  class="w-3.5 h-3.5 text-warning shrink-0"
                />
              </div>
              <div class="text-caption text-subtle truncate">
                {{ patient.phone || patient.email || '—' }}
              </div>
            </div>
            <StatusBadge
              :role="PATIENT_STATUS_ROLE[patient.status as PatientStatus] || 'neutral'"
              :label="t(`patients.status.${patient.status}`)"
              class="shrink-0"
            />
          </div>
          <div class="flex items-center justify-between gap-2">
            <span class="text-caption text-subtle truncate">
              {{ patientCity(patient) || '—' }}
            </span>
            <ModuleSlot
              name="patients.list.row.financial"
              :ctx="{ patient_id: patient.id, summary: debtSummaries[patient.id] ?? null }"
            />
          </div>
        </template>
      </DataListItem>
    </template>
  </DataListLayout>

  <UModal v-model:open="isCreateModalOpen">
    <template #content>
      <UCard>
        <template #header>
          <div class="flex items-center justify-between">
            <h2 class="text-h1 text-default">
              {{ t('patients.create') }}
            </h2>
            <UButton
              variant="ghost"
              color="neutral"
              icon="i-lucide-x"
              :aria-label="t('common.close', 'Cerrar')"
              @click="isCreateModalOpen = false"
            />
          </div>
        </template>

        <form
          class="space-y-4"
          @submit.prevent="createPatient"
        >
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField
              :label="t('patients.firstName')"
              :error="formErrors.first_name || undefined"
              required
            >
              <UInput
                v-model="newPatient.first_name"
                :placeholder="t('patients.firstName')"
                required
              />
            </UFormField>
            <UFormField
              :label="t('patients.lastName')"
              :error="formErrors.last_name || undefined"
              required
            >
              <UInput
                v-model="newPatient.last_name"
                :placeholder="t('patients.lastName')"
                required
              />
            </UFormField>
          </div>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField
              :label="t('patients.phone')"
              :error="formErrors.phone || undefined"
            >
              <UInput
                v-model="newPatient.phone"
                :placeholder="t('patients.phone')"
                type="tel"
              />
            </UFormField>
            <UFormField
              :label="t('patients.email')"
              :error="formErrors.email || undefined"
            >
              <UInput
                v-model="newPatient.email"
                :placeholder="t('patients.email')"
                type="email"
              />
            </UFormField>
          </div>

          <UFormField
            :label="t('patients.dateOfBirth')"
            :error="formErrors.date_of_birth || undefined"
          >
            <UInput
              v-model="newPatient.date_of_birth"
              type="date"
            />
          </UFormField>

          <UFormField
            :label="t('patients.notes')"
            :error="formErrors.notes || undefined"
          >
            <UTextarea
              v-model="newPatient.notes"
              :placeholder="t('patients.notes')"
              :rows="3"
            />
          </UFormField>
        </form>

        <template #footer>
          <div class="flex justify-end gap-3">
            <UButton
              variant="outline"
              color="neutral"
              @click="isCreateModalOpen = false"
            >
              {{ t('common.cancel') }}
            </UButton>
            <UButton
              color="primary"
              variant="solid"
              :loading="isSubmitting"
              :disabled="!newPatient.first_name || !newPatient.last_name"
              @click="createPatient"
            >
              {{ t('common.save') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
