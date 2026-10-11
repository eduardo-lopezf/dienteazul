<script setup lang="ts">
import type { SlotEntry } from '~/composables/useModuleSlots'
import { PERMISSIONS } from '~/config/permissions'
import { HOME_AREAS, arrangeEntries } from '~/composables/useHomeLayout'
import type { ColorModeKey } from '~/composables/useWorkspaceBrand'
import { COLOR_MODE_KEYS, DEFAULT_COLOR_MODE, PRODUCT_NAME } from '~/composables/useWorkspaceBrand'
import type { AccentKey, CornersKey, DensityKey, FontKey } from '~/config/workspaceTheme'
import {
  ACCENT_KEYS, CORNERS_KEYS, DEFAULT_ACCENT, DEFAULT_CORNERS, DEFAULT_DENSITY, DEFAULT_FONT,
  DENSITY_KEYS, FONT_KEYS, FONTS, accentSwatch, densityVars, themeVars
} from '~/config/workspaceTheme'

/**
 * The workspace App's own settings page (Settings → Apps → Espacio de
 * trabajo, ADR 0043), drawn as a canvas: a miniature of the app itself,
 * edited in place.
 *
 * - The sidebar of the canvas is the brand: the name and the logo the
 *   real sidebar shows, in place of the product's, and the look of the
 *   whole interface: accent colour, typeface, corners and density. The canvas wears them as they
 *   are chosen; the rest of the app does once they are saved.
 * - Its body is the home page: which widgets it shows and in what order.
 *   A widget keeps the area of the page its App put it in; the order is
 *   within that area.
 *
 * One of each per clinic: every member sees the same.
 */
const { t, te } = useI18n()
const toast = useToast()
const { can } = usePermissions()
const homeLayout = useHomeLayout()
const brand = useWorkspaceBrand()
const { navigationItems } = useModules()

// --- Brand: the name is saved with the page, the logo as it is chosen ---
const brandName = ref('')
const accent = ref<AccentKey>(DEFAULT_ACCENT)
const font = ref<FontKey>(DEFAULT_FONT)
const corners = ref<CornersKey>(DEFAULT_CORNERS)
const density = ref<DensityKey>(DEFAULT_DENSITY)
const defaultMode = ref<ColorModeKey>(DEFAULT_COLOR_MODE)
const savedBrand = ref('')
const colorMode = useColorMode()

/** What is chosen, as it is sent: the product's own is "not set". */
function chosenBrand() {
  return {
    display_name: brandName.value.trim() || null,
    accent: accent.value === DEFAULT_ACCENT ? null : accent.value,
    font: font.value === DEFAULT_FONT ? null : font.value,
    corners: corners.value === DEFAULT_CORNERS ? null : corners.value,
    density: density.value === DEFAULT_DENSITY ? null : density.value,
    color_mode: defaultMode.value === DEFAULT_COLOR_MODE ? null : defaultMode.value
  }
}

// The canvas alone wears the choice until it is saved. Always spelled out
// in full — the product's own included — so picking it shows on a canvas
// that sits inside a page already wearing the saved choice.
// Density with a mouse only, as in the real app: a touch screen keeps its tap targets.
const finePointer = ref(true)
onMounted(() => {
  finePointer.value = window.matchMedia('(pointer: fine)').matches
})
// The canvas shows the default mode being chosen: dark is previewed by
// wearing `.dark` itself. Light cannot be previewed inside a page that is
// already dark — the light tokens live on the root — so there it stays as
// the page is.
const canvasDark = computed(() => defaultMode.value === 'dark' || colorMode.value === 'dark')
const canvasStyle = computed(() => ({
  ...themeVars({ accent: accent.value, font: font.value, corners: corners.value }, canvasDark.value, true),
  ...(finePointer.value ? densityVars(density.value, true) : {})
}))

const cornersOptions = computed(() => CORNERS_KEYS.map(key => ({ label: t(`settings.workspace.corners.${key}`), value: key })))
const modeOptions = computed(() => COLOR_MODE_KEYS.map(key => ({ label: t(`settings.workspace.colorMode.${key}`), value: key })))
const densityOptions = computed(() => DENSITY_KEYS.map(key => ({ label: t(`settings.workspace.density.${key}`), value: key })))

const fontOptions = computed(() => FONT_KEYS.map(key => ({ label: FONTS[key].name, value: key })))
const logoBusy = ref(false)
const shownName = computed(() => brandName.value.trim() || PRODUCT_NAME)
const navPreview = computed(() => navigationItems.value.filter(item => item.to !== '/settings'))

