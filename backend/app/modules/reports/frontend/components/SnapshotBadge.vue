<script setup lang="ts">
/**
 * SnapshotBadge — marks a figure that ignores the period filter.
 *
 * Some numbers are the clinic's state right now, not a total for the
 * range: patient credit, receivables by age, overdue invoices, numbering
 * gaps. Next to range-scoped figures they read as a contradiction
 * ("invoiced 0, overdue 2"), so each one says so.
 */
const { t } = useI18n()
</script>

<template>
  <span
    class="inline-flex items-center gap-1 text-caption text-subtle"
    :title="t('reports.snapshotTooltip')"
  >
    <UIcon
      name="i-lucide-clock"
      class="w-3 h-3"
    />
    {{ t('reports.snapshotBadge') }}
  </span>
</template>
