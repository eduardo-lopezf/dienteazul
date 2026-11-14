<script setup lang="ts">
/**
 * Resumen tile: how the till stands, and above all what has not been counted.
 *
 * `pending_days` is the number this module exists to surface and the only
 * one no query could produce — and until now it was only visible to
 * somebody who opened the Caja tab and looked at the period card. An arqueo
 * abandoned for three weeks was discovered when a discrepancy was hunted,
 * which is the worst moment to discover it.
 *
 * The period is the fortnight because that is the cut a Mexican clinic
 * works to, and `/periods` takes any day inside it rather than its bounds —
 * where a quincena starts is the module's business, not this tile's.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import { formatDateOnly } from '~~/app/utils/date'

const { t, locale } = useI18n()
const api = useApi()
const { can } = usePermissions()
const { format: money } = useCurrency()
const { currentClinic } = useClinic()

interface Period {
  pending_days: string[]
  counted_days: number
  days_off: number
  difference_total: string
}

const period = ref<Period | null>(null)
const loading = ref(true)
const failed = ref(false)

/** The clinic's today, which is the day the backend counts by. */
function clinicToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: currentClinic.value?.timezone || undefined,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(new Date())
}

// Inside a widget example (Settings → Widgets) the fortnight is made up
// and nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

async function load() {
  if (preview) {
    const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().split('T')[0] as string
    period.value = { pending_days: [day(1), day(4)], counted_days: 6, days_off: 1, difference_total: '-50.00' }
    loading.value = false
    return
  }
  try {
    const response = await api.get<{ data: Period }>(
      `/api/v1/cashbox/periods?kind=fortnight&day=${clinicToday()}`
    )
    period.value = response.data
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (can(PERMISSIONS.cashbox.closingRead)) void load()
  else loading.value = false
})

const pending = computed(() => period.value?.pending_days ?? [])

/**
 * Three states, not two.
 *
 * `pending_days` counts days that saw money and were never counted, so a
 * fortnight with no movement at all has none — and reading that as "al día"
 * tells a clinic that has never done an arqueo that it is up to date. The
 * quiet case gets its own sentence instead.
 */
const state = computed<'pending' | 'counted' | 'quiet'>(() => {
  if (pending.value.length) return 'pending'
  return (period.value?.counted_days ?? 0) > 0 ? 'counted' : 'quiet'
})
</script>

<template>
  <UCard v-if="!failed && can(PERMISSIONS.cashbox.closingRead)">
    <template #header>
      <div class="flex items-center gap-2">
        <UIcon
          name="i-lucide-calculator"
          class="w-4 h-4"
          :class="pending.length ? 'text-warning' : 'text-muted'"
        />
        <span class="text-caption text-muted">{{ t('cashbox.summaryTile.title') }}</span>
      </div>
    </template>

    <USkeleton
      v-if="loading"
      class="h-12 w-full"
    />

    <div v-else-if="state === 'pending'">
      <p class="tile-value text-warning">
        {{ t('cashbox.summaryTile.pending', { n: pending.length }, pending.length) }}
      </p>
      <p class="text-caption text-subtle">
        {{ pending.slice(0, 3).map(d => formatDateOnly(d, locale, { day: '2-digit', month: 'short' })).join(' · ') }}
        <span v-if="pending.length > 3">…</span>
      </p>
      <UButton
        to="/finanzas?tab=cashbox"
        color="neutral"
        variant="soft"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        class="mt-3"
      >
        {{ t('cashbox.summaryTile.count') }}
      </UButton>
    </div>

    <div v-else-if="state === 'counted'">
      <p class="tile-value text-muted">
        {{ t('cashbox.summaryTile.upToDate') }}
      </p>
      <p class="text-caption text-subtle">
        {{ t('cashbox.summaryTile.counted', { n: period?.counted_days ?? 0 }, period?.counted_days ?? 0) }}
        <template v-if="period?.days_off">
          · {{ t('cashbox.summaryTile.daysOff', { n: period.days_off }, period.days_off) }}
          ({{ money(period.difference_total) }})
        </template>
      </p>
    </div>

    <div v-else>
      <p class="tile-value text-muted">
        {{ t('cashbox.summaryTile.quiet') }}
      </p>
      <p class="text-caption text-subtle">
        {{ t('cashbox.summaryTile.quietHint') }}
      </p>
    </div>
  </UCard>
</template>

<style scoped>
.tile-value {
  font-size: 20px;
  font-weight: 600;
  line-height: 1.25;
}
</style>
