<script setup lang="ts">
/**
 * A professional's own letterhead (Settings → Cuenta → Mi membrete).
 *
 * What heads the documents that answer to them — the consents they
 * explain, the records and questionnaires they print. They set up their
 * own and nobody else's; with none, their documents carry the clinic's.
 */
import type { OwnLetterhead } from '~/composables/useLetterhead'

const { t } = useI18n()
const toast = useToast()
const letterheadApi = useLetterhead()

const own = ref<OwnLetterhead | null>(null)
const loaded = ref(false)

async function load() {
  try {
    own.value = await letterheadApi.mine()
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loaded.value = true
  }
}

onMounted(load)
</script>

<template>
  <div
    class="space-y-4"
    data-testid="my-letterhead"
  >
    <p class="text-sm text-muted">
      {{ t('letterhead.mine.intro') }}
    </p>

    <USkeleton
      v-if="!loaded"
      class="h-40 w-full"
    />

    <UAlert
      v-else-if="!own?.professional_id"
      color="neutral"
      variant="subtle"
      icon="i-lucide-info"
      :title="t('letterhead.mine.notProfessional')"
      data-testid="my-letterhead-none"
    />

    <template v-else>
      <LetterheadEditor
        :professional-id="own.professional_id"
        :title="t('letterhead.mine.title')"
        :letterhead="own.letterhead"
        :suggested-subheading="own.suggested_subheading ?? undefined"
        can-edit
        @changed="load"
      />
      <p class="text-caption text-subtle">
        {{ t('letterhead.mine.fallback') }}
      </p>
    </template>
  </div>
</template>
