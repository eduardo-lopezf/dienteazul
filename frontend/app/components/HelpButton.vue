<script setup lang="ts">
/**
 * Contextual help button for the app shell.
 *
 * Click → right-side slideover that iframes the matching help fragment
 * from the public documentation portal (`<docsUrl>/<lang>/help/<slug>.html`).
 * The fragment is rendered separately by VitePress' `buildEnd` hook
 * (see `docs/portal/.vitepress/help.ts`) and served by nginx with CORS
 * + frame-embedding allowed for the `/help/` path.
 *
 * The drawer is also where a user reports something that did not work
 * ("Reportar un error"): a short account in their own words, sent with
 * the route they were on and the build of the interface, to the
 * operator's control panel. It is the one witness there is when a screen
 * simply stays loading and the server never raised a thing.
 *
 * So the button is shown even when `NUXT_PUBLIC_DOCS_URL` is empty (dev,
 * or a deployment with no portal): the manual is missing then, not the
 * way to say something is broken.
 */
import { computed, ref } from 'vue'
import type { ApiResponse } from '~/types'

const { t } = useI18n()
const route = useRoute()
const api = useApi()
const toast = useToast()
const { helpUrl, fullManualUrl, isAvailable } = useHelp()

const open = ref(false)
const loadFailed = ref(false)
const loading = ref(true)

function onIframeLoad() {
  loading.value = false
}

function onIframeError() {
  loading.value = false
  loadFailed.value = true
}

function handleOpen(value: boolean) {
  open.value = value
  if (value) {
    loadFailed.value = false
    loading.value = true
  } else {
    reporting.value = false
  }
}

// --- Reporting a problem ---------------------------------------------------

const config = useRuntimeConfig()
const reporting = ref(false)
const description = ref('')
const sending = ref(false)

const MAX_DESCRIPTION = 2000

/** The route, without its query string: that is where an identifier
 *  would be, and the report has no business carrying one. */
const reportedPath = computed(() => route.path)
const canSend = computed(
  () => description.value.trim().length > 0 && description.value.length <= MAX_DESCRIPTION
)

async function send() {
  if (!canSend.value || sending.value) return
  sending.value = true
  try {
    await api.post<ApiResponse<{ id: string }>>('/api/v1/error-reports', {
      description: description.value.trim(),
      path: reportedPath.value,
      app_version: (config.public.appVersion as string) || ''
    })
    toast.add({ title: t('help.report.sent'), color: 'success' })
    description.value = ''
    reporting.value = false
  } catch {
    toast.add({ title: t('help.report.failed'), color: 'error' })
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <UButton
    variant="ghost"
    color="neutral"
    size="sm"
    icon="i-lucide-circle-help"
    :aria-label="t('help.openHelp', 'Open help')"
    @click="handleOpen(true)"
  >
    <span class="hidden sm:inline">{{ t('help.label', 'Help') }}</span>
  </UButton>

  <USlideover
    :open="open"
    side="right"
    :title="t('help.drawerTitle', 'Help for this page')"
    :ui="{ content: 'w-[480px] max-w-[95vw] bg-surface' }"
    @update:open="handleOpen"
  >
    <template #content>
      <div class="flex flex-col h-full">
        <header class="flex items-center justify-between px-4 h-14 border-b border-default">
          <div class="flex items-center gap-2 min-w-0">
            <UIcon
              :name="reporting ? 'i-lucide-bug' : 'i-lucide-circle-help'"
              class="w-4 h-4 text-subtle shrink-0"
            />
            <span class="text-h3 text-default truncate">
              {{ reporting ? t('help.report.title') : t('help.drawerTitle', 'Help for this page') }}
            </span>
          </div>
          <UButton
            variant="ghost"
            color="neutral"
            size="sm"
            icon="i-lucide-x"
            :aria-label="t('actions.close', 'Close')"
            @click="handleOpen(false)"
          />
        </header>

        <!-- Reporting replaces the manual in the drawer, rather than
             opening a second window over it. -->
        <form
          v-if="reporting"
          id="error-report"
          class="flex-1 min-h-0 overflow-y-auto p-4 space-y-3"
          @submit.prevent="send"
        >
          <p class="text-default">
            {{ t('help.report.intro') }}
          </p>
          <UFormField
            :label="t('help.report.label')"
            :help="t('help.report.noPatientData')"
          >
            <UTextarea
              v-model="description"
              :maxlength="MAX_DESCRIPTION"
              :rows="6"
              autoresize
              :placeholder="t('help.report.placeholder')"
              class="w-full"
              data-testid="error-report-description"
            />
          </UFormField>
          <p class="text-caption text-subtle">
            {{ t('help.report.context', { path: reportedPath }) }}
          </p>
        </form>

        <div
          v-else
          class="relative flex-1 min-h-0 overflow-hidden"
        >
          <div
            v-if="loading && isAvailable"
            class="absolute inset-0 flex items-center justify-center bg-surface"
          >
            <UIcon
              name="i-lucide-loader"
              class="w-6 h-6 text-muted animate-spin"
            />
          </div>

          <div
            v-if="loadFailed || !isAvailable"
            class="absolute inset-0 flex flex-col items-center justify-center text-center px-6 gap-2 bg-surface"
          >
            <UIcon
              name="i-lucide-circle-alert"
              class="w-6 h-6 text-warning"
            />
            <p class="text-default">
              {{ isAvailable
                ? t('help.unavailable', 'No contextual help available for this page yet.')
                : t('help.notConfigured') }}
            </p>
          </div>

          <iframe
            v-if="isAvailable"
            v-show="!loadFailed"
            :src="helpUrl"
            class="w-full h-full border-0"
            :title="t('help.drawerTitle', 'Help for this page')"
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            referrerpolicy="no-referrer"
            @load="onIframeLoad"
            @error="onIframeError"
          />
        </div>

        <footer class="flex items-center justify-between gap-2 px-4 h-12 border-t border-default">
          <template v-if="reporting">
            <UButton
              variant="ghost"
              color="neutral"
              size="sm"
              icon="i-lucide-arrow-left"
              @click="reporting = false"
            >
              {{ t('help.report.back') }}
            </UButton>
            <UButton
              type="submit"
              form="error-report"
              size="sm"
              :loading="sending"
              :disabled="!canSend"
              data-testid="error-report-send"
            >
              {{ t('help.report.send') }}
            </UButton>
          </template>
          <template v-else>
            <UButton
              variant="ghost"
              color="neutral"
              size="sm"
              icon="i-lucide-bug"
              data-testid="error-report-open"
              @click="reporting = true"
            >
              {{ t('help.report.open') }}
            </UButton>
            <UButton
              v-if="fullManualUrl"
              variant="link"
              color="primary"
              size="sm"
              icon="i-lucide-external-link"
              :to="fullManualUrl"
              target="_blank"
            >
              {{ t('help.openFullManual', 'Open full manual') }}
            </UButton>
          </template>
        </footer>
      </div>
    </template>
  </USlideover>
</template>
