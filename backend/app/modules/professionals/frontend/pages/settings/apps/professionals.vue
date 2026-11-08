<script setup lang="ts">
/**
 * The Professionals App's own settings page (Settings → Apps →
 * Profesionales → Configurar): the modules it is made of.
 *
 * Those the App needs to run — its own and what they depend on — are
 * shown on and locked. Its optional modules (`optional_modules` in
 * `apps.json`, ADR 0066) are the clinic's to switch: off until then,
 * and only for the account tiers the catalog names.
 */
import type { AppInfo } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'

const APP = 'professionals'

const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const admin = useModuleAdmin()

const canRead = computed(() => can(PERMISSIONS.admin.clinicRead))
const canWrite = computed(() => can(PERMISSIONS.admin.clinicWrite))

const loaded = ref(false)
const busy = ref<string | null>(null)

const app = computed<AppInfo | undefined>(() => admin.apps.value.find(a => a.name === APP))

interface Row {
  name: string
  summary: string
  optional: boolean
  on: boolean
  locked: boolean
  clinicOnly: boolean
}

// The App's own modules first, then the ones they cannot run without.
const rows = computed<Row[]>(() => {
  const current = app.value
  if (!current) return []
  return [...current.modules, ...current.requires].map((name) => {
    const optional = current.optional_modules.find(m => m.name === name)
    const summary = admin.modules.value.find(m => m.name === name)?.summary ?? ''
    if (!optional) {
      return { name, summary, optional: false, on: true, locked: true, clinicOnly: false }
    }
    return {
      name,
      summary,
      optional: true,
      on: optional.enabled,
      locked: !canWrite.value || !optional.available,
      clinicOnly: !optional.available
    }
  })
})

async function load() {
  try {
    await admin.refresh()
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loaded.value = true
  }
}

watch(canRead, (ok) => {
  if (ok && import.meta.client) load()
}, { immediate: true })

async function toggle(row: Row, on: boolean) {
  busy.value = row.name
  try {
    await admin.setOptionalModule(APP, row.name, on)
    toast.add({
      title: t(on ? 'professionals.appSettings.switchedOn' : 'professionals.appSettings.switchedOff', { name: row.name }),
      color: 'success'
    })
  } catch (err: unknown) {
    const e = err as { data?: { message?: string, detail?: string }, message?: string }
    toast.add({
      title: t('common.error'),
      description: e?.data?.message ?? e?.data?.detail ?? e?.message ?? t('common.networkError'),
      color: 'error'
    })
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-center gap-3">
      <UButton
        to="/settings/apps"
        variant="ghost"
        size="sm"
        icon="i-lucide-arrow-left"
      >
        {{ t('settings.categories.modules.label') }}
      </UButton>
    </div>

    <div>
      <h1 class="text-display text-default flex items-center gap-2">
        <UIcon
          name="i-lucide-stethoscope"
          class="h-6 w-6 text-[var(--ui-primary)]"
        />
        {{ t('settings.apps.catalog.professionals.title') }}
      </h1>
      <p class="text-muted mt-1">
        {{ t('professionals.appSettings.intro') }}
      </p>
    </div>

    <div
      v-if="!canRead"
      class="rounded-md border border-default p-6 text-sm text-muted"
    >
      {{ t('common.forbidden', 'Acceso denegado') }}
    </div>

    <ClientOnly v-else>
      <div
        v-if="!loaded"
        class="space-y-3"
      >
        <USkeleton
          v-for="i in 5"
          :key="i"
          class="h-16 w-full"
        />
      </div>

      <ul
        v-else
        class="space-y-3"
        data-testid="app-modules"
      >
        <li
          v-for="row in rows"
          :key="row.name"
          class="flex items-start gap-3 rounded-[var(--radius-lg)] p-4 ring-1 ring-[var(--color-border)]"
          :class="row.optional && !row.clinicOnly ? 'bg-surface' : 'bg-elevated'"
          :data-testid="`app-module-${row.name}`"
        >
          <USwitch
            :model-value="row.on"
            color="success"
            :disabled="row.locked || busy === row.name"
            :aria-label="row.name"
            class="mt-0.5"
            :data-testid="`app-module-switch-${row.name}`"
            @update:model-value="(on: boolean) => toggle(row, on)"
          />
          <div class="min-w-0 flex-1">
            <p class="flex items-center gap-2 flex-wrap">
              <code class="font-medium text-default">{{ row.name }}</code>
              <UBadge
                v-if="row.optional"
                color="neutral"
                variant="outline"
                size="xs"
              >
                {{ t('professionals.appSettings.optional') }}
              </UBadge>
            </p>
            <p
              v-if="row.summary"
              class="text-sm text-muted mt-0.5"
            >
              {{ row.summary }}
            </p>
            <p
              v-if="!row.optional"
              class="text-caption text-subtle mt-1"
            >
              {{ t('professionals.appSettings.required') }}
            </p>
            <p
              v-else-if="row.clinicOnly"
              class="text-caption text-subtle mt-1"
            >
              {{ t('professionals.appSettings.clinicOnly') }}
            </p>
            <p
              v-else
              class="text-caption text-subtle mt-1"
            >
              {{ t('professionals.appSettings.keepsData') }}
            </p>
          </div>
        </li>
      </ul>
    </ClientOnly>
  </div>
</template>
