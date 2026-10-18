<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import type { ApiResponse, PaginatedResponse, Professional } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'

// The form offers exactly what the directory can hold, so this follows the
// shared type rather than restating it: a local copy is what let the page
// drift out of step with the backend's three values in the first place.
type ProfessionalType = Professional['professional_type']

interface ProfessionalForm {
  first_name: string
  last_name: string
  professional_type: ProfessionalType
  specialty_ids: string[]
  license_number: string
  email: string
  phone: string
  photo_url: string
  notes: string
  is_active: boolean
  /** Empty string = no account linked; the payload sends null. */
  user_id: string
}

definePageMeta({ middleware: ['auth'] })

const { t, locale } = useI18n()
const api = useApi()
const toast = useToast()
const { can } = usePermissions()

if (!can(PERMISSIONS.professionals.read)) {
  await navigateTo('/')
}

// The directory is a clinic's screen. One professional's practice has a
// single profile, its holder's, kept from Settings → My professional
// details; its sidebar has no entry here, and a typed URL goes home.
const { isIndividualPractice } = useClinic()
watchEffect(() => {
  if (isIndividualPractice.value) void navigateTo('/', { replace: true })
})

const { byId: workloadById, load: loadWorkload } = useProfessionalWorkload()

const professionals = ref<Professional[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const isLoading = ref(false)
const error = ref<string | null>(null)
const search = ref('')
const typeFilter = ref<'all' | ProfessionalType>('all')
const showInactive = ref(false)
const isModalOpen = ref(false)
const isSaving = ref(false)
const isUploadingPhoto = ref(false)
const editingId = ref<string | null>(null)
const editingHasSystemAccess = ref(false)

/**
 * Accounts an admin can link a professional to.
 *
 * Only those with a role in this clinic: the API refuses any other, because a
 * clinic naming an outsider as the author of its clinical records is not a
 * thing to allow. An account is offered once — linking two professionals to
 * the same one would make "who is responsible for this entry" unanswerable.
 *
 * Listing accounts needs `admin.users.write`, a different grant from the one
 * that opens this page. If it is refused the field simply does not appear,
 * rather than the form breaking around it.
 */
interface ClinicAccount { id: string, email: string, first_name: string, last_name: string, role: string | null }
const accounts = ref<ClinicAccount[]>([])
const canLinkAccounts = ref(true)

async function loadAccounts() {
  try {
    const response = await api.get<PaginatedResponse<ClinicAccount>>('/api/v1/auth/users')
    accounts.value = response.data.filter(u => u.role)
  } catch {
    canLinkAccounts.value = false
    accounts.value = []
  }
}

const takenUserIds = computed(
  () => new Set(
    professionals.value.filter(p => p.user_id && p.id !== editingId.value).map(p => p.user_id)
  )
)

const accountOptions = computed(() => [
  { value: '', label: t('professionals.account.none') },
  ...accounts.value
    .filter(u => !takenUserIds.value.has(u.id))
    .map(u => ({ value: u.id, label: `${u.first_name} ${u.last_name} · ${u.email}` }))
])
const photoFileInputRef = ref<HTMLInputElement | null>(null)
// The /photo endpoint requires Bearer auth and returns a relative path —
// a plain <img src> can't load it (no auth header, wrong origin). We
// fetch it as a blob ourselves and hand the <img> an object URL instead.
const modalPhotoSrc = ref<string | undefined>(undefined)

// Portraits for the list and the profile card, keyed by professional id.
// The /photo endpoint is Bearer-protected, so every one of these is a
// blob fetch — an <img> cannot authenticate itself. One cache serves
// both surfaces; revoked wholesale when the page's results change.
const photoSrcById = ref<Record<string, string>>({})

// Profile card state. Reading a professional is the common intent, so
// this is what a row opens; editing is a button inside it.
const profileOpen = ref(false)
const profileProfessional = ref<Professional | null>(null)

const form = reactive<ProfessionalForm>({
  first_name: '',
  last_name: '',
  professional_type: 'dentist',
  specialty_ids: [],
  license_number: '',
  email: '',
  phone: '',
  photo_url: '',
  notes: '',
  is_active: true,
  user_id: ''
})

// Clinical types first, then the non-clinical one — the order the backend's
// `ProfessionalType` literal uses. These feed both the create/edit select and
// the list filter.
const typeOptions = computed(() => [
  { label: t('professionals.types.dentist'), value: 'dentist' },
  { label: t('professionals.types.hygienist'), value: 'hygienist' },
  { label: t('professionals.types.collaborator'), value: 'collaborator' }
])

// Specialties come from the clinic's own catalog (`catalog` module) rather
// than a list hardcoded here: the same discipline names classify treatments,
// and two hand-typed copies drift apart on the first stray accent.
const specialtiesApi = useSpecialties()

const specialtyOptions = computed(() =>
  specialtiesApi.activeSpecialties.value.map(s => ({
    value: s.id,
    label: specialtiesApi.getSpecialtyName(s)
  }))
)

// A professional may practise several disciplines; the list view has room
// for one line, so join them.
function specialtyLabel(professional: Professional): string {
  return (professional.specialties ?? [])
    .map(s => s.names[locale.value] || s.names.es || s.names.en || '')
    .filter(Boolean)
    .join(', ')
}

// Only clinical staff practise a discipline. Collaborators (labs, suppliers,
// assistants) are roles, not specialties — offering them the catalog would
// put entries with zero treatments into the treatment classification.
const CLINICAL_TYPES = ['dentist', 'hygienist']
const hasSpecialty = computed(() => CLINICAL_TYPES.includes(form.professional_type))

// Fires only on genuine interaction with the type select (not on openEdit's
// Object.assign), so an existing link survives being reopened.
function handleTypeChange() {
  if (!hasSpecialty.value) form.specialty_ids = []
}

const filterOptions = computed(() => [
  { label: t('professionals.filters.allTypes'), value: 'all' },
  ...typeOptions.value
])

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const modalTitle = computed(() => t(editingId.value ? 'professionals.edit' : 'professionals.create'))

function resetForm() {
  Object.assign(form, {
    first_name: '',
    last_name: '',
    professional_type: 'dentist',
    specialty_ids: [],
    license_number: '',
    email: '',
    phone: '',
    photo_url: '',
    notes: '',
    is_active: true,
    user_id: ''
  })
  editingId.value = null
  editingHasSystemAccess.value = false
  if (modalPhotoSrc.value) {
    URL.revokeObjectURL(modalPhotoSrc.value)
    modalPhotoSrc.value = undefined
  }
}

function nullable(value: string): string | null {
  return value.trim() || null
}

function formPayload() {
  return {
    first_name: form.first_name.trim(),
    last_name: form.last_name.trim(),
    professional_type: form.professional_type,
    specialty_ids: form.specialty_ids,
    license_number: nullable(form.license_number),
    email: nullable(form.email),
    phone: nullable(form.phone),
    photo_url: nullable(form.photo_url),
    notes: nullable(form.notes),
    is_active: form.is_active,
    user_id: form.user_id || null
  }
}

async function load() {
  isLoading.value = true
  error.value = null
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      page_size: String(pageSize)
    })
    if (search.value.trim()) params.set('search', search.value.trim())
    if (typeFilter.value !== 'all') params.set('professional_type', typeFilter.value)
    if (showInactive.value) params.set('include_inactive', 'true')
    const response = await api.get<PaginatedResponse<Professional>>(
      `/api/v1/professionals?${params.toString()}`
    )
    professionals.value = response.data
    total.value = response.total
    void loadListPhotos()
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('professionals.errors.load')
  } finally {
    isLoading.value = false
  }
}

