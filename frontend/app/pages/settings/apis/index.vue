<script setup lang="ts">
import { PERMISSIONS } from '~/config/permissions'

/**
 * The outside services each App can connect to, as `backend/apps.json`
 * declares them (ADR 0040). Read-only: the switch lives in that file, and
 * credentials never do.
 */
const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const admin = useModuleAdmin()

const canRead = computed(() => can(PERMISSIONS.admin.clinicRead))

const apis = computed(() =>
  admin.apps.value.flatMap(app => app.apis.map(item => ({ api: item, app: app.name })))
)

// Until the catalog has been read once, the page says nothing about it:
// the server renders before any request, and "nothing to show" would be
// a claim it cannot make.
const loaded = ref(false)

async function load() {
  try {
    await admin.refreshApps()
    loaded.value = true
  } catch (err: unknown) {
    const e = err as { data?: { detail?: string }, message?: string }
    toast.add({
      title: t('common.error'),
      description: e?.data?.detail ?? e?.message ?? t('common.networkError'),
      color: 'error'
    })
  }
}

// Client-side, from setup, and as soon as the permission is known: on a
// first full load `onMounted` could run before the session was restored
// and never load at all, leaving the page showing an empty list.
watch(canRead, (ok) => {
  if (ok && import.meta.client) load()
}, { immediate: true })
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <UButton
        to="/settings"
        variant="ghost"
        size="sm"
        icon="i-lucide-arrow-left"
      >
        {{ t('settings.title') }}
      </UButton>
    </div>

    <div>
      <h1 class="text-display text-default">
        {{ t('settings.apis.title') }}
      </h1>
      <p class="text-muted mt-1">
        {{ t('settings.apis.intro') }}
      </p>
    </div>

    <div
      v-if="!canRead"
      class="rounded-md border border-default p-6 text-sm text-muted"
    >
      {{ t('common.forbidden', 'Acceso denegado') }}
    </div>

    <template v-else>
      <!--
        What an App puts on this page itself. The declared list below says
        which outside services exist; a module that already has something
        to configure registers it here (ADR 0041), and it disappears with
        its App.
      -->
      <ModuleSlot
        name="settings.apis.sections"
        :ctx="{}"
      />

      <div
        v-if="!loaded && !admin.error.value"
        class="space-y-3"
      >
        <USkeleton class="h-20 w-full" />
      </div>

      <UAlert
        v-else-if="admin.error.value && admin.apps.value.length === 0"
        color="error"
        icon="i-lucide-x-circle"
        :title="t('common.error')"
        :description="admin.error.value"
        :actions="[{ label: t('common.retry'), onClick: () => admin.refreshApps() }]"
      />

      <div
        v-else
        class="space-y-3"
      >
        <ApiCard
          v-for="item in apis"
          :key="`${item.app}.${item.api.name}`"
          :api="item.api"
          :app-title="admin.appTitle(item.app)"
        />
        <p
          v-if="apis.length === 0"
          class="text-sm text-muted"
        >
          {{ t('settings.apis.empty') }}
        </p>
      </div>
    </template>
  </div>
</template>
