<script setup lang="ts">
import { PERMISSIONS } from '~/config/permissions'

/**
 * The widgets each App contributes to other screens, each with a live
 * example built from made-up data (ADR 0040). Read-only: a widget is shown
 * wherever its App runs, and is not switched on or off here.
 */
const { t } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const admin = useModuleAdmin()

const canRead = computed(() => can(PERMISSIONS.admin.clinicRead))

// A widget is a slot registration that says so (`widget: true`). Its id
// starts with the module that registered it, which is how it finds its
// App. Grouped by App, in the catalog's order; an App with none is left out.
const groups = computed(() =>
  admin.apps.value
    .map(app => ({
      app: app.name,
      widgets: listSlotEntries()
        .filter(({ entry }) =>
          entry.widget && app.modules.some(module => entry.id.startsWith(`${module}.`))
        )
        .map(({ slot, entry }) => ({ slot, entry }))
    }))
    .filter(group => group.widgets.length > 0)
)

// Each App's widgets start folded; the chevron on its title opens them.
const expanded = ref(new Set<string>())

function toggle(app: string) {
  const next = new Set(expanded.value)
  if (next.has(app)) next.delete(app)
  else next.add(app)
  expanded.value = next
}

// What each host screen would hand a widget. Home widgets take nothing;
// a patient card takes its patient — a made-up one here, like the rest
// of the example.
const SAMPLE_PATIENT = { id: 'preview-patient-1', first_name: 'Laura', last_name: 'Demo' }

function exampleCtx(slot: string): unknown {
  return slot.startsWith('patient.') ? { patient: SAMPLE_PATIENT } : {}
}

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
        {{ t('settings.widgets.title') }}
      </h1>
      <p class="text-muted mt-1">
        {{ t('settings.widgets.intro') }}
      </p>
    </div>

    <div
      v-if="!canRead"
      class="rounded-md border border-default p-6 text-sm text-muted"
    >
      {{ t('common.forbidden', 'Acceso denegado') }}
    </div>

    <template v-else>
      <div
        v-if="!loaded && !admin.error.value"
        class="space-y-3"
      >
        <USkeleton class="h-40 w-full" />
        <USkeleton class="h-40 w-full" />
      </div>

      <UAlert
        v-else-if="admin.error.value && admin.apps.value.length === 0"
        color="error"
        icon="i-lucide-x-circle"
        :title="t('common.error')"
        :description="admin.error.value"
        :actions="[{ label: t('common.retry'), onClick: () => admin.refreshApps() }]"
      />

      <!-- Client-only: registrations come from each layer's
           `slots.client.ts`, which does not run during SSR. -->
      <ClientOnly v-else>
        <div class="space-y-8">
          <section
            v-for="group in groups"
            :key="group.app"
            :data-testid="`widget-group-${group.app}`"
            class="space-y-3"
          >
            <h2 class="text-h2 text-default">
              <button
                type="button"
                data-testid="widget-group-title"
                class="flex items-center gap-2 text-left"
                :aria-expanded="expanded.has(group.app)"
                :aria-label="expanded.has(group.app) ? t('common.collapse') : t('common.expand')"
                @click="toggle(group.app)"
              >
                <UIcon
                  :name="expanded.has(group.app) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                  class="size-5 text-muted"
                />
                {{ admin.appTitle(group.app) }}
                <span class="text-sm font-normal text-muted">· {{ group.widgets.length }}</span>
              </button>
            </h2>
            <WidgetCard
              v-for="widget in expanded.has(group.app) ? group.widgets : []"
              :key="widget.entry.id"
              :slot-name="widget.slot"
              :entry="widget.entry"
              :ctx="exampleCtx(widget.slot)"
            />
          </section>
          <p
            v-if="groups.length === 0"
            class="text-sm text-muted"
          >
            {{ t('settings.widgets.empty') }}
          </p>
        </div>
      </ClientOnly>
    </template>
  </div>
</template>
