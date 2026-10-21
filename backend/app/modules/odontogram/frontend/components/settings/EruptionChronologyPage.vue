<script setup lang="ts">
/**
 * EruptionChronologyPage — the clinic's usual eruption age per permanent
 * tooth position, upper and lower.
 *
 * It decides which tooth a mixed dentition shows when nothing is charted on
 * it, and when the chart warns of a late eruption or a primary tooth kept
 * too long. The usual chronology applies until the clinic sets its own;
 * *Back to the usual chronology* clears it.
 */
type Ages = Record<'upper' | 'lower', Record<string, number>>

const { t } = useI18n()
const api = useApi()
const toast = useToast()

const URL = '/api/v1/odontogram/settings/eruption-ages'
const POSITIONS = ['1', '2', '3', '4', '5', '6', '7', '8']
const ARCHES = ['upper', 'lower'] as const

const ages = ref<Ages | null>(null)
const saving = ref(false)

async function load() {
  ages.value = (await api.get<{ data: Ages }>(URL)).data
}

async function save(next: Ages | null) {
  saving.value = true
  try {
    ages.value = (await api.put<{ data: Ages }>(URL, { ages: next })).data
    toast.add({ title: t('odontogram.eruption.settings.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('odontogram.eruption.settings.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <UCard v-if="ages">
    <div class="space-y-4">
      <div class="overflow-x-auto">
        <table
          class="w-full text-sm"
          data-testid="eruption-chronology"
        >
          <thead>
            <tr class="border-b border-subtle text-left">
              <th class="py-2 pr-3">
                {{ t('odontogram.eruption.settings.position') }}
              </th>
              <th
                v-for="arch in ARCHES"
                :key="arch"
                class="py-2 pr-3"
              >
                {{ t(`odontogram.eruption.settings.${arch}`) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="position in POSITIONS"
              :key="position"
              class="border-b border-subtle"
            >
              <td class="py-2 pr-3">
                {{ position }} · {{ t(`odontogram.eruption.settings.positions.${position}`) }}
              </td>
              <td
                v-for="arch in ARCHES"
                :key="arch"
                class="py-1 pr-3"
              >
                <UInput
                  v-model.number="ages[arch][position]"
                  type="number"
                  :min="0"
                  :max="30"
                  class="w-24"
                  :aria-label="`${t(`odontogram.eruption.settings.${arch}`)} ${position} · ${t('odontogram.eruption.settings.age')}`"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <template #footer>
      <div class="flex flex-wrap justify-end gap-2">
        <UButton
          color="neutral"
          variant="ghost"
          :disabled="saving"
          data-testid="eruption-chronology-reset"
          @click="save(null)"
        >
          {{ t('odontogram.eruption.settings.reset') }}
        </UButton>
        <UButton
          :loading="saving"
          data-testid="eruption-chronology-save"
          @click="save(ages)"
        >
          {{ t('actions.save') }}
        </UButton>
      </div>
    </template>
  </UCard>
</template>
