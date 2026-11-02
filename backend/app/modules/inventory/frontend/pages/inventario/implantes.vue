<script setup lang="ts">
/**
 * Implantes — the recall screen.
 *
 * One question, and it is why the table behind it exists: a
 * manufacturer withdraws a batch, and the clinic needs the list of the
 * people carrying it, today, by name.
 *
 * Recording a device happens on the patient's own record, not here:
 * this module has no patient picker and calls no Patients API. What it
 * shows of a patient comes through the `PatientDirectory` contract, so
 * with that App off the ids remain and the names do not.
 */
import type { ImplantTrace, InventoryItem, InventoryLot } from '../../composables/useInventory'
import { PERMISSIONS } from '~~/app/config/permissions'

definePageMeta({ middleware: ['auth'] })

/** Sentinel for "any": Reka UI reserves the empty string. */
const ANY = '__any__'

const { t, locale } = useI18n()
const { can } = usePermissions()
const { implants: listImplants, items: listItems, lots: listLots } = useInventory()

if (!can(PERMISSIONS.inventory.implantsRead)) {
  await navigateTo('/inventario')
}

const itemId = ref<string>(ANY)
const lotId = ref<string>(ANY)
const rows = ref<ImplantTrace[]>([])
const articles = ref<InventoryItem[]>([])
const lots = ref<InventoryLot[]>([])
const isLoading = ref(true)

const articleOptions = computed(() => [
  { value: ANY, label: t('inventory.implants.allDevices') },
  ...articles.value
    .filter(article => article.tracks_lots)
    .map(article => ({ value: article.id, label: `${article.code} · ${article.name}` }))
])

const lotOptions = computed(() => [
  { value: ANY, label: t('inventory.implants.allLots') },
  ...lots.value.map(lot => ({ value: lot.id, label: lot.lot_code }))
])

function patientName(trace: ImplantTrace): string {
  const name = `${trace.first_name ?? ''} ${trace.last_name ?? ''}`.trim()
  return name || t('inventory.implants.unnamedPatient')
}

function formatDate(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(locale.value, {
    day: '2-digit',
    month: 'short',
    year: 'numeric'
  })
}

async function load() {
  isLoading.value = true
  try {
    rows.value = (
      await listImplants({
        item_id: itemId.value === ANY ? undefined : itemId.value,
        lot_id: lotId.value === ANY ? undefined : lotId.value
      })
    ).data
  } finally {
    isLoading.value = false
  }
}

watch(itemId, async (value) => {
  lotId.value = ANY
  lots.value = value === ANY ? [] : (await listLots(value)).data
  await load()
})
watch(lotId, () => load())

onMounted(async () => {
  articles.value = (await listItems()).data
  await load()
})
</script>

<template>
  <UContainer class="py-6">
    <div class="mb-6">
      <UButton
        variant="ghost"
        icon="i-lucide-arrow-left"
        :label="t('inventory.stock')"
        to="/inventario"
      />
      <h1 class="mt-2 text-xl font-semibold">
        {{ t('inventory.implants.title') }}
      </h1>
      <p class="text-sm text-subtle">
        {{ t('inventory.implants.subtitle') }}
      </p>
    </div>

    <div class="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <USelect
        v-model="itemId"
        :items="articleOptions"
        value-key="value"
        :aria-label="t('inventory.implants.allDevices')"
      />
      <USelect
        v-model="lotId"
        :items="lotOptions"
        value-key="value"
        :disabled="itemId === ANY"
        :aria-label="t('inventory.implants.allLots')"
      />
    </div>

    <USkeleton
      v-if="isLoading"
      class="h-48 w-full"
    />

    <p
      v-else-if="rows.length === 0"
      class="rounded-token-md border border-default bg-default p-8 text-center text-subtle"
    >
      {{ t('inventory.implants.empty') }}
    </p>

    <div
      v-else
      class="overflow-x-auto rounded-token-md border border-default"
    >
      <table class="w-full text-sm">
        <thead class="bg-elevated text-left text-xs text-subtle">
          <tr>
            <th class="p-3">
              {{ t('inventory.implants.patient') }}
            </th>
            <th class="p-3">
              {{ t('inventory.implants.device') }}
            </th>
            <th class="p-3">
              {{ t('inventory.lot') }}
            </th>
            <th class="p-3">
              {{ t('inventory.implants.tooth') }}
            </th>
            <th class="p-3">
              {{ t('inventory.implants.serial') }}
            </th>
            <th class="p-3">
              {{ t('inventory.implants.placedOn') }}
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-default">
          <tr
            v-for="trace in rows"
            :key="trace.id"
            class="bg-default"
          >
            <td class="p-3 font-medium">
              {{ patientName(trace) }}
            </td>
            <td class="p-3">
              {{ trace.item_name }}
              <span class="text-xs text-subtle">{{ trace.item_code }}</span>
            </td>
            <td class="p-3 font-mono text-xs">
              {{ trace.lot_code }}
            </td>
            <td class="p-3">
              {{ trace.tooth_number ?? '—' }}
            </td>
            <td class="p-3">
              {{ trace.serial_number ?? '—' }}
            </td>
            <td class="p-3 whitespace-nowrap">
              {{ formatDate(trace.placed_on) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p class="mt-4 text-xs text-subtle">
      {{ t('inventory.implants.retentionNote') }}
    </p>
  </UContainer>
</template>
