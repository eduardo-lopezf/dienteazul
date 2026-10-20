<script setup lang="ts">
/**
 * The Treatments App's own settings page (Settings → Apps → Tratamientos):
 * the specialties the clinic works with.
 *
 * Each discipline comes with a reference catalogue — its treatments and
 * its plan templates. Enabling one adds it to the clinic's catalogue;
 * from there it is the clinic's to edit. Disabling takes it out without
 * deleting anything. Restoring puts its reference treatments back to the
 * reference, and overwrites what the clinic changed on them — so it asks
 * first, and says how many.
 */
import { PERMISSIONS } from '~~/app/config/permissions'
import type { PackTreatment, SpecialtyPack, SpecialtyPackDetail } from '../../../composables/useSpecialtyPacks'

const { t, locale } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const packsApi = useSpecialtyPacks()
const { format: formatMoney } = useCurrency()

const canRead = computed(() => can(PERMISSIONS.catalog.read))
const canWrite = computed(() => can(PERMISSIONS.catalog.admin))

const packs = ref<SpecialtyPack[]>([])
const loaded = ref(false)
const busy = ref<string | null>(null)
const restoring = ref<SpecialtyPack | null>(null)

// One discipline open at a time: its reference treatments, by sub-area.
const openKey = ref<string | null>(null)
const opened = ref<SpecialtyPackDetail | null>(null)
const opening = ref(false)

async function showTreatments(pack: SpecialtyPack) {
  if (openKey.value === pack.key) {
    openKey.value = null
    opened.value = null
    return
  }
  openKey.value = pack.key
  opened.value = null
  opening.value = true
  try {
    opened.value = await packsApi.detail(pack.key)
  } catch {
    openKey.value = null
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    opening.value = false
  }
}

function localized(names: Record<string, string>): string {
  return names[locale.value] || names.es || ''
}

function price(treatment: PackTreatment): string {
  const shown = treatment.clinic_price ?? treatment.reference_price
  return shown === null ? '' : formatMoney(Number(shown))
}

const enabled = computed(() => packs.value.filter(pack => pack.enabled))
const available = computed(() => packs.value.filter(pack => !pack.enabled))

function name(pack: SpecialtyPack): string {
  return pack.names[locale.value] || pack.names.es || pack.key
}

async function load() {
  try {
    packs.value = await packsApi.list()
  } catch {
    toast.add({ title: t('errors.loadFailed'), color: 'error' })
  } finally {
    loaded.value = true
  }
}

async function run(pack: SpecialtyPack, action: 'enable' | 'disable' | 'restore') {
  busy.value = pack.key
  try {
    const next = await packsApi.act(pack.key, action)
    packs.value = packs.value.map(item => item.key === next.key ? next : item)
    // What is open shows the clinic's catalogue: read it again.
    if (openKey.value === next.key) opened.value = await packsApi.detail(next.key)
    toast.add({ title: t(`catalog.packs.done.${action}`, { name: name(next) }), color: 'success' })
  } catch (error: unknown) {
    const e = error as { data?: { detail?: string } }
    toast.add({ title: t('errors.updateFailed'), description: e?.data?.detail, color: 'error' })
  } finally {
    busy.value = null
  }
}

function toggle(pack: SpecialtyPack, on: boolean) {
  run(pack, on ? 'enable' : 'disable')
}

async function confirmRestore() {
  const pack = restoring.value
  restoring.value = null
  if (pack) await run(pack, 'restore')
}

