<script setup lang="ts">
/**
 * The user's own agenda as a calendar subscription (ADR 0061).
 *
 * Rendered into the host's ``settings.apis.sections`` slot. The URL is
 * the whole credential, so the card treats it like one: hidden until
 * asked for, copied in one click, and rotating says in advance that the
 * subscriptions already pasted elsewhere will stop resolving.
 */
import type { ApiResponse } from '~~/app/types'

interface CalendarFeed {
  token: string
  path: string
  scope: 'own' | 'clinic'
  last_access_at: string | null
  created_at: string
}

const { t, locale } = useI18n()
const api = useApi()
const toast = useToast()

const feed = ref<CalendarFeed | null>(null)
const loading = ref(false)
const revealed = ref(false)
const confirmingRotate = ref(false)

// Absolute only in the browser: the server render has no origin to build
// it from, and half a URL is worse than none.
const url = computed(() => {
  if (!feed.value || !import.meta.client) return ''
  return `${window.location.origin}${feed.value.path}`
})

const lastAccess = computed(() => {
  const at = feed.value?.last_access_at
  if (!at) return null
  return new Date(at).toLocaleString(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
})

function failed(err: unknown) {
  const e = err as { data?: { message?: string }, message?: string }
  toast.add({
    title: t('common.error'),
    description: e?.data?.message ?? e?.message ?? t('common.networkError'),
    color: 'error'
  })
}

async function load() {
  loading.value = true
  try {
    const response = await api.get<ApiResponse<CalendarFeed | null>>(
      '/api/v1/calendar_feed/subscription'
    )
    feed.value = response.data
  } catch (err: unknown) {
    failed(err)
  } finally {
    loading.value = false
  }
}

async function issue() {
  loading.value = true
  try {
    const response = await api.post<ApiResponse<CalendarFeed>>('/api/v1/calendar_feed/subscription')
    feed.value = response.data
    revealed.value = true
    confirmingRotate.value = false
  } catch (err: unknown) {
    failed(err)
  } finally {
    loading.value = false
  }
}

async function revoke() {
  loading.value = true
  try {
    await api.del('/api/v1/calendar_feed/subscription')
    feed.value = null
    revealed.value = false
  } catch (err: unknown) {
    failed(err)
  } finally {
    loading.value = false
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(url.value)
    toast.add({ title: t('calendarFeed.copied'), color: 'success' })
  } catch {
    // A clipboard the browser refuses is why the field stays selectable.
    revealed.value = true
  }
}

onMounted(load)
</script>

<template>
  <UCard>
    <template #header>
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold text-default">
            {{ t('calendarFeed.title') }}
          </h2>
          <p class="text-sm text-muted mt-1">
            {{ t('calendarFeed.intro') }}
          </p>
        </div>
        <UIcon
          name="i-lucide-calendar-sync"
          class="size-5 text-muted shrink-0"
        />
      </div>
    </template>

    <div class="space-y-4">
      <UAlert
        v-if="feed"
        color="neutral"
        variant="subtle"
        icon="i-lucide-arrow-right"
        :description="t('calendarFeed.oneWay')"
      />

      <template v-if="feed">
        <UFormField
          :label="t('calendarFeed.urlLabel')"
          :help="feed.scope === 'own' ? t('calendarFeed.scopeOwn') : t('calendarFeed.scopeClinic')"
        >
          <div class="flex flex-col gap-2 sm:flex-row">
            <UInput
              :model-value="revealed ? url : '•'.repeat(48)"
              readonly
              class="flex-1 font-mono text-xs"
              :aria-label="t('calendarFeed.urlLabel')"
              @focus="revealed = true"
            />
            <div class="flex gap-2">
              <UButton
                :icon="revealed ? 'i-lucide-eye-off' : 'i-lucide-eye'"
                variant="subtle"
                :aria-label="revealed ? t('calendarFeed.hide') : t('calendarFeed.reveal')"
                @click="revealed = !revealed"
              />
              <UButton
                icon="i-lucide-copy"
                variant="subtle"
                :aria-label="t('calendarFeed.copy')"
                @click="copy"
              />
            </div>
          </div>
        </UFormField>

        <p class="text-sm text-muted">
          {{ lastAccess
            ? t('calendarFeed.lastAccess', { at: lastAccess })
            : t('calendarFeed.neverAccessed') }}
        </p>

        <ol class="text-sm text-muted list-decimal ml-5 space-y-1">
          <li>{{ t('calendarFeed.howTo.copy') }}</li>
          <li>{{ t('calendarFeed.howTo.google') }}</li>
          <li>{{ t('calendarFeed.howTo.wait') }}</li>
        </ol>

        <UAlert
          v-if="confirmingRotate"
          color="warning"
          variant="subtle"
          icon="i-lucide-triangle-alert"
          :description="t('calendarFeed.rotateWarning')"
          :actions="[
            { label: t('calendarFeed.rotateConfirm'), color: 'warning', onClick: issue },
            {
              label: t('common.cancel'),
              variant: 'ghost',
              onClick: () => (confirmingRotate = false)
            }
          ]"
        />
      </template>

      <p
        v-else-if="!loading"
        class="text-sm text-muted"
      >
        {{ t('calendarFeed.none') }}
      </p>
    </div>

    <template #footer>
      <div class="flex flex-wrap gap-2">
        <UButton
          v-if="!feed"
          icon="i-lucide-link"
          :loading="loading"
          @click="issue"
        >
          {{ t('calendarFeed.create') }}
        </UButton>
        <template v-else>
          <UButton
            variant="subtle"
            icon="i-lucide-refresh-cw"
            :loading="loading"
            @click="confirmingRotate = true"
          >
            {{ t('calendarFeed.rotate') }}
          </UButton>
          <UButton
            variant="ghost"
            color="error"
            icon="i-lucide-trash-2"
            :loading="loading"
            @click="revoke"
          >
            {{ t('calendarFeed.revoke') }}
          </UButton>
        </template>
      </div>
    </template>
  </UCard>
</template>
