<script setup lang="ts">
/**
 * The two ways out of the agenda, in its bottom-right corner: Google
 * Calendar and Apple Calendar (ADR 0061).
 *
 * Rendered into the agenda's ``agenda.calendar.subscribe`` slot, so the
 * agenda page knows nothing about this module (ADR 0041). Neither button
 * subscribes anything by itself — no browser can — they explain where the
 * URL comes from and what to do with it on each device.
 *
 * The URL is shown only when the user already has one. Reading it never
 * creates it: minting a credential is a decision taken on purpose, on the
 * APIs screen, which is where both modals point.
 */
import type { ApiResponse } from '~~/app/types'

interface CalendarFeed {
  token: string
  path: string
  scope: 'own' | 'clinic'
  last_access_at: string | null
  created_at: string
}

type Target = 'google' | 'apple'

const { t } = useI18n()
const api = useApi()
const toast = useToast()

const open = ref(false)
const target = ref<Target>('google')
const feed = ref<CalendarFeed | null>(null)
const loaded = ref(false)

// Absolute only in the browser: the server render has no origin to build
// it from. This is also what makes it right in both places without a
// setting — ``localhost:3000`` while developing, the clinic's domain in
// production, because it is the origin the user is already looking at.
const url = computed(() => {
  if (!feed.value || !import.meta.client) return ''
  return `${window.location.origin}${feed.value.path}`
})

// Named rather than an array, so a translator sees what each step is
// about and the two paths can differ in length without renumbering.
//
// One button, one family: the Google route stops at the Android phone
// and the Apple route at the iPhone. Each path is short enough to follow
// without deciding first which half of it applies.
const STEPS: Record<Target, readonly string[]> = {
  google: ['copy', 'web', 'android', 'show'],
  apple: ['copy', 'iphone', 'mac']
}

const steps = computed(() =>
  STEPS[target.value].map(name => t(`calendarFeed.subscribe.${target.value}.steps.${name}`))
)

async function show(which: Target) {
  target.value = which
  open.value = true
  if (loaded.value) return
  try {
    const response = await api.get<ApiResponse<CalendarFeed | null>>(
      '/api/v1/calendar_feed/subscription'
    )
    feed.value = response.data
  } catch {
    // The steps are worth reading with or without a URL in hand, so a
    // failed read leaves the modal standing rather than closing it.
    feed.value = null
  } finally {
    loaded.value = true
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(url.value)
    toast.add({ title: t('calendarFeed.copied'), color: 'success' })
  } catch {
    toast.add({ title: t('calendarFeed.copyFailed'), color: 'warning' })
  }
}
</script>

<template>
  <div class="flex gap-2">
    <UButton
      icon="i-lucide-globe"
      color="neutral"
      variant="subtle"
      size="sm"
      :aria-label="t('calendarFeed.subscribe.google.button')"
      @click="show('google')"
    >
      <span class="hidden sm:inline">{{ t('calendarFeed.subscribe.google.button') }}</span>
    </UButton>
    <UButton
      icon="i-lucide-smartphone"
      color="neutral"
      variant="subtle"
      size="sm"
      :aria-label="t('calendarFeed.subscribe.apple.button')"
      @click="show('apple')"
    >
      <span class="hidden sm:inline">{{ t('calendarFeed.subscribe.apple.button') }}</span>
    </UButton>

    <UModal
      v-model:open="open"
      :title="t(`calendarFeed.subscribe.${target}.title`)"
      :description="t(`calendarFeed.subscribe.${target}.intro`)"
    >
      <template #body>
        <div class="space-y-4">
          <UAlert
            color="neutral"
            variant="subtle"
            icon="i-lucide-arrow-right"
            :description="t('calendarFeed.oneWay')"
          />

          <!-- With a URL in hand the first step is done; without one the
               only thing that matters is where to go and get it. -->
          <UFormField
            v-if="feed"
            :label="t('calendarFeed.urlLabel')"
            :help="feed.scope === 'own' ? t('calendarFeed.scopeOwn') : t('calendarFeed.scopeClinic')"
          >
            <div class="flex flex-col gap-2 sm:flex-row">
              <UInput
                :model-value="url"
                readonly
                class="flex-1 font-mono text-xs"
                :aria-label="t('calendarFeed.urlLabel')"
              />
              <UButton
                icon="i-lucide-copy"
                variant="subtle"
                :aria-label="t('calendarFeed.copy')"
                @click="copy"
              >
                <span class="hidden sm:inline">{{ t('calendarFeed.copy') }}</span>
              </UButton>
            </div>
          </UFormField>

          <UAlert
            v-else-if="loaded"
            color="info"
            variant="subtle"
            icon="i-lucide-info"
            :description="t('calendarFeed.subscribe.noUrl')"
          />

          <ol class="text-sm text-default list-decimal ml-5 space-y-2">
            <li
              v-for="(step, index) in steps"
              :key="index"
            >
              {{ step }}
            </li>
          </ol>

          <p class="text-sm text-muted">
            {{ t(`calendarFeed.subscribe.${target}.caveat`) }}
          </p>
        </div>
      </template>

      <template #footer>
        <div class="flex flex-wrap gap-2">
          <UButton
            to="/settings/apis"
            icon="i-lucide-settings"
            variant="subtle"
            @click="open = false"
          >
            {{ t('calendarFeed.subscribe.goToSettings') }}
          </UButton>
          <UButton
            variant="ghost"
            color="neutral"
            @click="open = false"
          >
            {{ t('common.close') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
