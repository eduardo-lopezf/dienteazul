<script setup lang="ts">
/**
 * The operator's notice to this clinic — a maintenance window, something
 * new — shown beside the clinic's name at the top of the workspace, and
 * meant to be easy to miss: muted text, no colour, one line. A click
 * shows the whole message; "Ocultar" puts it away on this device.
 *
 * Read on load and every ten minutes; the newest one in force shows.
 */
import type { ApiResponse } from '~/types'

interface Announcement {
  id: string
  kind: 'maintenance' | 'feature'
  message: string
  starts_at: string
  ends_at: string | null
}

const { t, locale } = useI18n()
const api = useApi()

const STORAGE_KEY = 'announcements:dismissed'
const REFRESH_MS = 10 * 60 * 1000

const announcements = ref<Announcement[]>([])
const dismissed = ref<string[]>([])

function readDismissed(): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(stored) ? stored.filter(id => typeof id === 'string') : []
  } catch {
    return []
  }
}

const shown = computed(() => announcements.value.find(a => !dismissed.value.includes(a.id)) ?? null)

async function load() {
  try {
    announcements.value = (await api.get<ApiResponse<Announcement[]>>('/api/v1/announcements')).data
    // Forget what was put away and no longer shows, so the list stays short.
    const live = new Set(announcements.value.map(a => a.id))
    dismissed.value = dismissed.value.filter(id => live.has(id))
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dismissed.value))
  } catch {
    // A notice is never worth an error on screen.
  }
}

function dismiss(id: string) {
  dismissed.value = [...dismissed.value, id]
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dismissed.value))
  } catch {
    // Without storage it stays hidden until the page is loaded again.
  }
}

const ICONS = { maintenance: 'i-lucide-wrench', feature: 'i-lucide-sparkles' } as const

const until = computed(() =>
  shown.value?.ends_at
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
        .format(new Date(shown.value.ends_at))
    : null
)

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  dismissed.value = readDismissed()
  load()
  timer = setInterval(load, REFRESH_MS)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <UPopover
    v-if="shown"
    :content="{ align: 'start' }"
  >
    <button
      type="button"
      class="ml-3 flex min-w-0 max-w-[40vw] items-center gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-caption text-subtle hover:text-muted"
      :aria-label="t(`announcements.kind.${shown.kind}`)"
      data-testid="workspace-announcement"
    >
      <UIcon
        :name="ICONS[shown.kind]"
        class="size-3.5 shrink-0"
      />
      <span class="hide-on-phone truncate">{{ shown.message }}</span>
    </button>

    <template #content>
      <div class="max-w-xs space-y-2 p-3 text-sm">
        <div class="flex items-center gap-1.5 text-caption text-muted">
          <UIcon
            :name="ICONS[shown.kind]"
            class="size-3.5"
          />
          {{ t(`announcements.kind.${shown.kind}`) }}
        </div>
        <p class="text-default">
          {{ shown.message }}
        </p>
        <p
          v-if="until"
          class="text-caption text-subtle"
        >
          {{ t('announcements.until', { date: until }) }}
        </p>
        <div class="flex justify-end">
          <UButton
            size="xs"
            color="neutral"
            variant="ghost"
            data-testid="workspace-announcement-dismiss"
            @click="dismiss(shown.id)"
          >
            {{ t('announcements.dismiss') }}
          </UButton>
        </div>
      </div>
    </template>
  </UPopover>
</template>
