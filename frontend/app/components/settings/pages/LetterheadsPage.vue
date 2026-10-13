<script setup lang="ts">
/**
 * The clinic's letterheads (Settings → General → Membretes): the clinic's
 * own, and one per professional (ADR 0046).
 *
 * A letterhead heads every printed document, whichever App prints it —
 * consent letters, the clinical record, the blank health questionnaire —
 * so it is set up here, in the Workspace, and stays reachable whatever
 * optional App is switched off.
 */
import { PERMISSIONS } from '~/config/permissions'
import type { PaginatedResponse } from '~/types'
import type { Letterhead } from '~/composables/useLetterhead'

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const { isActive } = useModules()
const letterheadApi = useLetterhead()
const api = useApi()

const canEdit = computed(() => can(PERMISSIONS.admin.clinicWrite))

interface Doctor { id: string, name: string, license: string | null }

const letterheads = ref<Letterhead[]>([])
const doctors = ref<Doctor[]>([])
/** Professionals given a card in this visit, before their first save. */
const drafted = ref<string[]>([])
const adding = ref<string | undefined>(undefined)
const loaded = ref(false)

async function load() {
  try {
    letterheads.value = await letterheadApi.list()
    // Whoever has one saved no longer needs a draft card.
    const saved = new Set(letterheads.value.map(item => item.professional_id))
    drafted.value = drafted.value.filter(id => !saved.has(id))
    // The directory is the Professionals App's: with it off there is nobody
    // to offer, and the clinic's own letterhead is all there is.
    if (isActive('professionals') && doctors.value.length === 0) {
      try {
        const response = await api.get<PaginatedResponse<{
          id: string
          first_name: string
          last_name: string
          license_number?: string | null
        }>>('/api/v1/professionals?page_size=100')
        doctors.value = response.data.map(pro => ({
          id: pro.id,
          name: `${pro.first_name} ${pro.last_name}`.trim(),
          license: pro.license_number ?? null
        }))
      } catch {
        doctors.value = []
      }
    }
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loaded.value = true
  }
}

onMounted(load)

const clinicLetterhead = computed(() => letterheads.value.find(item => item.professional_id === null) ?? null)

/** One card per professional with a letterhead, saved or being drafted. */
const doctorCards = computed(() => {
  const saved = letterheads.value.filter(item => item.professional_id !== null)
  const ids = [...saved.map(item => item.professional_id!), ...drafted.value]
  return ids.map((id) => {
    const doctor = doctors.value.find(d => d.id === id)
    return {
      id,
      name: doctor?.name ?? t('letterhead.unknownProfessional'),
      suggested: doctor
        ? [doctor.name, doctor.license && t('letterhead.license', { number: doctor.license })].filter(Boolean).join(' · ')
        : '',
      letterhead: saved.find(item => item.professional_id === id) ?? null
    }
  })
})

const addable = computed(() => {
  const taken = new Set(doctorCards.value.map(card => card.id))
  return doctors.value.filter(d => !taken.has(d.id)).map(d => ({ label: d.name, value: d.id }))
})

function addDoctor() {
  if (!adding.value) return
  drafted.value.push(adding.value)
  adding.value = undefined
}
</script>

<template>
  <SectionCard
    icon="i-lucide-stamp"
    :title="t('letterhead.title')"
  >
    <p class="text-caption text-muted mb-4">
      {{ t('letterhead.intro') }}
    </p>

    <USkeleton
      v-if="!loaded"
      class="h-40 w-full"
    />

    <div
      v-else
      class="space-y-4"
      data-testid="letterheads"
    >
      <LetterheadEditor
        :professional-id="null"
        :title="t('letterhead.clinic')"
        :letterhead="clinicLetterhead"
        :can-edit="canEdit"
        @changed="load"
      />
      <LetterheadEditor
        v-for="card in doctorCards"
        :key="card.id"
        :professional-id="card.id"
        :title="card.name"
        :letterhead="card.letterhead"
        :suggested-subheading="card.suggested"
        :can-edit="canEdit"
        @changed="load"
      />
      <div
        v-if="canEdit && addable.length"
        class="flex items-end gap-2 flex-wrap"
      >
        <UFormField
          :label="t('letterhead.addFor')"
          class="min-w-56"
        >
          <USelect
            v-model="adding"
            :items="addable"
            value-key="value"
            :placeholder="t('letterhead.pickProfessional')"
            class="w-full"
            data-testid="letterhead-add-select"
          />
        </UFormField>
        <UButton
          icon="i-lucide-plus"
          variant="soft"
          :disabled="!adding"
          data-testid="letterhead-add"
          @click="addDoctor"
        >
          {{ t('letterhead.add') }}
        </UButton>
      </div>
      <p class="text-caption text-subtle">
        {{ t('letterhead.rule') }}
      </p>
    </div>
  </SectionCard>
</template>
