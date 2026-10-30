<script setup lang="ts">
/**
 * BackButton — the one way back out of a detail screen.
 *
 * An icon-only arrow immediately left of the title. It is a link, not a
 * `router.back()`: landing on a bookmarked detail page must still lead
 * somewhere sensible. The label lives in `aria-label` so the control
 * reads the same whatever the destination is called.
 */
interface Props {
  to: string
  /** Overrides the default "Volver" for a destination worth naming. */
  label?: string
}

withDefaults(defineProps<Props>(), {
  label: undefined
})

const { t } = useI18n()
</script>

<template>
  <UButton
    variant="ghost"
    color="neutral"
    icon="i-lucide-arrow-left"
    :to="to"
    :aria-label="label ?? t('common.back')"
    class="shrink-0"
  />
</template>
