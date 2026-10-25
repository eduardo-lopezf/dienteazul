<script setup lang="ts">
interface Props {
  /** ISO date string anchored to day 1 of the target month (YYYY-MM-01). */
  modelValue: string
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const { locale } = useI18n()

const open = ref(false)

const currentDate = computed(() => {
  const value = props.modelValue
  // `YYYY-MM` or `YYYY-MM-DD`, read as a calendar month — never through
  // `new Date('2026-10-01')`, which is midnight UTC and, west of
  // Greenwich, the last day of the month before.
  const match = /^(\d{4})-(\d{2})/.exec(value)
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, 1) : new Date()
})

const viewYear = ref(currentDate.value.getFullYear())

const monthLabels = computed(() => {
  const fmt = new Intl.DateTimeFormat(locale.value, { month: 'short' })
  return Array.from({ length: 12 }, (_, i) => fmt.format(new Date(2000, i, 1)))
})

const triggerLabel = computed(() =>
  new Intl.DateTimeFormat(locale.value, {
    year: 'numeric',
    month: 'long'
  }).format(currentDate.value)
)

const selectedYear = computed(() => currentDate.value.getFullYear())
const selectedMonth = computed(() => currentDate.value.getMonth())

function pick(monthIdx: number) {
  const y = String(viewYear.value).padStart(4, '0')
  const m = String(monthIdx + 1).padStart(2, '0')
  emit('update:modelValue', `${y}-${m}-01`)
  open.value = false
}

function shiftYear(delta: number) {
  viewYear.value += delta
}

function goToday() {
  const today = new Date()
  viewYear.value = today.getFullYear()
  pick(today.getMonth())
}
</script>

<template>
  <UPopover
    v-model:open="open"
    :ui="{ content: 'w-64' }"
  >
    <UButton
      color="neutral"
      variant="outline"
      :label="triggerLabel"
      icon="i-lucide-calendar"
      trailing-icon="i-lucide-chevron-down"
      class="w-full justify-between"
    />
    <template #content>
      <div class="p-3 space-y-3">
        <div class="flex items-center justify-between">
          <UButton
            icon="i-lucide-chevron-left"
            size="xs"
            variant="ghost"
            color="neutral"
            :aria-label="$t('recalls.filters.previousYear')"
            @click="shiftYear(-1)"
          />
          <span class="font-medium tnum">{{ viewYear }}</span>
          <UButton
            icon="i-lucide-chevron-right"
            size="xs"
            variant="ghost"
            color="neutral"
            :aria-label="$t('recalls.filters.nextYear')"
            @click="shiftYear(1)"
          />
        </div>
        <div class="grid grid-cols-3 gap-1">
          <UButton
            v-for="(label, i) in monthLabels"
            :key="i"
            :variant="
              viewYear === selectedYear && i === selectedMonth ? 'solid' : 'soft'
            "
            :color="
              viewYear === selectedYear && i === selectedMonth ? 'primary' : 'neutral'
            "
            size="sm"
            class="capitalize justify-center"
            :label="label"
            @click="pick(i)"
          />
        </div>
        <UButton
          variant="link"
          color="primary"
          size="xs"
          class="w-full justify-center"
          @click="goToday"
        >
          {{ $t('recalls.filters.thisMonth') }}
        </UButton>
      </div>
    </template>
  </UPopover>
</template>
