<script setup lang="ts">
/**
 * The Data migration App's own page (Settings → Apps → Migración de
 * datos), opened from its card's "Configure" button: where a migration
 * is run. The App needs no other one to be enabled — what belongs to an
 * App that is off is left out and the preview says so (ADR 0037).
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import DataExportPanel from '../../../components/settings/DataExportPanel.vue'
import DataMigrationPage from '../../../components/settings/DataMigrationPage.vue'

const { t } = useI18n()
const { can } = usePermissions()
const canRead = computed(() => can(PERMISSIONS.migrationImport.jobRead))
const canExport = computed(() => can(PERMISSIONS.migrationImport.exportRun))

// Bringing data in, and taking it out in the same format.
const tabs = computed(() => [
  ...(canRead.value ? [{ label: t('migrationImport.tabs.import'), value: 'import', slot: 'import' as const, icon: 'i-lucide-database-zap' }] : []),
  ...(canExport.value ? [{ label: t('migrationImport.tabs.export'), value: 'export', slot: 'export' as const, icon: 'i-lucide-hard-drive-download' }] : [])
])
// The tabs appear once permissions load. Open the one asked for
// (`?tab=import|export`, from the App's card) or else the first.
const route = useRoute()
const active = ref<string>()
watchEffect(() => {
  if (tabs.value.some(tab => tab.value === active.value)) return
  const asked = typeof route.query.tab === 'string' ? route.query.tab : undefined
  active.value = tabs.value.find(tab => tab.value === asked)?.value ?? tabs.value[0]?.value
})
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

    <UTabs
      v-if="tabs.length"
      v-model="active"
      :items="tabs"
      class="w-full"
      data-testid="data-migration-tabs"
    >
      <template #import>
        <div class="mt-4">
          <DataMigrationPage />
        </div>
      </template>
      <template #export>
        <div class="mt-4">
          <DataExportPanel />
        </div>
      </template>
    </UTabs>
    <UAlert
      v-else
      color="neutral"
      variant="subtle"
      icon="i-lucide-lock"
      :title="t('common.forbidden')"
    />
  </div>
</template>
