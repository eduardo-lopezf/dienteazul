<script setup lang="ts">
/**
 * The way into a professional's commissions, on their card in the
 * Professionals directory (`professional.profile.actions`). The card knows
 * nothing of this module (ADR 0041).
 */
import type { Professional } from '~~/app/types'

defineProps<{ ctx: { professional: Professional } }>()

const { t } = useI18n()
const open = ref(false)
</script>

<template>
  <ProfessionalCommissionsModal
    v-model:open="open"
    :professional="ctx.professional"
  >
    <UButton
      color="neutral"
      variant="soft"
      icon="i-lucide-percent"
    >
      {{ t('commissions.action') }}
    </UButton>
  </ProfessionalCommissionsModal>
</template>
