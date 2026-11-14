<script setup lang="ts">
/**
 * Home widget: consent letters written and never signed, oldest first.
 * An informed consent still in draft is a treatment that, on paper, the
 * patient has not agreed to.
 */
defineProps<{ ctx?: unknown }>()

interface Item {
  id: string
  patient_id: string
  first_name: string | null
  last_name: string | null
  kind: string
  title: string
  created_at: string
}

const { t, locale } = useI18n()
const api = useApi()

const items = ref<Item[]>([])
const total = ref(0)
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the list is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

function sample(): Item[] {
  const now = Date.now()
  const rows: [string, string, string, string, number][] = [
    ['Laura', 'Demo', 'informed', 'Extracción del 48', 9],
    ['Diego', 'Muestra', 'informed', 'Implante unitario', 4],
    ['Carmen', 'Modelo', 'data_use', 'Aviso de privacidad', 1]
  ]
  return rows.map(([first_name, last_name, kind, title, days], i) => ({
    id: `preview-consent-${i + 1}`,
    patient_id: `preview-patient-${i + 1}`,
    first_name,
    last_name,
    kind,
    title,
    created_at: new Date(now - days * 86_400_000).toISOString()
  }))
}

async function load() {
  if (preview) {
    items.value = sample()
    total.value = items.value.length
    pending.value = false
    return
  }
  try {
    const res = await api.get<{ data: { total: number, items: Item[] } }>('/api/v1/consents/unsigned?limit=5')
    items.value = res.data.items
    total.value = res.data.total
  } catch {
    items.value = []
    total.value = 0
  } finally {
    pending.value = false
  }
}

onMounted(load)
onActivated(load)

function since(iso: string): string {
  const days = Math.round((Date.now() - new Date(iso).getTime()) / 86_400_000)
  return new Intl.RelativeTimeFormat(locale.value, { numeric: 'auto' }).format(-days, 'day')
}
</script>

<template>
  <SectionCard
    icon="i-lucide-file-signature"
    icon-role="warning"
    :title="t('dashboard.unsignedConsents.title')"
  >
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
      v-else-if="items.length === 0"
      icon="i-lucide-file-check"
      :title="t('dashboard.unsignedConsents.empty')"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="item in items"
        :key="item.id"
      >
        <ListRow :to="`/patients/${item.patient_id}?tab=consents`">
          <template #title>
            {{ item.first_name ? `${item.first_name} ${item.last_name ?? ''}` : item.title }}
          </template>
          <template #subtitle>
            {{ item.title }} · {{ t(`dashboard.unsignedConsents.kinds.${item.kind}`) }}
          </template>
          <template #meta>
            <span class="text-caption text-subtle tnum">{{ since(item.created_at) }}</span>
          </template>
        </ListRow>
      </li>
    </ul>
    <p
      v-if="total > items.length"
      class="mt-2 text-caption text-subtle"
    >
      {{ t('dashboard.unsignedConsents.more', { n: total - items.length }) }}
    </p>
  </SectionCard>
</template>
