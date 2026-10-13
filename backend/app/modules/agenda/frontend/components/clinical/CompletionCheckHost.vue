<script setup lang="ts">
/**
 * The question asked before an appointment is completed, rendered once at
 * the agenda page level for every path that completes one
 * (``useCompletionCheck``): the visit works on a plan with no signed
 * informed consent. Which plans is the consents' owner's answer, reached
 * through the agenda's own endpoint — nothing here imports another module.
 */
import { PERMISSIONS } from '~/config/permissions'

const { t } = useI18n()
const { can } = usePermissions()
const { pending, reply } = useCompletionCheck()

const letters = computed(() => {
  const patientId = pending.value?.appointment.patient_id
  if (!patientId || !can(PERMISSIONS.consents.write)) return []
  const plans = pending.value?.plans ?? []
  return plans.map(plan => ({
    id: plan.plan_id,
    label: plans.length > 1 && plan.plan_number
      ? `${t('appointments.consentPrompt.write')} · ${plan.plan_number}`
      : t('appointments.consentPrompt.write'),
    to: `/patients/${patientId}?tab=consents&plan=${plan.plan_id}`
  }))
})
</script>

<template>
  <UModal
    :open="pending !== null"
    :title="t('appointments.consentPrompt.title')"
    :description="t('appointments.consentPrompt.description')"
    @update:open="(v: boolean) => { if (!v) reply(false) }"
  >
    <template #footer>
      <div
        class="flex w-full flex-wrap justify-end gap-2"
        data-testid="appointment-consent-prompt"
      >
        <UButton
          color="neutral"
          variant="ghost"
          @click="reply(false)"
        >
          {{ t('common.cancel') }}
        </UButton>
        <UButton
          color="error"
          variant="soft"
          data-testid="appointment-consent-proceed"
          @click="reply(true)"
        >
          {{ t('appointments.consentPrompt.proceed') }}
        </UButton>
        <UButton
          v-for="letter in letters"
          :key="letter.id"
          icon="i-lucide-file-signature"
          :to="letter.to"
          data-testid="appointment-consent-write"
          @click="reply(false)"
        >
          {{ letter.label }}
        </UButton>
      </div>
    </template>
  </UModal>
</template>