/**
 * Fetch the portraits for the page just loaded.
 *
 * Deliberately not awaited by `load()`: the directory is useful the
 * moment the names arrive, and a portrait appearing a beat later is a
 * better trade than a list that waits on twenty image requests. Failures
 * are silent by design — a missing portrait falls back to initials,
 * which is not worth a toast.
 */
async function loadListPhotos() {
  for (const url of Object.values(photoSrcById.value)) URL.revokeObjectURL(url)
  photoSrcById.value = {}

  const withPhoto = professionals.value.filter(pro => pro.photo_url)
  const loaded = await Promise.all(
    withPhoto.map(async (pro) => {
      try {
        return [pro.id, await resolvePhotoBlobUrl(pro.photo_url as string)] as const
      } catch {
        return null
      }
    })
  )
  photoSrcById.value = Object.fromEntries(loaded.filter(Boolean) as (readonly [string, string])[])
}

onBeforeUnmount(() => {
  for (const url of Object.values(photoSrcById.value)) URL.revokeObjectURL(url)
})

function openProfile(professional: Professional) {
  profileProfessional.value = professional
  profileOpen.value = true
}

/** From the profile card into the edit form, without a second click. */
function editFromProfile(professional: Professional) {
  profileOpen.value = false
  openEdit(professional)
}

