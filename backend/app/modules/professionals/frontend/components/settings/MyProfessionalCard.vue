<script setup lang="ts">
/**
 * MyProfessionalCard — the caller's own professional profile, in their
 * account settings.
 *
 * The only place the holder of an individual practice keeps their details
 * (they have no directory screen), and where any clinic professional
 * linked to their account can keep theirs. Name, licence, specialties and
 * contact: what appears on their appointments, treatments, letterheads and
 * letters. Who the profile is — the account link, the type, active or not —
 * stays the clinic's (`PUT /professionals/{id}`).
 *
 * An account that is no professional here sees nothing: `GET /me` answers
 * 404 and the card stays out of the page.
 */
import type { ApiResponse, Professional } from '~~/app/types'

const { t } = useI18n()
const api = useApi()
const toast = useToast()
const specialtiesApi = useSpecialties()

const profile = ref<Professional | null>(null)
const saving = ref(false)
const form = reactive({
  first_name: '',
  last_name: '',
  license_number: '',
  phone: '',
  email: '',
  specialty_ids: [] as string[]
})

const specialtyOptions = computed(() =>
  specialtiesApi.activeSpecialties.value.map(s => ({
    value: s.id,
    label: specialtiesApi.getSpecialtyName(s)
  }))
)

function fill(p: Professional) {
  profile.value = p
  form.first_name = p.first_name
  form.last_name = p.last_name
  form.license_number = p.license_number ?? ''
  form.phone = p.phone ?? ''
  form.email = p.email ?? ''
  form.specialty_ids = (p.specialties ?? []).map(s => s.id)
}

async function load() {
  try {
    fill((await api.get<ApiResponse<Professional>>('/api/v1/professionals/me')).data)
  } catch {
    profile.value = null
  }
}

async function save() {
  saving.value = true
  try {
    const body = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      license_number: form.license_number.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      ...(specialtyOptions.value.length ? { specialty_ids: form.specialty_ids } : {})
    }
    fill((await api.put<ApiResponse<Professional>>('/api/v1/professionals/me', body)).data)
    toast.add({ title: t('professionals.mine.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('professionals.mine.failed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([load(), specialtiesApi.fetchSpecialties()])
})
</script>

<template>
  <SectionCard
    v-if="profile"
    icon="i-lucide-stethoscope"
    :title="t('professionals.mine.title')"
    data-testid="my-professional-card"
  >
    <p class="text-caption text-subtle mb-4">
      {{ t('professionals.mine.description') }}
    </p>
    <form
      class="grid grid-cols-1 gap-4 sm:grid-cols-2"
      @submit.prevent="save"
    >
      <UFormField :label="t('professionals.firstName')">
        <UInput
          v-model="form.first_name"
          class="w-full"
          required
        />
      </UFormField>
      <UFormField :label="t('professionals.lastName')">
        <UInput
          v-model="form.last_name"
          class="w-full"
          required
        />
      </UFormField>
      <UFormField :label="t('professionals.licenseNumber')">
        <UInput
          v-model="form.license_number"
          class="w-full"
        />
      </UFormField>
      <UFormField
        v-if="specialtyOptions.length"
        :label="t('professionals.specialty')"
      >
        <USelect
          v-model="form.specialty_ids"
          :items="specialtyOptions"
          value-key="value"
          multiple
          class="w-full"
        />
      </UFormField>
      <UFormField :label="t('professionals.email')">
        <UInput
          v-model="form.email"
          type="email"
          class="w-full"
        />
      </UFormField>
      <UFormField :label="t('professionals.phone')">
        <UInput
          v-model="form.phone"
          type="tel"
          class="w-full"
        />
      </UFormField>
      <div class="sm:col-span-2 flex justify-end">
        <UButton
          type="submit"
          :loading="saving"
          data-testid="my-professional-save"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </form>
  </SectionCard>
</template>
