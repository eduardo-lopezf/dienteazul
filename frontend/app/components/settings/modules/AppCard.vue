<script setup lang="ts">
import type { AppInfo } from '~/types'
import { appPresentation } from '~/config/appCatalog'
import { PERMISSIONS } from '~/config/permissions'

interface Props {
  app: AppInfo
}

const props = defineProps<Props>()
const emit = defineEmits<{ enable: [name: string] }>()
const { t, te } = useI18n()
const { can } = usePermissions()

// Catalog names are code; the clinic-facing title and summary live in
// i18n. An App without strings yet falls back to its name.
const title = computed(() => {
  const key = `settings.apps.catalog.${props.app.name}.title`
  return te(key) ? t(key) : props.app.name
})
// The icon that stands for the App, and its own settings page when it has
// one. A disabled App offers no page: its routes are turned away.
const presentation = computed(() => appPresentation(props.app.name))
const settingsPath = computed(() => props.app.enabled ? presentation.value.settingsPath : undefined)

const summary = computed(() => {
  const key = `settings.apps.catalog.${props.app.name}.summary`
  return te(key) ? t(key) : ''
})
</script>

<template>
  <UCard :data-testid="`app-card-${app.name}`">
    <div class="flex items-center gap-2 flex-wrap">
      <span
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        :class="app.enabled ? 'bg-[var(--ui-primary)]/10 text-[var(--ui-primary)]' : 'bg-elevated text-subtle'"
        aria-hidden="true"
      >
        <UIcon
          :name="presentation.icon"
          class="h-5 w-5"
          :data-testid="`app-icon-${app.name}`"
        />
      </span>
      <h3 class="font-semibold text-default">
        {{ title }}
      </h3>
      <span class="text-caption text-subtle">v{{ app.version }}</span>
      <UBadge
        :color="app.tier === 'base' ? 'primary' : 'neutral'"
        :variant="app.tier === 'optional' ? 'outline' : 'subtle'"
        size="xs"
        :data-testid="`app-tier-${app.name}`"
      >
        {{ t(`settings.apps.tier.${app.tier}`) }}
      </UBadge>
      <UButton
        v-if="settingsPath"
        :to="settingsPath"
        size="xs"
        variant="soft"
        icon="i-lucide-settings-2"
        class="ml-auto"
        :data-testid="`app-configure-${app.name}`"
      >
        {{ t('settings.apps.configure') }}
      </UButton>
    </div>

    <p
      v-if="summary"
      class="mt-1 text-sm text-muted"
    >
      {{ summary }}
    </p>

    <div class="mt-3 flex items-center gap-3 flex-wrap">
      <StatusBadge
        :role="app.enabled ? 'success' : 'neutral'"
        :label="t(app.enabled ? 'settings.modules.state.installed' : 'settings.modules.state.disabled')"
        dot
      />
      <!-- Offered to this clinic and not switched on yet. -->
      <UButton
        v-if="app.available && can(PERMISSIONS.admin.clinicWrite)"
        size="xs"
        icon="i-lucide-power"
        :data-testid="`app-enable-${app.name}`"
        @click="emit('enable', app.name)"
      >
        {{ t('settings.apps.enable') }}
      </UButton>
      <UBadge
        v-else-if="app.available"
        color="info"
        variant="subtle"
        size="xs"
      >
        {{ t('settings.apps.available') }}
      </UBadge>
      <!-- `apps.json` was edited and the backend has not restarted yet. -->
      <UBadge
        v-if="app.pending_enabled !== null && app.pending_enabled !== undefined"
        color="warning"
        variant="subtle"
        size="xs"
        icon="i-lucide-refresh-cw"
        :data-testid="`app-pending-${app.name}`"
      >
        {{ t(app.pending_enabled ? 'settings.apps.pendingEnable' : 'settings.apps.pendingDisable') }}
      </UBadge>
      <!-- Off because an App it cannot run without is off (ADR 0053). -->
      <UBadge
        v-if="app.held_back_by"
        color="neutral"
        variant="subtle"
        size="xs"
        icon="i-lucide-link-2-off"
        :data-testid="`app-held-back-${app.name}`"
      >
        {{ t('settings.apps.heldBackBy', { name: t(`settings.apps.catalog.${app.held_back_by}.title`) }) }}
      </UBadge>
      <!-- The base App groups no modules: it is the core and the shell. -->
      <span
        v-if="app.tier === 'base'"
        class="text-caption text-subtle"
      >
        {{ t('settings.apps.alwaysOn') }}
      </span>
      <span
        v-if="app.modules.length > 0"
        class="text-caption text-subtle"
      >
        {{ t('settings.apps.includes') }}:
        <code
          v-for="(name, idx) in app.modules"
          :key="name"
          class="ml-1"
        >{{ name }}{{ idx < app.modules.length - 1 ? ',' : '' }}</code>
      </span>
      <span
        v-if="app.requires.length > 0"
        class="text-caption text-subtle"
      >
        {{ t('settings.apps.requires') }}:
        <code
          v-for="(name, idx) in app.requires"
          :key="name"
          class="ml-1"
        >{{ name }}{{ idx < app.requires.length - 1 ? ',' : '' }}</code>
      </span>
      <span
        v-if="app.integrates.length > 0"
        class="text-caption text-subtle"
      >
        {{ t('settings.apps.integrates') }}:
        <code
          v-for="(name, idx) in app.integrates"
          :key="name"
          class="ml-1"
        >{{ name }}{{ idx < app.integrates.length - 1 ? ',' : '' }}</code>
      </span>
    </div>
  </UCard>
</template>
