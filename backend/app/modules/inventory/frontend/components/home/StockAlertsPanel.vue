<script setup lang="ts">
import { formatDateOnly } from '~~/app/utils/date'

/**
 * Home widget: what the stock needs today — articles below their minimum,
 * lots about to expire and lots already expired.
 */
defineProps<{ ctx?: unknown }>()

interface Line {
  item_id: string
  item_name: string
  location_name: string
  lot_id: string | null
  lot_code: string | null
  expires_on: string | null
  quantity: string
  base_unit: string
}

interface Alerts {
  low_stock: Line[]
  expiring: Line[]
  expired: Line[]
}

const { t, locale } = useI18n()
const api = useApi()

const alerts = ref<Alerts | null>(null)
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the stock is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

function line(name: string, qty: string, unit: string, expiresInDays?: number): Line {
  return {
    item_id: `preview-item-${name}`,
    item_name: name,
    location_name: 'Almacén',
    lot_id: expiresInDays === undefined ? null : `preview-lot-${name}`,
    lot_code: expiresInDays === undefined ? null : 'L-0425',
    expires_on: expiresInDays === undefined
      ? null
      : new Date(Date.now() + expiresInDays * 86_400_000).toISOString().split('T')[0] as string,
    quantity: qty,
    base_unit: unit
  }
}

function sample(): Alerts {
  return {
    low_stock: [line('Guantes de nitrilo M', '2', 'caja'), line('Composite A2', '1', 'jeringa')],
    expiring: [line('Anestesia articaína 4%', '12', 'carpule', 18)],
    expired: [line('Hipoclorito 5,25%', '1', 'frasco', -3)]
  }
}

async function load() {
  if (preview) {
    alerts.value = sample()
    pending.value = false
    return
  }
  try {
    const res = await api.get<{ data: Alerts }>('/api/v1/inventory/stock/alerts')
    alerts.value = res.data
  } catch {
    alerts.value = null
  } finally {
    pending.value = false
  }
}

onMounted(load)
onActivated(load)

const groups = computed(() => {
  const a = alerts.value
  if (!a) return []
  return ([
    ['expired', 'danger', a.expired],
    ['expiring', 'warning', a.expiring],
    ['low_stock', 'warning', a.low_stock]
  ] as const)
    .filter(([, , lines]) => lines.length > 0)
    .map(([key, tone, lines]) => ({ key, tone, lines: lines.slice(0, 3), total: lines.length }))
})

function detail(key: string, l: Line): string {
  if (key === 'low_stock' || !l.expires_on) return `${Number(l.quantity)} ${l.base_unit} · ${l.location_name}`
  return t(`dashboard.stockAlerts.${key === 'expired' ? 'expiredOn' : 'expiresOn'}`, {
    date: formatDateOnly(l.expires_on, locale.value, { day: '2-digit', month: 'short' })
  })
}
</script>

<template>
  <SectionCard
    icon="i-lucide-package-search"
    icon-role="warning"
    :title="t('dashboard.stockAlerts.title')"
  >
    <template #actions>
      <UButton
        to="/inventario"
        variant="ghost"
        color="neutral"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        :aria-label="t('dashboard.stockAlerts.all')"
      />
    </template>

    <div
      v-if="pending"
      class="space-y-2"
    >
      <USkeleton
        v-for="i in 3"
        :key="i"
        class="h-10 w-full"
      />
    </div>

    <EmptyState
      v-else-if="groups.length === 0"
      icon="i-lucide-package-check"
      :title="t('dashboard.stockAlerts.empty')"
    />

    <div
      v-else
      class="space-y-4"
    >
      <section
        v-for="group in groups"
        :key="group.key"
      >
        <p
          class="text-caption uppercase tracking-wide mb-1"
          :class="group.tone === 'danger' ? 'text-error' : 'text-warning'"
        >
          {{ t(`dashboard.stockAlerts.${group.key}`, { n: group.total }) }}
        </p>
        <ul class="divide-y divide-[var(--color-border-subtle)]">
          <li
            v-for="l in group.lines"
            :key="`${l.item_id}-${l.lot_id}-${l.location_name}`"
          >
            <ListRow to="/inventario">
              <template #title>
                {{ l.item_name }}
              </template>
              <template #subtitle>
                {{ detail(group.key, l) }}
              </template>
            </ListRow>
          </li>
        </ul>
      </section>
    </div>
  </SectionCard>
</template>