function openCreate() {
  resetForm()
  isModalOpen.value = true
}

function openEdit(professional: Professional) {
  editingId.value = professional.id
  editingHasSystemAccess.value = professional.has_system_access
  Object.assign(form, {
    first_name: professional.first_name,
    last_name: professional.last_name,
    professional_type: professional.professional_type,
    specialty_ids: (professional.specialties ?? []).map(s => s.id),
    license_number: professional.license_number ?? '',
    email: professional.email ?? '',
    phone: professional.phone ?? '',
    photo_url: professional.photo_url ?? '',
    notes: professional.notes ?? '',
    is_active: professional.is_active,
    user_id: professional.user_id ?? ''
  })
  isModalOpen.value = true
  refreshModalPhotoSrc()
}

async function save() {
  if (!form.first_name.trim() || !form.last_name.trim()) return
  isSaving.value = true
  try {
    if (editingId.value) {
      await api.put<ApiResponse<Professional>>(
        `/api/v1/professionals/${editingId.value}`,
        formPayload()
      )
    } else {
      await api.post<ApiResponse<Professional>>('/api/v1/professionals', formPayload())
    }
    toast.add({ title: t('common.success'), description: t('professionals.saved'), color: 'success' })
    isModalOpen.value = false
    await load()
  } catch (err) {
    const message = (err as { data?: { message?: string, detail?: string } })?.data
    toast.add({
      title: t('common.error'),
      description: message?.message || message?.detail || t('professionals.errors.save'),
      color: 'error'
    })
  } finally {
    isSaving.value = false
  }
}

// Takes the directory's full set, not the form's: this labels rows that
// come back from the API, and a hygienist created elsewhere is one of
// them. Both locales already carry `professionals.types.hygienist`.
function labelForType(type: Professional['professional_type']) {
  return t(`professionals.types.${type}`)
}

// Photos are fetched as blobs because <img> cannot attach the app's
// same-origin session credentials to a protected media endpoint.
async function resolvePhotoBlobUrl(relativeUrl: string): Promise<string> {
  const blob = await api.$api<Blob>(relativeUrl, { responseType: 'blob' })
  return URL.createObjectURL(blob)
}

async function refreshModalPhotoSrc() {
  if (modalPhotoSrc.value) {
    URL.revokeObjectURL(modalPhotoSrc.value)
    modalPhotoSrc.value = undefined
  }
  if (!form.photo_url) return
  try {
    modalPhotoSrc.value = await resolvePhotoBlobUrl(form.photo_url)
  } catch {
    modalPhotoSrc.value = undefined
  }
}

async function uploadPhoto(file: File) {
  if (!editingId.value) return
  isUploadingPhoto.value = true
  try {
    const body = new FormData()
    body.append('file', file)
    const response = await api.post<ApiResponse<Professional>>(
      `/api/v1/professionals/${editingId.value}/photo`, body
    )
    form.photo_url = response.data.photo_url ?? ''
    await refreshModalPhotoSrc()
    toast.add({ title: t('common.success'), description: t('professionals.photoUploaded'), color: 'success' })
    await load()
  } catch {
    toast.add({ title: t('common.error'), description: t('professionals.errors.photoUpload'), color: 'error' })
  } finally {
    isUploadingPhoto.value = false
  }
}

function onPhotoFileSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (file) uploadPhoto(file)
}

watch([typeFilter, showInactive], () => {
  page.value = 1
  load()
})

watch(page, load)
onMounted(async () => {
  await Promise.all([load(), specialtiesApi.fetchSpecialties(), loadAccounts(), loadWorkload()])
})
</script>

