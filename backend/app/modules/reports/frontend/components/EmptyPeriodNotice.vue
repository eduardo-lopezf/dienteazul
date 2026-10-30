<script setup lang="ts">
/**
 * EmptyPeriodNotice — what to do when the period holds nothing.
 *
 * A screen full of zeroes doesn't say whether the clinic had a quiet
 * month or the range is simply wrong, and the range is the usual
 * culprit: the default is the current month, and on the 2nd of the
 * month that is almost empty by definition. So the notice offers the
 * one move that answers it — widen to the last 12 months — instead of
 * leaving the user to find the period control.
 *
 * The button is hidden once the range already spans a year: there would
 * be nothing to widen to, and an action that changes nothing is worse
 * than none.
 */
const { period } = useReportPeriod()
const { t } = useI18n()

const WIDE_MONTHS = 12

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10)
}

const spansAYearOrMore = computed(() => {
  const from = new Date(`${period.value.from}T00:00:00`)
  const to = new Date(`${period.value.to}T00:00:00`)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return false
  const aYearBefore = new Date(to)
  aYearBefore.setMonth(aYearBefore.getMonth() - WIDE_MONTHS)
  return from <= aYearBefore
})

function widen() {
  const to = new Date()
  const from = new Date(to)
  from.setMonth(from.getMonth() - WIDE_MONTHS)
  period.value = { from: toIso(from), to: toIso(to) }
}
</script>

<template>
  <UAlert
    color="neutral"
    variant="subtle"
    icon="i-lucide-calendar-search"
    :title="t('reports.emptyPeriod.title')"
    :description="t('reports.emptyPeriod.description')"
  >
    <template
      v-if="!spansAYearOrMore"
      #actions
    >
      <UButton
        color="neutral"
        variant="outline"
        size="xs"
        icon="i-lucide-maximize-2"
        @click="widen"
      >
        {{ t('reports.emptyPeriod.widen', { months: WIDE_MONTHS }) }}
      </UButton>
    </template>
  </UAlert>
</template>
