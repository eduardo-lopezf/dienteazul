<script setup lang="ts">
/**
 * Envío programado — when the one-page summary leaves on its own.
 *
 * Deliberately small: a switch, a cadence and a list of addresses. The
 * only state that matters is "is anybody getting this and when", and a
 * screen that asked more questions would be a screen nobody finishes.
 *
 * It lives here rather than in Ajustes because the summary is a
 * Productividad thing and because the e-mail it sends says so — the
 * footer of every send points back to this screen.
 */
import { useSummarySchedule, type Cadence } from '../composables/useSummarySchedule'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const { t, locale } = useI18n()
const toast = useToast()
const { schedule, loading, saving, load, save } = useSummarySchedule()

const CADENCES: Cadence[] = ['weekly', 'monthly']

const isActive = ref(false)
const cadence = ref<Cadence>('monthly')
/** One input per row; a blank row is how "add another" starts. */
const recipients = ref<string[]>([''])

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    await load()
    isActive.value = schedule.value?.is_active ?? false
    cadence.value = schedule.value?.cadence ?? 'monthly'
    recipients.value = schedule.value?.recipients.length
      ? [...schedule.value.recipients]
      : ['']
  }
)

const filled = computed(() => recipients.value.map(r => r.trim()).filter(Boolean))

// Turning it on with nobody to send to is the one state that looks
// configured and does nothing, so the button says so instead.
const blocked = computed(() => isActive.value && filled.value.length === 0)

const lastSent = computed(() => {
  const value = schedule.value?.last_sent_for
  if (!value) return null
  return new Date(`${value}T00:00:00`).toLocaleDateString(locale.value)
})

function addRow() {
  recipients.value.push('')
}

function removeRow(index: number) {
  recipients.value.splice(index, 1)
  if (recipients.value.length === 0) recipients.value = ['']
}

async function submit() {
  try {
    await save({
      is_active: isActive.value,
      cadence: cadence.value,
      recipients: filled.value
    })
    toast.add({ title: t('reports.scheduleSummary.saved'), color: 'success' })
    emit('update:open', false)
  } catch {
    // `$api` surfaces the reason; this names the action that failed.
    toast.add({ title: t('reports.scheduleSummary.failed'), color: 'error' })
  }
}
</script>

<template>
  <UModal
    :open="open"
    :title="t('reports.scheduleSummary.title')"
    :description="t('reports.scheduleSummary.subtitle')"
    @update:open="emit('update:open', $event)"
  >
    <template #body>
      <div
        v-if="loading"
        class="space-y-2"
      >
        <USkeleton class="h-10 w-full" />
        <USkeleton class="h-10 w-full" />
      </div>

      <div
        v-else
        class="space-y-4"
      >
        <USwitch
          v-model="isActive"
          :label="t('reports.scheduleSummary.active')"
        />

        <UFormField :label="t('reports.scheduleSummary.cadence')">
          <USelect
            v-model="cadence"
            :items="CADENCES.map(c => ({
              label: t(`reports.scheduleSummary.cadences.${c}`),
              value: c
            }))"
          />
        </UFormField>

        <UFormField
          :label="t('reports.scheduleSummary.recipients')"
          :hint="t('reports.scheduleSummary.recipientsHint')"
        >
          <div class="space-y-2">
            <div
              v-for="(_, index) in recipients"
              :key="index"
              class="flex items-center gap-2"
            >
              <UInput
                v-model="recipients[index]"
                type="email"
                class="flex-1"
                placeholder="nombre@clinica.com"
              />
              <UButton
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                :aria-label="t('reports.scheduleSummary.removeRecipient')"
                @click="removeRow(index)"
              />
            </div>
            <UButton
              color="neutral"
              variant="ghost"
              icon="i-lucide-plus"
              size="sm"
              @click="addRow"
            >
              {{ t('reports.scheduleSummary.addRecipient') }}
            </UButton>
          </div>
        </UFormField>

        <p
          v-if="lastSent"
          class="text-caption text-subtle"
        >
          {{ t('reports.scheduleSummary.lastSent', { date: lastSent }) }}
        </p>
      </div>
    </template>

    <template #footer>
      <div class="flex items-center justify-end gap-2 w-full">
        <UButton
          color="neutral"
          variant="ghost"
          @click="emit('update:open', false)"
        >
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          color="primary"
          :loading="saving"
          :disabled="blocked"
          :title="blocked ? t('reports.scheduleSummary.needsRecipient') : undefined"
          @click="submit"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