async function pickLogo(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  logoBusy.value = true
  try {
    await brand.uploadLogo(file)
  } catch (error: unknown) {
    const e = error as { data?: { detail?: string } }
    toast.add({ title: t('settings.workspace.brand.logoFailed'), description: e?.data?.detail, color: 'error' })
  } finally {
    logoBusy.value = false
  }
}

async function removeLogo() {
  logoBusy.value = true
  try {
    await brand.removeLogo()
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    logoBusy.value = false
  }
}

const canRead = computed(() => can(PERMISSIONS.admin.clinicRead))
const canWrite = computed(() => can(PERMISSIONS.admin.clinicWrite))

interface Row {
  id: string
  labelKey?: string
  descriptionKey?: string
  visible: boolean
}

// Every widget registered for an area, whoever may see it: a layout is
// for the whole clinic, not for the admin's own permissions.
function registered(area: string): SlotEntry[] {
  return listSlotEntries()
    .filter(({ slot }) => slot === area)
    .map(({ entry }) => entry)
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

const areas = ref<{ area: string, rows: Row[] }[]>([])
const saving = ref(false)
const snapshot = ref('')

function build(hidden: string[], order: string[]) {
  const hiddenSet = new Set(hidden)
  areas.value = HOME_AREAS
    .map((area) => {
      // Ordered as the home page would draw them, hidden ones included.
      const rows = arrangeEntries(registered(area), { hidden: [], order }).map(entry => ({
        id: entry.id,
        labelKey: entry.labelKey,
        descriptionKey: entry.descriptionKey,
        visible: !hiddenSet.has(entry.id)
      }))
      return { area, rows }
    })
    .filter(group => group.rows.length > 0)
  snapshot.value = JSON.stringify(current())
}

function current() {
  return {
    hidden: areas.value.flatMap(g => g.rows.filter(r => !r.visible).map(r => r.id)),
    order: areas.value.flatMap(g => g.rows.map(r => r.id))
  }
}

const layoutDirty = computed(() => JSON.stringify(current()) !== snapshot.value)
const brandDirty = computed(() => JSON.stringify(chosenBrand()) !== savedBrand.value)
const dirty = computed(() => layoutDirty.value || brandDirty.value)

function label(row: Row): string {
  return row.labelKey && te(row.labelKey) ? t(row.labelKey) : row.id
}

function areaLabel(area: string): string {
  const key = `settings.widgets.slots.${area}`
  return te(key) ? t(key) : area
}

function move(rows: Row[], index: number, step: -1 | 1) {
  const target = index + step
  if (target < 0 || target >= rows.length) return
  const [row] = rows.splice(index, 1)
  rows.splice(target, 0, row!)
}

function restoreDefaults() {
  build([], [])
  snapshot.value = ''
  // The look goes back to the product's too; the name and the logo stay.
  accent.value = DEFAULT_ACCENT
  font.value = DEFAULT_FONT
  corners.value = DEFAULT_CORNERS
  density.value = DEFAULT_DENSITY
  defaultMode.value = DEFAULT_COLOR_MODE
}

async function save() {
  saving.value = true
  try {
    if (layoutDirty.value) {
      await homeLayout.save(current())
      snapshot.value = JSON.stringify(current())
    }
    if (brandDirty.value) {
      await brand.save(chosenBrand())
      savedBrand.value = JSON.stringify(chosenBrand())
    }
    toast.add({ title: t('settings.home.saved'), color: 'success' })
  } catch {
    toast.add({ title: t('errors.updateFailed'), color: 'error' })
  } finally {
    saving.value = false
  }
}

async function load() {
  await homeLayout.load(true)
  const stored = homeLayout.layout.value
  build([...(stored?.hidden ?? [])], [...(stored?.order ?? [])])
  await brand.load(true)
  brandName.value = brand.brand.value?.display_name ?? ''
  accent.value = brand.brand.value?.accent ?? DEFAULT_ACCENT
  font.value = brand.brand.value?.font ?? DEFAULT_FONT
  corners.value = brand.brand.value?.corners ?? DEFAULT_CORNERS
  density.value = brand.brand.value?.density ?? DEFAULT_DENSITY
  defaultMode.value = brand.brand.value?.color_mode ?? DEFAULT_COLOR_MODE
  savedBrand.value = JSON.stringify(chosenBrand())
}

/** How the tiles of an area sit in the canvas — as on the real home page. */
function areaGrid(area: string): string {
  return area === 'dashboard.hero' || area === 'dashboard.widgets'
    ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
    : 'grid-cols-1'
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
        to="/settings/apps"
        variant="ghost"
        size="sm"
        icon="i-lucide-arrow-left"
      >
        {{ t('settings.categories.modules.label') }}
      </UButton>
    </div>

    <div class="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <div class="flex items-center gap-2 flex-wrap">
          <h1 class="text-display text-default">
            {{ t('settings.apps.catalog.workspace.title') }}
          </h1>
          <UBadge
            color="primary"
            variant="subtle"
            size="sm"
          >
            {{ t('settings.apps.tier.base') }}
          </UBadge>
        </div>
        <p class="text-muted mt-1">
          {{ t('settings.workspace.intro') }}
        </p>
      </div>
      <div
        v-if="canWrite"
        class="flex gap-2"
      >
        <UButton
          variant="ghost"
          color="neutral"
          icon="i-lucide-rotate-ccw"
          data-testid="home-layout-reset"
          @click="restoreDefaults"
        >
          {{ t('settings.home.reset') }}
        </UButton>
        <UButton
          icon="i-lucide-save"
          :loading="saving"
          :disabled="!dirty"
          data-testid="home-layout-save"
          @click="save"
        >
          {{ t('common.save') }}
        </UButton>
      </div>
    </div>

    <AccountLimits v-if="canRead" />

    <div
      v-if="!canRead"
      class="rounded-md border border-default p-6 text-sm text-muted"
    >
      {{ t('common.forbidden', 'Acceso denegado') }}
    </div>

    <!-- Client-only: widgets register from each layer's `slots.client.ts`. -->
    <ClientOnly v-else>
      <!-- The canvas: the app in miniature, edited where it shows. -->
      <div
        class="flex overflow-hidden rounded-[var(--radius-xl)] border border-default bg-canvas shadow-[var(--shadow-md)]"
        :class="{ dark: canvasDark }"
        :style="canvasStyle"
        data-testid="workspace-canvas"
      >
        <!-- Its sidebar is the brand. -->
        <aside
          class="hidden w-56 shrink-0 flex-col gap-4 bg-surface-muted p-4 sm:flex"
          data-testid="workspace-brand"
        >
          <div class="flex items-center gap-2 overflow-hidden">
            <img
              :src="brand.logo.value"
              alt=""
              class="h-8 w-8 shrink-0 object-contain"
              data-testid="workspace-brand-logo"
            >
            <span
              class="text-h2 text-default truncate"
              data-testid="workspace-brand-shown"
            >{{ shownName }}</span>
          </div>

          <div
            v-if="canWrite"
            class="space-y-2"
          >
            <UFormField
              :label="t('settings.workspace.brand.name')"
              size="xs"
            >
              <UInput
                v-model="brandName"
                class="w-full"
                size="sm"
                :maxlength="60"
                :placeholder="PRODUCT_NAME"
                data-testid="workspace-brand-name"
              />
            </UFormField>
            <div class="flex gap-1.5">
              <label
                class="inline-flex cursor-pointer items-center gap-1.5 rounded-md bg-surface px-2.5 py-1.5 text-xs text-default ring-1 ring-[var(--color-border)]"
                :class="{ 'pointer-events-none opacity-50': logoBusy }"
              >
                <UIcon
                  name="i-lucide-upload"
                  class="h-3.5 w-3.5"
                />
                {{ t('settings.workspace.brand.upload') }}
                <input
                  type="file"
                  accept="image/png,image/jpeg"
                  class="hidden"
                  data-testid="workspace-brand-logo-input"
                  @change="pickLogo"
                >
              </label>
              <UButton
                v-if="brand.brand.value?.has_logo"
                size="xs"
                color="neutral"
                variant="ghost"
                icon="i-lucide-x"
                :loading="logoBusy"
                :aria-label="t('settings.workspace.brand.remove')"
                data-testid="workspace-brand-logo-remove"
                @click="removeLogo"
              />
            </div>
            <p class="text-caption text-subtle">
              {{ t('settings.workspace.brand.hint') }}
            </p>
          </div>

          <div
            v-if="canWrite"
            class="space-y-3 border-t border-default pt-3"
          >
            <div>
              <p class="text-xs font-medium text-default mb-1.5">
                {{ t('settings.workspace.brand.accent') }}
              </p>
              <div
                class="flex flex-wrap gap-1.5"
                role="radiogroup"
                :aria-label="t('settings.workspace.brand.accent')"
              >
                <button
                  v-for="key in ACCENT_KEYS"
                  :key="key"
                  type="button"
                  role="radio"
                  :aria-checked="accent === key"
                  :aria-label="t(`settings.workspace.accents.${key}`)"
                  :title="t(`settings.workspace.accents.${key}`)"
                  class="h-7 w-7 rounded-full ring-offset-2 ring-offset-[var(--color-surface-muted)] transition-shadow"
                  :class="accent === key ? 'ring-2 ring-[var(--color-text)]' : 'ring-1 ring-[var(--color-border)]'"
                  :style="{ backgroundColor: accentSwatch(key) }"
                  :data-testid="`workspace-accent-${key}`"
                  @click="accent = key"
                />
              </div>
            </div>
            <UFormField
              :label="t('settings.workspace.brand.font')"
              size="xs"
            >
              <USelect
                v-model="font"
                :items="fontOptions"
                value-key="value"
                size="sm"
                class="w-full"
                data-testid="workspace-font"
              />
            </UFormField>
            <UFormField
              :label="t('settings.workspace.brand.corners')"
              size="xs"
            >
              <URadioGroup
                v-model="corners"
                :items="cornersOptions"
                value-key="value"
                size="sm"
                data-testid="workspace-corners"
              />
            </UFormField>
            <UFormField
              :label="t('settings.workspace.brand.density')"
              :help="t('settings.workspace.brand.densityHint')"
              size="xs"
            >
              <URadioGroup
                v-model="density"
                :items="densityOptions"
                value-key="value"
                size="sm"
                data-testid="workspace-density"
              />
            </UFormField>
            <UFormField
              :label="t('settings.workspace.brand.colorMode')"
              :help="t('settings.workspace.brand.colorModeHint')"
              size="xs"
            >
              <URadioGroup
                v-model="defaultMode"
                :items="modeOptions"
                value-key="value"
                size="sm"
                data-testid="workspace-color-mode"
              />
            </UFormField>
          </div>

          <!-- The menu, as it is: not editable here, only shown. -->
          <nav
            class="space-y-1 border-t border-default pt-3"
            aria-hidden="true"
          >
            <div
              v-for="item in navPreview"
              :key="item.to"
              class="flex items-center gap-2 rounded-token-md px-2 py-1.5 text-caption text-muted"
              :class="{ 'bg-[var(--color-primary-soft)] text-[var(--color-primary-soft-text)]': item.to === '/' }"
            >
              <UIcon
                :name="item.icon"
                class="h-3.5 w-3.5 shrink-0"
              />
              <span class="truncate">{{ item.label }}</span>
            </div>
          </nav>
        </aside>

        <!-- Its body is the home page. -->
        <div class="min-w-0 flex-1 space-y-5 p-4 sm:p-5">
          <div>
            <h2
              class="text-h2 text-default"
              data-testid="workspace-section-home"
            >
              {{ t('settings.home.title') }}
            </h2>
            <p class="text-caption text-muted mt-0.5">
              {{ t('settings.home.intro') }}
            </p>
          </div>

          <section
            v-for="group in areas"
            :key="group.area"
            :data-testid="`home-area-${group.area}`"
          >
            <h3 class="text-caption font-medium uppercase tracking-wide text-subtle mb-2">
              {{ areaLabel(group.area) }}
            </h3>
            <ul
              class="grid gap-3"
              :class="areaGrid(group.area)"
            >
              <li
                v-for="(row, index) in group.rows"
                :key="row.id"
                :data-testid="`home-widget-${row.id}`"
                class="flex flex-col gap-2 rounded-[var(--radius-lg)] p-3 transition-colors"
                :class="row.visible
                  ? 'bg-surface ring-1 ring-[var(--color-border)] shadow-[var(--shadow-sm)]'
                  : 'border border-dashed border-default opacity-60'"
              >
                <div class="min-w-0">
                  <p
                    class="font-medium truncate"
                    :class="row.visible ? 'text-default' : 'text-subtle line-through'"
                  >
                    {{ label(row) }}
                  </p>
                  <p
                    v-if="row.descriptionKey && te(row.descriptionKey)"
                    class="text-caption text-muted line-clamp-2"
                  >
                    {{ t(row.descriptionKey) }}
                  </p>
                </div>
                <div class="mt-auto flex items-center justify-between gap-2">
                  <USwitch
                    v-model="row.visible"
                    :disabled="!canWrite"
                    :aria-label="label(row)"
                  />
                  <div
                    v-if="canWrite"
                    class="flex gap-1"
                  >
                    <UButton
                      icon="i-lucide-arrow-up"
                      variant="ghost"
                      color="neutral"
                      size="sm"
                      :disabled="index === 0"
                      :aria-label="t('settings.home.moveUp')"
                      @click="move(group.rows, index, -1)"
                    />
                    <UButton
                      icon="i-lucide-arrow-down"
                      variant="ghost"
                      color="neutral"
                      size="sm"
                      :disabled="index === group.rows.length - 1"
                      :aria-label="t('settings.home.moveDown')"
                      @click="move(group.rows, index, 1)"
                    />
                  </div>
                </div>
              </li>
            </ul>
          </section>

          <p
            v-if="areas.length === 0"
            class="text-sm text-muted"
          >
            {{ t('settings.widgets.empty') }}
          </p>
        </div>
      </div>
    </ClientOnly>
  </div>
</template>