<template>
  <DataListLayout
    :title="t('professionals.title')"
    :subtitle="t('professionals.description')"
    :loading="isLoading"
    :empty="!professionals.length"
    :error="error"
    :page="page"
    :page-size="pageSize"
    :total="total"
    :total-pages="totalPages"
    @update:page="(value) => (page = value)"
  >
    <template #actions>
      <UButton
        v-if="can(PERMISSIONS.professionals.write)"
        color="primary"
        variant="soft"
        icon="i-lucide-plus"
        @click="openCreate"
      >
        {{ t('professionals.create') }}
      </UButton>
    </template>

    <template #toolbar>
      <FilterBar
        :active-count="Number(typeFilter !== 'all') + Number(showInactive)"
        @reset="() => { typeFilter = 'all'; showInactive = false; search = ''; load() }"
      >
        <template #search>
          <UInput
            v-model="search"
            icon="i-lucide-search"
            :placeholder="t('professionals.searchPlaceholder')"
            @keyup.enter="() => { page = 1; load() }"
          />
        </template>

        <USelect
          v-model="typeFilter"
          :items="filterOptions"
          value-key="value"
          label-key="label"
          class="w-48"
        />
        <UCheckbox
          v-model="showInactive"
          :label="t('professionals.filters.showInactive')"
        />
      </FilterBar>
    </template>

    <template #empty>
      <EmptyState
        icon="i-lucide-stethoscope"
        :title="search || typeFilter !== 'all' || showInactive ? t('professionals.noResults') : t('professionals.empty')"
        :description="search || typeFilter !== 'all' || showInactive ? undefined : t('professionals.emptyDescription')"
      >
        <template
          v-if="can(PERMISSIONS.professionals.write) && !search && typeFilter === 'all' && !showInactive"
          #actions
        >
          <UButton
            color="primary"
            variant="soft"
            icon="i-lucide-plus"
            @click="openCreate"
          >
            {{ t('professionals.create') }}
          </UButton>
        </template>
      </EmptyState>
    </template>

    <template #rows>
      <DataListItem
        v-for="professional in professionals"
        :key="professional.id"
      >
        <!-- The whole row is one button: opening the profile is what a
             click here means, and a real <button> gets keyboard focus and
             the 44 px touch minimum for free. It replaces a pencil that
             offered the rarer intent — editing — as the only thing a row
             could do. -->
        <template #row>
          <button
            type="button"
            class="flex flex-1 items-center gap-[var(--density-gap,0.75rem)] min-w-0 text-left"
            @click="openProfile(professional)"
          >
            <UAvatar
              :src="photoSrcById[professional.id]"
              :alt="professional.full_name"
              size="md"
            />
            <div class="flex-1 min-w-0">
              <p class="text-ui text-default truncate">
                {{ professional.full_name }}
              </p>
              <p class="text-caption text-subtle truncate">
                {{ specialtyLabel(professional) || labelForType(professional.professional_type) }}
                <span v-if="professional.license_number"> · {{ t('professionals.licenseShort') }} {{ professional.license_number }}</span>
              </p>
              <p
                v-if="workloadById[professional.id]"
                class="text-caption text-subtle truncate"
                data-testid="professional-workload-row"
              >
                {{ t('professionals.workload.rowPatients', { n: workloadById[professional.id]!.patients }) }}
                <template v-if="workloadById[professional.id]!.counts.appointments_upcoming !== undefined">
                  · {{ t('professionals.workload.rowAppointments', { n: workloadById[professional.id]!.counts.appointments_upcoming }) }}
                </template>
                <template v-if="workloadById[professional.id]!.counts.treatments_pending !== undefined">
                  · {{ t('professionals.workload.rowTreatments', { n: workloadById[professional.id]!.counts.treatments_pending }) }}
                </template>
              </p>
            </div>
            <span class="hidden lg:block text-caption text-subtle truncate max-w-52">
              {{ professional.email || professional.phone || '—' }}
            </span>
            <UBadge
              :color="professional.is_active ? 'success' : 'neutral'"
              variant="subtle"
            >
              {{ t(professional.is_active ? 'professionals.status.active' : 'professionals.status.inactive') }}
            </UBadge>
            <UIcon
              name="i-lucide-chevron-right"
              class="h-4 w-4 shrink-0 text-subtle"
            />
          </button>
        </template>

        <template #card>
          <button
            type="button"
            class="flex w-full items-center gap-3 text-left"
            @click="openProfile(professional)"
          >
            <UAvatar
              :src="photoSrcById[professional.id]"
              :alt="professional.full_name"
              size="lg"
            />
            <div class="flex-1 min-w-0">
              <p class="font-medium text-default truncate">
                {{ professional.full_name }}
              </p>
              <p class="text-caption text-subtle truncate">
                {{ specialtyLabel(professional) || labelForType(professional.professional_type) }}
              </p>
            </div>
            <UBadge
              :color="professional.is_active ? 'success' : 'neutral'"
              variant="subtle"
            >
              {{ t(professional.is_active ? 'professionals.status.active' : 'professionals.status.inactive') }}
            </UBadge>
          </button>
          <p class="text-caption text-subtle truncate">
            {{ professional.email || professional.phone || '—' }}
          </p>
        </template>
      </DataListItem>
    </template>
  </DataListLayout>

  <UModal v-model:open="isModalOpen">
    <template #content>
      <UCard>
        <template #header>
          <div class="flex items-center justify-between gap-3">
            <h2 class="text-h1 text-default">
              {{ modalTitle }}
            </h2>
            <UButton
              variant="ghost"
              color="neutral"
              icon="i-lucide-x"
              :aria-label="t('common.close')"
              @click="isModalOpen = false"
            />
          </div>
        </template>

        <form
          class="space-y-4"
          @submit.prevent="save"
        >
          <div class="flex items-center gap-4">
            <div class="relative shrink-0">
              <UAvatar
                :src="modalPhotoSrc"
                :alt="`${form.first_name} ${form.last_name}`"
                size="xl"
              />
              <UButton
                v-if="editingId"
                type="button"
                icon="i-lucide-camera"
                color="primary"
                variant="solid"
                size="xs"
                class="absolute -bottom-1 -right-1 rounded-full"
                :loading="isUploadingPhoto"
                :aria-label="t('professionals.uploadPhotoAction')"
                @click="photoFileInputRef?.click()"
              />
              <input
                ref="photoFileInputRef"
                type="file"
                accept="image/*"
                class="hidden"
                @change="onPhotoFileSelected"
              >
            </div>
            <p
              v-if="!editingId"
              class="text-caption text-subtle"
            >
              {{ t('professionals.photoAfterSave') }}
            </p>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField
              :label="t('professionals.firstName')"
              required
            >
              <UInput
                v-model="form.first_name"
                required
              />
            </UFormField>
            <UFormField
              :label="t('professionals.lastName')"
              required
            >
              <UInput
                v-model="form.last_name"
                required
              />
            </UFormField>
          </div>
          <UFormField
            :label="t('professionals.type')"
            required
          >
            <USelect
              v-model="form.professional_type"
              :items="typeOptions"
              value-key="value"
              label-key="label"
              class="w-full"
              @update:model-value="handleTypeChange"
            />
          </UFormField>
          <UFormField
            v-if="hasSpecialty"
            :label="t('professionals.specialty')"
          >
            <USelectMenu
              v-model="form.specialty_ids"
              :aria-label="t('professionals.specialty')"
              :items="specialtyOptions"
              value-key="value"
              label-key="label"
              multiple
              :placeholder="t('professionals.specialtyPlaceholder')"
              class="w-full"
            />
          </UFormField>
          <UFormField :label="t('professionals.licenseNumber')">
            <UInput v-model="form.license_number" />
          </UFormField>

          <!-- What ties a clinical entry to a person with a licence. Stated
               here rather than guessed from a matching email: the record has
               to name who is responsible, and a coincidence would name the
               wrong one. -->
          <UFormField
            v-if="canLinkAccounts"
            :label="t('professionals.account.label')"
            :help="t('professionals.account.help')"
          >
            <USelect
              v-model="form.user_id"
              :items="accountOptions"
              value-key="value"
              label-key="label"
              class="w-full"
            />
          </UFormField>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <UFormField :label="t('professionals.email')">
              <UInput
                v-model="form.email"
                type="email"
              />
            </UFormField>
            <UFormField :label="t('professionals.phone')">
              <UInput
                v-model="form.phone"
                type="tel"
              />
            </UFormField>
          </div>
          <UFormField :label="t('professionals.notes')">
            <UTextarea
              v-model="form.notes"
              :rows="3"
            />
          </UFormField>
          <div class="flex items-center gap-4">
            <UCheckbox
              v-model="form.is_active"
              :label="t('professionals.status.active')"
            />
            <span
              v-if="editingHasSystemAccess"
              class="flex items-center gap-1 text-caption text-success-accent"
            >
              <UIcon
                name="i-lucide-check-circle-2"
                class="size-4"
              />
              {{ t('professionals.status.hasSystemAccess') }}
            </span>
          </div>
        </form>

        <template #footer>
          <div class="flex justify-end gap-3">
            <UButton
              variant="outline"
              color="neutral"
              @click="isModalOpen = false"
            >
              {{ t('common.cancel') }}
            </UButton>
            <UButton
              color="primary"
              :loading="isSaving"
              :disabled="!form.first_name.trim() || !form.last_name.trim()"
              @click="save"
            >
              {{ t('common.save') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>

  <ProfessionalProfileModal
    v-model:open="profileOpen"
    :professional="profileProfessional"
    :photo-src="profileProfessional ? photoSrcById[profileProfessional.id] : undefined"
    :can-edit="can(PERMISSIONS.professionals.write)"
    :workload="profileProfessional ? workloadById[profileProfessional.id] : undefined"
    @edit="editFromProfile"
  />
</template>