// Client-side, from setup, and as soon as the permission is known.
watch(canRead, (ok) => {
  if (ok && import.meta.client) load()
}, { immediate: true })
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
          name="i-lucide-clipboard-list"
          class="h-6 w-6 text-[var(--ui-primary)]"
        />
        {{ t('settings.apps.catalog.treatments.title') }}
      </h1>
      <p class="text-muted mt-1">
        {{ t('catalog.packs.intro') }}
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
          v-for="i in 4"
          :key="i"
          class="h-20 w-full"
        />
      </div>

      <div
        v-else
        class="space-y-8"
      >
        <section
          v-for="group in [
            { id: 'enabled', title: t('catalog.packs.enabled'), items: enabled },
            { id: 'available', title: t('catalog.packs.available'), items: available }
          ]"
          :key="group.id"
          :data-testid="`specialty-packs-${group.id}`"
        >
          <h2 class="text-h3 text-default mb-3">
            {{ group.title }}
            <span class="text-caption text-subtle font-normal">{{ group.items.length }}</span>
          </h2>
          <p
            v-if="group.items.length === 0"
            class="text-sm text-subtle"
          >
            {{ t(`catalog.packs.none.${group.id}`) }}
          </p>
          <ul
            v-else
            class="grid grid-cols-1 lg:grid-cols-2 gap-3"
          >
            <li
              v-for="pack in group.items"
              :key="pack.key"
              class="rounded-[var(--radius-lg)] bg-surface p-4 ring-1 ring-[var(--color-border)]"
              :class="{ 'lg:col-span-2': openKey === pack.key }"
              :data-testid="`specialty-pack-${pack.key}`"
            >
              <div class="flex items-start gap-3 flex-wrap">
                <USwitch
                  :model-value="pack.enabled"
                  :disabled="!canWrite || busy === pack.key"
                  :aria-label="name(pack)"
                  class="mt-0.5"
                  @update:model-value="(on: boolean) => toggle(pack, on)"
                />
                <div class="min-w-48 flex-1">
                  <p class="font-medium text-default">
                    {{ name(pack) }}
                  </p>
                  <p class="text-caption text-muted">
                    <template v-if="pack.enabled">
                      {{ t('catalog.packs.installed', { installed: pack.installed_count, total: pack.reference_count }) }}
                      <span
                        v-if="pack.customised_count"
                        :data-testid="`specialty-pack-customised-${pack.key}`"
                      > · {{ t('catalog.packs.customised', { count: pack.customised_count }) }}</span>
                    </template>
                    <template v-else>
                      {{ t('catalog.packs.reference', { total: pack.reference_count }) }}
                    </template>
                  </p>
                </div>
                <!-- Kept together, so they drop under the name as a row
                     when the card is narrow. -->
                <div class="flex flex-wrap items-center gap-1 ml-auto">
                  <!-- The reference grew since the clinic enabled it: add the new
                   ones without touching what the clinic has. -->
                  <UButton
                    v-if="canWrite && pack.enabled && pack.missing_count > 0"
                    size="xs"
                    variant="soft"
                    icon="i-lucide-plus"
                    :loading="busy === pack.key"
                    :data-testid="`specialty-pack-complete-${pack.key}`"
                    @click="run(pack, 'enable')"
                  >
                    {{ t('catalog.packs.complete', { count: pack.missing_count }) }}
                  </UButton>
                  <UButton
                    v-if="canWrite && pack.enabled"
                    size="xs"
                    color="neutral"
                    variant="ghost"
                    icon="i-lucide-rotate-ccw"
                    :loading="busy === pack.key"
                    :data-testid="`specialty-pack-restore-${pack.key}`"
                    @click="restoring = pack"
                  >
                    {{ t('catalog.packs.restore') }}
                  </UButton>
                  <UButton
                    size="xs"
                    color="neutral"
                    variant="ghost"
                    :icon="openKey === pack.key ? 'i-lucide-chevron-up' : 'i-lucide-chevron-down'"
                    :aria-expanded="openKey === pack.key"
                    :data-testid="`specialty-pack-open-${pack.key}`"
                    @click="showTreatments(pack)"
                  >
                    {{ t('catalog.packs.treatments') }}
                  </UButton>
                </div>
              </div>

              <!-- The reference catalogue of the discipline, by sub-area. -->
              <div
                v-if="openKey === pack.key"
                class="mt-4 border-t border-default pt-4"
                :data-testid="`specialty-pack-detail-${pack.key}`"
              >
                <div
                  v-if="opening || !opened"
                  class="space-y-2"
                >
                  <USkeleton
                    v-for="i in 3"
                    :key="i"
                    class="h-10 w-full"
                  />
                </div>
                <div
                  v-else
                  class="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5"
                >
                  <section
                    v-for="block in [
                      ...opened.subareas.map(sub => ({ id: sub.key, title: localized(sub.names), treatments: sub.treatments, shared: false })),
                      ...opened.shared.map(other => ({ id: `shared-${other.specialty_key}`, title: t('catalog.packs.sharedWith', { name: localized(other.names) }), treatments: other.treatments, shared: true }))
                    ]"
                    :key="block.id"
                    :data-testid="`specialty-subarea-${block.id}`"
                  >
                    <h3
                      class="text-caption font-medium uppercase tracking-wide mb-1.5"
                      :class="block.shared ? 'text-subtle' : 'text-muted'"
                    >
                      {{ block.title }}
                      <span class="font-normal">{{ block.treatments.length }}</span>
                    </h3>
                    <ul class="divide-y divide-[var(--color-border-subtle)]">
                      <li
                        v-for="treatment in block.treatments"
                        :key="treatment.code"
                        class="flex items-baseline gap-2 py-1.5 text-sm"
                      >
                        <span
                          class="min-w-0 flex-1 truncate"
                          :class="treatment.state === 'active' ? 'text-default' : 'text-subtle'"
                        >{{ localized(treatment.names) }}</span>
                        <UBadge
                          v-if="treatment.customised"
                          color="primary"
                          variant="subtle"
                          size="xs"
                        >
                          {{ t('catalog.packs.badge.customised') }}
                        </UBadge>
                        <UBadge
                          v-else-if="pack.enabled && treatment.state !== 'active'"
                          color="neutral"
                          variant="subtle"
                          size="xs"
                        >
                          {{ t(`catalog.packs.badge.${treatment.state}`) }}
                        </UBadge>
                        <span class="text-caption text-muted tabular-nums shrink-0">{{ price(treatment) }}</span>
                      </li>
                    </ul>
                  </section>
                </div>
              </div>
            </li>
          </ul>
        </section>

        <p class="text-caption text-subtle">
          {{ t('catalog.packs.note') }}
        </p>
      </div>
    </ClientOnly>

    <!-- Restoring overwrites what the clinic changed: say so, and how much. -->
    <UModal
      :open="restoring !== null"
      @update:open="(open: boolean) => { if (!open) restoring = null }"
    >
      <template #content>
        <UCard
          v-if="restoring"
          data-testid="specialty-pack-restore-confirm"
        >
          <template #header>
            <h2 class="text-lg font-semibold">
              {{ t('catalog.packs.restoreTitle', { name: name(restoring) }) }}
            </h2>
          </template>
          <div class="space-y-3 text-sm">
            <UAlert
              color="info"
              icon="i-lucide-info"
              :title="t('catalog.packs.restoreWarning')"
              :description="restoring.customised_count
                ? t('catalog.packs.restoreCustomised', { count: restoring.customised_count })
                : t('catalog.packs.restoreNothingCustomised')"
            />
            <ul class="list-disc pl-5 text-muted space-y-1">
              <li>{{ t('catalog.packs.restoreResets') }}</li>
              <li>{{ t('catalog.packs.restoreKeeps') }}</li>
              <li>{{ t('catalog.packs.restorePlans') }}</li>
            </ul>
          </div>
          <template #footer>
            <div class="flex justify-end gap-2">
              <UButton
                color="neutral"
                variant="ghost"
                @click="restoring = null"
              >
                {{ t('common.cancel') }}
              </UButton>
              <UButton
                color="primary"
                icon="i-lucide-rotate-ccw"
                data-testid="specialty-pack-restore-go"
                @click="confirmRestore"
              >
                {{ t('catalog.packs.restoreConfirm') }}
              </UButton>
            </div>
          </template>
        </UCard>
      </template>
    </UModal>
  </div>
</template>
