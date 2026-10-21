<script setup lang="ts">
/**
 * ToothEruptionModal — where a tooth is in its life, and the exchange of a
 * primary tooth for its successor.
 *
 * Opened by clicking a tooth with no treatment armed (or right-clicking it).
 * The status is the clinician's word on the tooth and decides before the
 * eruption chronology; "Not said" gives the decision back to the chronology.
 * For a primary tooth, *Exchange* marks it exfoliated and its successor
 * erupting in one step — both land in the tooth history.
 */
import { getToothNameKey } from '~~/app/config/odontogramConstants'
import { successorOf, type EruptionStatus } from '../../utils/dentitionLayout'

const props = defineProps<{
  /** The tooth, or `null` while closed. */
  toothNumber: number | null
  patientId: string
  status: EruptionStatus | null
}>()

const emit = defineEmits<{
  close: []
  changed: []
}>()

const { t } = useI18n()
const api = useApi()
const toast = useToast()

const NOT_SAID = 'not_said'
const chosen = ref<string>(NOT_SAID)
const saving = ref(false)

watch(() => [props.toothNumber, props.status] as const, () => {
  chosen.value = props.status ?? NOT_SAID
}, { immediate: true })

const isPrimary = computed(() => props.toothNumber !== null && props.toothNumber >= 51)
const successor = computed(() => (props.toothNumber === null ? null : successorOf(props.toothNumber)))

const options = computed(() => {
  const statuses: EruptionStatus[] = [
    'unerupted',
    'erupting',
    'erupted',
    ...(isPrimary.value ? ['exfoliated' as const] : []),
    'congenitally_missing',
    'impacted'
  ]
  return [
    { value: NOT_SAID, label: t('odontogram.eruption.notSaid'), description: t('odontogram.eruption.notSaidHelp') },
    ...statuses.map(status => ({ value: status, label: t(`odontogram.eruption.status.${status}`) }))
  ]
})

async function save() {
  if (props.toothNumber === null) return
  saving.value = true
  try {
    await api.put(`/api/v1/odontogram/patients/${props.patientId}/teeth/${props.toothNumber}`, {
      eruption_status: chosen.value === NOT_SAID ? null : chosen.value
    })
    emit('changed')
    emit('close')
  } catch {
    toast.add({ title: t('odontogram.eruption.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

async function exchange() {
  if (props.toothNumber === null) return
  saving.value = true
  try {
    await api.post(`/api/v1/odontogram/patients/${props.patientId}/odontogram/exchange`, {
      primary_tooth: props.toothNumber
    })
    toast.add({
      title: t('odontogram.eruption.exchanged', { tooth: props.toothNumber, successor: successor.value }),
      color: 'success'
    })
    emit('changed')
    emit('close')
  } catch {
    toast.add({ title: t('odontogram.eruption.saveFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <UModal
    :open="toothNumber !== null"
    @update:open="(open: boolean) => { if (!open) emit('close') }"
  >
    <template #content>
      <UCard
        v-if="toothNumber !== null"
        data-testid="tooth-eruption-modal"
      >
        <template #header>
          <h2 class="text-h2 text-default">
            {{ t('odontogram.eruption.title', { tooth: toothNumber, name: t(getToothNameKey(toothNumber)) }) }}
          </h2>
          <p class="text-caption text-subtle mt-1">
            {{ t(isPrimary ? 'odontogram.dentition.deciduous' : 'odontogram.dentition.permanent') }}
          </p>
        </template>

        <div class="space-y-4">
          <URadioGroup
            v-model="chosen"
            :items="options"
            value-key="value"
            :legend="t('odontogram.eruption.legend')"
            data-testid="tooth-eruption-status"
          />

          <div
            v-if="successor !== null"
            class="rounded-token-lg border border-subtle bg-surface-muted p-3 space-y-2"
          >
            <p class="text-sm text-default">
              {{ t('odontogram.eruption.exchangeHelp', { tooth: toothNumber, successor }) }}
            </p>
            <UButton
              icon="i-lucide-repeat"
              variant="soft"
              :loading="saving"
              data-testid="tooth-eruption-exchange"
              @click="exchange"
            >
              {{ t('odontogram.eruption.exchange', { tooth: toothNumber, successor }) }}
            </UButton>
          </div>
        </div>

        <template #footer>
          <div class="flex justify-end gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              @click="emit('close')"
            >
              {{ t('actions.cancel') }}
            </UButton>
            <UButton
              :loading="saving"
              data-testid="tooth-eruption-save"
              @click="save"
            >
              {{ t('actions.save') }}
            </UButton>
          </div>
        </template>
      </UCard>
    </template>
  </UModal>
</template>
