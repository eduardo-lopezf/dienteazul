<script setup lang="ts">
import type { PaginatedResponse } from '~~/app/types'

/**
 * Home widget: messages to patients that could not be delivered, newest
 * first. A failed reminder is a patient who does not know about their
 * appointment, so it belongs where reception looks every morning.
 */
defineProps<{ ctx?: unknown }>()

interface Row {
  id: string
  channel: string
  to_address: string
  patient_id: string | null
  template_key: string
  error_message: string | null
  created_at: string
}

const { t, te, locale } = useI18n()
const api = useApi()

const rows = ref<Row[]>([])
const total = ref(0)
const pending = ref(true)
// Inside a widget example (Settings → Widgets) the list is made up and
// nothing is fetched (ADR 0040).
const preview = useWidgetPreview()

function sample(): Row[] {
  const now = Date.now()
  return [
    ['email', 'laura@ejemplo.test', 'appointment_reminder', 'Buzón lleno', 2],
    ['whatsapp', '+52 55 1000 0002', 'appointment_confirmation', 'El número no tiene WhatsApp', 20],
    ['email', 'ivan@ejemplo.test', 'budget_sent', 'Dominio inexistente', 50]
  ].map(([channel, to_address, template_key, error_message, hours], i) => ({
    id: `preview-message-${i + 1}`,
    channel: channel as string,
    to_address: to_address as string,
    patient_id: null,
    template_key: template_key as string,
    error_message: error_message as string,
    created_at: new Date(now - (hours as number) * 3_600_000).toISOString()
  }))
}

async function load() {
  if (preview) {
    rows.value = sample()
    total.value = rows.value.length
    pending.value = false
    return
  }
  try {
    const res = await api.get<PaginatedResponse<Row>>(
      '/api/v1/notifications/logs?status=failed&page_size=5'
    )
    rows.value = res.data
    total.value = res.total
  } catch {
    rows.value = []
    total.value = 0
  } finally {
    pending.value = false
  }
}

onMounted(load)
onActivated(load)

function templateLabel(key: string): string {
  const k = `notifications.types.${key}`
  return te(k) ? t(k) : key
}

function when(iso: string): string {
  return new Date(iso).toLocaleDateString(locale.value, { day: 'numeric', month: 'short' })
}
</script>

<template>
  <SectionCard
    icon="i-lucide-mail-x"
    icon-role="danger"
    :title="t('dashboard.failedMessages.title')"
  >
    <template #actions>
      <UButton
        to="/settings/notifications"
        variant="ghost"
        color="neutral"
        size="xs"
        trailing-icon="i-lucide-arrow-right"
        :aria-label="t('dashboard.failedMessages.settings')"
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
      v-else-if="rows.length === 0"
      icon="i-lucide-mail-check"
      :title="t('dashboard.failedMessages.empty')"
    />

    <ul
      v-else
      class="divide-y divide-[var(--color-border-subtle)]"
    >
      <li
        v-for="row in rows"
        :key="row.id"
      >
        <ListRow :to="row.patient_id ? `/patients/${row.patient_id}` : undefined">
          <template #leading>
            <UIcon
              :name="row.channel === 'whatsapp' ? 'i-lucide-message-circle' : 'i-lucide-mail'"
              class="size-4 text-muted"
            />
          </template>
          <template #title>
            {{ row.to_address }}
          </template>
          <template #subtitle>
            {{ templateLabel(row.template_key) }}<template v-if="row.error_message">
              · {{ row.error_message }}
            </template>
          </template>
          <template #meta>
            <span class="text-caption text-subtle tnum">{{ when(row.created_at) }}</span>
          </template>
        </ListRow>
      </li>
    </ul>
    <p
      v-if="total > rows.length"
      class="mt-2 text-caption text-subtle"
    >
      {{ t('dashboard.failedMessages.more', { n: total - rows.length }) }}
    </p>
  </SectionCard>
</template>
