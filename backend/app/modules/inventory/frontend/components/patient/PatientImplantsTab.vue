<script setup lang="ts">
/**
 * The "Implantes" tab of the patient record (`patient.detail.tabs`).
 *
 * What this patient carries: which device, from which batch, placed
 * when and where. The patient comes from the slot's context, so this
 * module never calls the Patients App for it (ADR 0041).
 *
 * This is the one place the inventory shows patient data, and the
 * record behind it is the one that survives an erasure request — a
 * withdrawn batch has to remain traceable to the people carrying it.
 */
import type { PatientExtended } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'
import type { ImplantTrace } from '../../composables/useInventory'

const props = defineProps<{ ctx: { patient: PatientExtended } }>()

const { t, locale } = useI18n()
const { can } = usePermissions()
const { implants: listImplants } = useInventory()

const canWrite = computed(() => can(PERMISSIONS.inventory.implantsWrite))

const rows = ref<ImplantTrace[]>([])
const isLoading = ref(true)
const modalOpen = ref(false)

async function load() {
  isLoading.value = true
  try {
    rows.value = (await listImplants({ patient_id: props.ctx.patient.id })).data
  } finally {
    isLoading.value = false
  }
}

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale.value, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  })
}

watch(() => props.ctx.patient.id, () => load())

onMounted(() => load())
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
      <p class="text-sm text-subtle">
        {{ t('inventory.implants.patientSubtitle') }}
      </p>
      <UButton
        v-if="canWrite"
        icon="i-lucide-plus"
        :label="t('inventory.implants.add')"
        @click="modalOpen = true"
      />
    </div>

    <USkeleton
      v-if="isLoading"
      class="h-32 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-6 text-center text-subtle"
    >
      {{ t('inventory.implants.noneForPatient') }}
    </p>

    <ul
      v-else
      class="divide-y divide-default rounded-token-md border border-default"
    >
      <li
        v-for="trace in rows"
        :key="trace.id"
        class="bg-default p-3"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-medium">
              {{ trace.item_name }}
              <span
                v-if="trace.tooth_number"
                class="text-sm text-subtle"
              >· {{ t('inventory.implants.tooth') }} {{ trace.tooth_number }}</span>
            </p>
            <p class="text-xs text-subtle">
              {{ t('inventory.lot') }} <span class="font-mono">{{ trace.lot_code }}</span>
              <template v-if="trace.serial_number">
                · {{ t('inventory.implants.serial') }} {{ trace.serial_number }}
              </template>
            </p>
            <p
              v-if="trace.notes"
              class="mt-1 text-xs text-toned"
            >
              {{ trace.notes }}
            </p>
          </div>
          <span class="shrink-0 text-sm">{{ formatDate(trace.placed_on) }}</span>
        </div>
      </li>
    </ul>

    <RecordImplantModal
      v-model:open="modalOpen"
      :patient-id="props.ctx.patient.id"
      @recorded="load"
    />
  </div>
</template>
