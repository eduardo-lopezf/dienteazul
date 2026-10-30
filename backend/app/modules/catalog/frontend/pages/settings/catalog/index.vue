<script setup lang="ts">
import type { TreatmentCatalogItem, TreatmentCatalogItemUpdate, TreatmentCatalogItemCreate, TreatmentCatalogCategory, Specialty, SpecialtyUpdate } from '~~/app/types'
import { PERMISSIONS } from '~~/app/config/permissions'

const { t, locale } = useI18n()
const { can } = usePermissions()

// Ask the same question the API asks, rather than "is this an admin".
// Treatment items are gated on `catalog.write`; the taxonomy around them
// (categories, specialties, VAT types) on `catalog.admin`. Only the admin
// role holds either today, so this changes nothing now — but the day a
// dentist is given `catalog.write` to keep the price list, the buttons
// follow the grant instead of staying hidden behind a role check.
const canEditItems = computed(() => can(PERMISSIONS.catalog.write))
const canManageTaxonomy = computed(() => can(PERMISSIONS.catalog.admin))
const catalog = useCatalog()
const specialtiesApi = useSpecialties()

// View tabs: by treatment type (existing) vs by specialty
type CatalogView = 'type' | 'specialty'
const activeView = ref<CatalogView>('type')
const viewTabs = computed(() => [
  { value: 'type', label: t('catalog.byTreatmentType') },
  { value: 'specialty', label: t('catalog.bySpecialty') }
])

// Specialties tab state
const showSpecialtiesInactive = ref(false)
const displaySpecialties = computed(() =>
  showSpecialtiesInactive.value ? specialtiesApi.specialties.value : specialtiesApi.activeSpecialties.value
)

// Both tabs read one snapshot, `catalog.items`, loaded once with
// `include_deleted` (live, inactive and removed together). Each tab narrows
// it in the browser. The specialty view used to keep a second full copy,
// which every save re-downloaded on top of the first.
//
// The specialty view lists live and inactive treatments, never removed ones,
// and ignores the list view's search and category on purpose.
const specialtyItems = computed(() => catalog.items.value.filter(item => !item.deleted_at))
const isLoadingSpecialtyView = ref(false)

// Pseudo-group collecting treatments that have no specialty yet.
const UNASSIGNED_GROUP_ID = '__unassigned__'

const itemsBySpecialtyId = computed(() => {
  const map = new Map<string, TreatmentCatalogItem[]>()
  for (const item of specialtyItems.value) {
    for (const specialty of item.specialties ?? []) {
      const group = map.get(specialty.id)
      if (group) group.push(item)
      else map.set(specialty.id, [item])
    }
  }
  return map
})

function itemsForSpecialty(specialtyId: string): TreatmentCatalogItem[] {
  return itemsBySpecialtyId.value.get(specialtyId) ?? []
}

const unassignedItems = computed(() =>
  specialtyItems.value.filter(item => !item.specialties?.length)
)

interface SpecialtyGroup {
  id: string
  label: string
  specialty: Specialty | null
  items: TreatmentCatalogItem[]
}

const specialtyGroups = computed<SpecialtyGroup[]>(() => {
  const groups: SpecialtyGroup[] = displaySpecialties.value.map(specialty => ({
    id: specialty.id,
    label: specialtiesApi.getSpecialtyName(specialty),
    specialty,
    items: itemsForSpecialty(specialty.id)
  }))

  if (unassignedItems.value.length > 0) {
    groups.push({
      id: UNASSIGNED_GROUP_ID,
      label: t('specialties.unassigned'),
      specialty: null,
      items: unassignedItems.value
    })
  }

  return groups
})

const expandedSpecialties = ref<Set<string>>(new Set())

function isSpecialtyExpanded(groupId: string): boolean {
  return expandedSpecialties.value.has(groupId)
}

function toggleSpecialtyGroup(groupId: string) {
  const next = new Set(expandedSpecialties.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  expandedSpecialties.value = next
}

async function loadSpecialtyView() {
  isLoadingSpecialtyView.value = true
  try {
    // Groups start collapsed: drawing every discipline's treatments at once
    // (several hundred rows, many shown under more than one) froze the
    // browser for seconds on first open. A group draws its rows when opened.
    await specialtiesApi.fetchSpecialties(true)
  } finally {
    isLoadingSpecialtyView.value = false
  }
}

// Assign treatments to a specialty
const showAssignModal = ref(false)
const isAssigning = ref(false)
const assignTarget = ref<Specialty | null>(null)
const assignSearch = ref('')
const assignSelectedIds = ref<Set<string>>(new Set())

function openAssignModal(specialty: Specialty) {
  assignTarget.value = specialty
  assignSearch.value = ''
  assignSelectedIds.value = new Set(itemsForSpecialty(specialty.id).map(item => item.id))
  showAssignModal.value = true
}

// Inactive treatments stay listed only while assigned, so an existing
// assignment can still be removed without resurrecting the treatment.
const assignCandidates = computed(() => {
  const term = assignSearch.value.trim().toLowerCase()
  return specialtyItems.value.filter((item) => {
    if (!item.is_active && !assignSelectedIds.value.has(item.id)) return false
    if (!term) return true
    return (
      item.internal_code.toLowerCase().includes(term)
      || getItemName(item).toLowerCase().includes(term)
    )
  })
})

function isAssignSelected(itemId: string): boolean {
  return assignSelectedIds.value.has(itemId)
}

function toggleAssignItem(itemId: string) {
  const next = new Set(assignSelectedIds.value)
  if (next.has(itemId)) next.delete(itemId)
  else next.add(itemId)
  assignSelectedIds.value = next
}

async function handleAssignSave() {
  if (!assignTarget.value) return

  isAssigning.value = true
  const result = await specialtiesApi.setSpecialtyItems(
    assignTarget.value.id,
    [...assignSelectedIds.value]
  )
  if (result) {
    await reloadItems()
    showAssignModal.value = false
    assignTarget.value = null
  }
  isAssigning.value = false
}

const showSpecialtyEditModal = ref(false)
const isEditingSpecialty = ref(false)
const editingSpecialty = ref<Specialty | null>(null)
const editSpecialtyName = ref('')
const editSpecialtyActive = ref(true)

const showSpecialtyDeleteModal = ref(false)
const isDeletingSpecialty = ref(false)
const specialtyToDelete = ref<Specialty | null>(null)

const specialtyViewOpened = ref(false)
watch(activeView, async (view) => {
  if (view === 'specialty' && !specialtyViewOpened.value) {
    specialtyViewOpened.value = true
    await loadSpecialtyView()
  }
})

function openSpecialtyEditModal(specialty: Specialty) {
  editingSpecialty.value = specialty
  editSpecialtyName.value = specialtiesApi.getSpecialtyName(specialty)
  editSpecialtyActive.value = specialty.is_active
  showSpecialtyEditModal.value = true
}

async function handleSpecialtyUpdate() {
  if (!editingSpecialty.value) return

  isEditingSpecialty.value = true
  const data: SpecialtyUpdate = {
    names: { [locale.value]: editSpecialtyName.value },
    is_active: editSpecialtyActive.value
  }
  const result = await specialtiesApi.updateSpecialty(editingSpecialty.value.id, data)
  isEditingSpecialty.value = false
  if (result) {
    showSpecialtyEditModal.value = false
    editingSpecialty.value = null
  }
}

function openSpecialtyDeleteModal(specialty: Specialty) {
  specialtyToDelete.value = specialty
  showSpecialtyDeleteModal.value = true
}

async function handleSpecialtyDelete() {
  if (!specialtyToDelete.value) return

  isDeletingSpecialty.value = true
  const result = await specialtiesApi.deleteSpecialty(specialtyToDelete.value.id)
  isDeletingSpecialty.value = false
  if (result) {
    showSpecialtyDeleteModal.value = false
    specialtyToDelete.value = null
  }
}

// "Visible" column — one flag per treatment, rendered in both tabs, so
// ticking it under "Tipo de Tratamiento" shows it ticked under "Por
// Especialidad" too. Controls only the clinical /treatments list; an
// unticked treatment stays active and billable.
const togglingVisibility = ref<Set<string>>(new Set())

function isTogglingVisibility(itemId: string): boolean {
  return togglingVisibility.value.has(itemId)
}

async function toggleVisible(item: TreatmentCatalogItem) {
  if (isTogglingVisibility(item.id)) return

  const next = item.is_visible === false
  togglingVisibility.value = new Set(togglingVisibility.value).add(item.id)
  try {
    const updated = await catalog.updateItem(item.id, { is_visible: next })
    if (!updated) return
    // Patch the row rather than refetching the whole catalog for one checkbox.
    const found = catalog.items.value.find(i => i.id === item.id)
    if (found) found.is_visible = next
  } finally {
    const pending = new Set(togglingVisibility.value)
    pending.delete(item.id)
    togglingVisibility.value = pending
  }
}

/**
 * Save one price typed into the table.
 *
 * The row is patched rather than the catalog reloaded: setting a clinic's
 * prices means walking a column, and re-reading 136 rows between each one
 * would move the list under the cursor. Both tabs read the same snapshot, so
 * the specialty tab follows along.
 */
async function savePrice(item: TreatmentCatalogItem, price: number) {
  const updated = await catalog.updateItem(item.id, { default_price: price }, { silent: true })
  if (!updated) return
  const found = catalog.items.value.find(i => i.id === item.id)
  if (found) found.default_price = updated.default_price
}

// Modal state
const showModal = ref(false)
const editingItem = ref<TreatmentCatalogItem | null>(null)
const isSaving = ref(false)

// Delete confirmation state
const showDeleteConfirm = ref(false)
const itemToDelete = ref<TreatmentCatalogItem | null>(null)
const isDeleting = ref(false)

// Filters
const searchQuery = ref('')
const selectedCategoryId = ref<string | undefined>(undefined)

/**
 * Show what the catalog no longer offers: treatments deactivated, and
 * treatments removed.
 *
 * Off by default — the question this screen answers is "what do we charge
 * for". But without it the two were unreachable from the only screen that can
 * edit them. Deactivating a treatment made it vanish from this list, which is
 * also the only place to reactivate it; and a removed treatment kept its
 * internal code reserved, so it could neither be found nor recreated under the
 * same code.
 *
 * The snapshot already holds both (it is loaded with `include_deleted`), so
 * the switch only narrows in the browser.
 */
const showRemoved = ref(false)

// Track which categories are expanded (all expanded by default)
const expandedCategories = ref<Set<string>>(new Set())

// Load data on mount
onMounted(async () => {
  await Promise.all([
    catalog.fetchCategories(),
    reloadItems()
  ])
  // Expand all categories by default
  expandedCategories.value = new Set(catalog.categories.value.map(c => c.id))
})

/**
 * Search and category narrow the loaded catalog here, in the browser, rather
 * than re-querying. The screen groups by category, and a grouping can only be
 * read off a complete list — asking the server for "everything" in one page
 * is one server-side cap away from grouping a subset and heading it with the
 * total, which is exactly what this screen did.
 *
 * Same trade the clinical catalog already makes: a clinic's catalog is a
 * couple of hundred rows.
 */
// What the list view offers before search and category: what the catalog
// charges for, plus — with the switch on — what it no longer offers.
const listViewItems = computed(() =>
  showRemoved.value ? catalog.items.value : catalog.items.value.filter(item => item.is_active)
)

const filteredItems = computed(() => {
  const term = searchQuery.value.trim().toLowerCase()

  return listViewItems.value.filter((item) => {
    if (selectedCategoryId.value && item.category_id !== selectedCategoryId.value) return false
    if (!term) return true
    return (
      getItemName(item).toLowerCase().includes(term)
      || item.internal_code.toLowerCase().includes(term)
    )
  })
})

const isFiltered = computed(() =>
  Boolean(searchQuery.value.trim() || selectedCategoryId.value)
)

// The count beside the heading counts the rows underneath it, and says so out
// of how many when a filter is on. It used to print the catalog total over a
// list that held one page of it.
const countLabel = computed(() =>
  isFiltered.value
    ? t('catalog.count', { shown: filteredItems.value.length, total: listViewItems.value.length })
    : String(filteredItems.value.length)
)

// Group items by category
interface CategoryGroup {
  category: TreatmentCatalogCategory
  items: TreatmentCatalogItem[]
}

const groupedItems = computed<CategoryGroup[]>(() => {
  // If a specific category is selected, don't group
  if (selectedCategoryId.value) {
    return []
  }

  // Group items by category_id
  const groups = new Map<string, TreatmentCatalogItem[]>()
  for (const item of filteredItems.value) {
    const categoryId = item.category_id
    if (!groups.has(categoryId)) {
      groups.set(categoryId, [])
    }
    groups.get(categoryId)!.push(item)
  }

  // Convert to array with category info, sorted by display_order
  const result: CategoryGroup[] = []
  const sortedCategories = [...catalog.categories.value].sort((a, b) => a.display_order - b.display_order)
  for (const category of sortedCategories) {
    const items = groups.get(category.id)
    if (items && items.length > 0) {
      result.push({ category, items })
    }
  }

  return result
})

// Check if we should show grouped view
const showGroupedView = computed(() => !selectedCategoryId.value && groupedItems.value.length > 0)

// Toggle category expansion
function toggleCategory(categoryId: string) {
  if (expandedCategories.value.has(categoryId)) {
    expandedCategories.value.delete(categoryId)
  } else {
    expandedCategories.value.add(categoryId)
  }
  // Force reactivity
  expandedCategories.value = new Set(expandedCategories.value)
}

function isCategoryExpanded(categoryId: string): boolean {
  return expandedCategories.value.has(categoryId)
}

// Expand/collapse all
function expandAll() {
  expandedCategories.value = new Set(catalog.categories.value.map(c => c.id))
}

function collapseAll() {
  expandedCategories.value = new Set()
}

/** Load the whole catalog: live, inactive and removed, in one pass. */
async function reloadItems() {
  await catalog.loadAllItems(false, true)
}

/**
 * Put the row a write returned into the snapshot, in internal-code order.
 *
 * Writes do not re-read the catalog. They used to: one save fetched every
 * page of it twice in a row (once per tab) and re-rendered every row, which
 * froze the browser for seconds. A request left waiting through that freeze
 * is reported as timed out even when the server answered at once, so an
 * admin editing several treatments in a row got a stack of "el servidor
 * tardó" for saves that had worked. The API answers each write with the full
 * item, which is all the screen needs.
 */
function upsertItem(item: TreatmentCatalogItem) {
  const list = catalog.items.value
  const index = list.findIndex(i => i.id === item.id)
  if (index !== -1) {
    list.splice(index, 1, item)
    return
  }
  const at = list.findIndex(i => i.internal_code.localeCompare(item.internal_code) > 0)
  list.splice(at === -1 ? list.length : at, 0, item)
}

// Undoing a deletion is an ordinary update: the row never went away, and
// setting it active again clears `deleted_at` server-side.
const restoring = ref<Set<string>>(new Set())

function isRestoring(itemId: string): boolean {
  return restoring.value.has(itemId)
}

async function restoreItem(item: TreatmentCatalogItem) {
  if (isRestoring(item.id)) return
  restoring.value = new Set(restoring.value).add(item.id)
  try {
    const restored = await catalog.updateItem(item.id, { is_active: true })
    if (restored) upsertItem(restored)
  } finally {
    const pending = new Set(restoring.value)
    pending.delete(item.id)
    restoring.value = pending
  }
}

// Create/Edit modal
function openCreateModal() {
  editingItem.value = null
  showModal.value = true
}

function openEditModal(item: TreatmentCatalogItem) {
  editingItem.value = item
  showModal.value = true
}

async function handleCreateItem(data: TreatmentCatalogItemCreate) {
  isSaving.value = true
  const result = await catalog.createItem(data)
  isSaving.value = false

  if (result) {
    showModal.value = false
    upsertItem(result)
  }
}

async function handleSaveItem(data: TreatmentCatalogItemUpdate) {
  if (!editingItem.value) return

  isSaving.value = true
  const result = await catalog.updateItem(editingItem.value.id, data)
  isSaving.value = false

  if (result) {
    showModal.value = false
    editingItem.value = null
    upsertItem(result)
  }
}

// Delete confirmation
function confirmDelete(item: TreatmentCatalogItem) {
  itemToDelete.value = item
  showDeleteConfirm.value = true
}

async function handleDeleteItem() {
  if (!itemToDelete.value) return

  isDeleting.value = true
  const deletedId = itemToDelete.value.id
  const result = await catalog.deleteItem(deletedId)
  isDeleting.value = false

  if (result) {
    // The delete answers 204, so mark the row the way the server just did
    // (`CatalogService.delete_item`): removed and inactive. It stays in the
    // snapshot, which is what lets "Mostrar inactivos y eliminados" show it.
    const found = catalog.items.value.find(i => i.id === deletedId)
    if (found) {
      found.deleted_at = new Date().toISOString()
      found.is_active = false
    }
    showDeleteConfirm.value = false
    itemToDelete.value = null
  }
}

// Helpers
function getItemName(item: TreatmentCatalogItem): string {
  return catalog.getItemName(item)
}

function getCategoryName(categoryId: string): string {
  const category = catalog.categories.value.find(c => c.id === categoryId)
  return category ? catalog.getCategoryName(category) : '-'
}

// Category options for filter
const categoryOptions = computed(() => [
  { value: undefined, label: t('common.all') },
  ...catalog.activeCategories.value.map(c => ({
    value: c.id,
    label: catalog.getCategoryName(c)
  }))
])
</script>

<template>
  <div class="space-y-6">
    <!-- Page header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-display text-default">
          {{ t('catalog.title') }}
        </h1>
        <p class="text-caption text-subtle mt-1">
          {{ t('catalog.description') }}
        </p>
      </div>
      <div class="flex items-center gap-2">
        <UButton
          v-if="canEditItems && activeView === 'type'"
          icon="i-lucide-plus"
          @click="openCreateModal"
        >
          {{ t('catalog.newItem') }}
        </UButton>
        <NuxtLink to="/settings">
          <UButton
            variant="ghost"
            icon="i-lucide-arrow-left"
          >
            {{ t('common.back') }}
          </UButton>
        </NuxtLink>
      </div>
    </div>

    <!-- View tabs -->
    <UTabs
      v-model="activeView"
      :items="viewTabs"
      class="w-full sm:w-auto"
    />

    <!-- By Specialty. Mounted on first open, then hidden rather than torn
         down: each tab draws every treatment, and rebuilding several
         hundred rows froze the browser for seconds on every switch. -->
    <div
      v-if="specialtyViewOpened"
      v-show="activeView === 'specialty'"
      class="space-y-6"
    >
      <div class="flex items-center justify-between gap-4">
        <p class="text-caption text-subtle">
          {{ t('specialties.viewHint') }}
        </p>
        <div class="flex items-center gap-2">
          <USwitch v-model="showSpecialtiesInactive" />
          <span class="text-sm text-muted dark:text-subtle">
            {{ t('specialties.showInactive') }}
          </span>
        </div>
      </div>

      <!-- Loading state -->
      <div
        v-if="isLoadingSpecialtyView"
        class="space-y-3"
      >
        <USkeleton class="h-16 w-full" />
        <USkeleton class="h-16 w-full" />
        <USkeleton class="h-16 w-full" />
      </div>

      <UCard v-else-if="specialtyGroups.length === 0">
        <div class="text-center py-12 text-muted">
          <UIcon
            name="i-lucide-stethoscope"
            class="w-12 h-12 mx-auto mb-4 opacity-50"
          />
          <p>{{ t('specialties.noItems') }}</p>
        </div>
      </UCard>

      <!-- Specialty groups (last group collects unassigned treatments) -->
      <template v-else>
        <UCard
          v-for="group in specialtyGroups"
          :key="group.id"
          class="overflow-hidden"
          :ui="isSpecialtyExpanded(group.id) ? undefined : { body: 'hidden' }"
        >
          <template #header>
            <div class="flex items-center justify-between gap-3">
              <button
                class="flex-1 flex items-center gap-3 py-1 text-left"
                @click="toggleSpecialtyGroup(group.id)"
              >
                <UIcon
                  :name="isSpecialtyExpanded(group.id) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                  class="w-5 h-5 text-subtle transition-transform"
                />
                <span
                  class="font-semibold"
                  :class="group.specialty ? 'text-default' : 'text-muted'"
                >
                  {{ group.label }}
                </span>
                <UBadge
                  variant="subtle"
                  color="neutral"
                  size="xs"
                >
                  {{ group.items.length }}
                </UBadge>
                <UBadge
                  v-if="group.specialty && !group.specialty.is_active"
                  variant="subtle"
                  color="error"
                  size="xs"
                >
                  {{ t('common.inactive') }}
                </UBadge>
              </button>

              <div
                v-if="canManageTaxonomy && group.specialty"
                class="flex items-center gap-1"
              >
                <UButton
                  v-if="group.specialty.is_active"
                  icon="i-lucide-list-plus"
                  size="xs"
                  variant="ghost"
                  color="neutral"
                  @click="openAssignModal(group.specialty)"
                >
                  {{ t('specialties.assignItems') }}
                </UButton>
                <UButton
                  icon="i-lucide-pencil"
                  size="xs"
                  variant="ghost"
                  color="neutral"
                  @click="openSpecialtyEditModal(group.specialty)"
                />
                <UButton
                  v-if="group.specialty.is_active"
                  icon="i-lucide-trash-2"
                  size="xs"
                  variant="ghost"
                  color="error"
                  @click="openSpecialtyDeleteModal(group.specialty)"
                />
              </div>
            </div>
          </template>

          <!-- `v-if`: a collapsed group's rows are not drawn at all. -->
          <div v-if="isSpecialtyExpanded(group.id)">
            <p
              v-if="group.items.length === 0"
              class="py-4 text-sm text-muted dark:text-subtle"
            >
              {{ t('specialties.noTreatments') }}
            </p>

            <div
              v-else
              class="overflow-x-auto -mx-4 sm:-mx-6"
            >
              <table class="w-full">
                <thead>
                  <tr class="border-b border-default bg-surface-muted/50">
                    <th class="text-left py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.code') }}
                    </th>
                    <th class="text-left py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.name') }}
                    </th>
                    <th class="hidden sm:table-cell text-left py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.category') }}
                    </th>
                    <th class="text-center py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.visible') }}
                    </th>
                    <th class="text-right py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.price') }}
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--color-border-subtle)]">
                  <CatalogItemRow
                    v-for="item in group.items"
                    :key="item.id"
                    :item="item"
                    variant="specialty"
                    :category-name="getCategoryName(item.category_id)"
                    :can-edit="canEditItems"
                    :toggling="isTogglingVisibility(item.id)"
                    @save-price="savePrice"
                    @toggle-visible="toggleVisible"
                  />
                </tbody>
              </table>
            </div>
          </div>
        </UCard>
      </template>

      <!-- Assign Treatments Modal -->
      <UModal v-model:open="showAssignModal">
        <template #content>
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon
                  name="i-lucide-list-plus"
                  class="w-5 h-5 text-primary-accent"
                />
                <h3 class="font-semibold text-default">
                  {{ t('specialties.assignTitle', { name: assignTarget ? specialtiesApi.getSpecialtyName(assignTarget) : '' }) }}
                </h3>
              </div>
            </template>

            <div class="space-y-4">
              <UInput
                v-model="assignSearch"
                icon="i-lucide-search"
                :placeholder="t('catalog.searchPlaceholder')"
              />

              <div class="max-h-80 overflow-y-auto divide-y divide-[var(--color-border-subtle)]">
                <p
                  v-if="assignCandidates.length === 0"
                  class="py-6 text-center text-sm text-muted dark:text-subtle"
                >
                  {{ t('catalog.noItems') }}
                </p>

                <!-- The whole row toggles; the checkbox is display-only so
                     the click is handled exactly once. -->
                <button
                  v-for="item in assignCandidates"
                  :key="item.id"
                  type="button"
                  class="w-full flex items-center gap-3 py-2.5 px-1 text-left hover:bg-surface-muted"
                  @click="toggleAssignItem(item.id)"
                >
                  <UCheckbox
                    :model-value="isAssignSelected(item.id)"
                    tabindex="-1"
                    class="pointer-events-none"
                  />
                  <span class="font-mono text-sm text-muted dark:text-subtle w-28 shrink-0">
                    {{ item.internal_code }}
                  </span>
                  <span class="flex-1 text-default">
                    {{ getItemName(item) }}
                  </span>
                  <span
                    v-if="!item.is_active"
                    class="text-xs text-danger-accent"
                  >
                    {{ t('common.inactive') }}
                  </span>
                  <span class="text-sm text-muted dark:text-subtle">
                    {{ getCategoryName(item.category_id) }}
                  </span>
                </button>
              </div>

              <div class="flex items-center justify-between pt-2">
                <span class="text-sm text-muted dark:text-subtle">
                  {{ t('specialties.selectedCount', { count: assignSelectedIds.size }) }}
                </span>
                <div class="flex gap-2">
                  <UButton
                    variant="ghost"
                    @click="showAssignModal = false"
                  >
                    {{ t('common.cancel') }}
                  </UButton>
                  <UButton
                    :loading="isAssigning"
                    @click="handleAssignSave"
                  >
                    {{ t('common.save') }}
                  </UButton>
                </div>
              </div>
            </div>
          </UCard>
        </template>
      </UModal>

      <!-- Edit Specialty Modal -->
      <UModal v-model:open="showSpecialtyEditModal">
        <template #content>
          <UCard>
            <template #header>
              <div class="flex items-center gap-2">
                <UIcon
                  name="i-lucide-pencil"
                  class="w-5 h-5 text-primary-accent"
                />
                <h3 class="font-semibold text-default">
                  {{ t('specialties.edit') }}
                </h3>
              </div>
            </template>

            <form
              class="space-y-4"
              @submit.prevent="handleSpecialtyUpdate"
            >
              <UFormField :label="t('specialties.name')">
                <UInput
                  v-model="editSpecialtyName"
                  required
                  :placeholder="t('specialties.namePlaceholder')"
                />
              </UFormField>

              <div class="flex items-center gap-3">
                <USwitch v-model="editSpecialtyActive" />
                <span class="text-sm text-muted">
                  {{ t('catalog.active') }}
                </span>
              </div>

              <div class="flex justify-end gap-2 pt-4">
                <UButton
                  variant="ghost"
                  @click="showSpecialtyEditModal = false"
                >
                  {{ t('common.cancel') }}
                </UButton>
                <UButton
                  type="submit"
                  :loading="isEditingSpecialty"
                >
                  {{ t('common.save') }}
                </UButton>
              </div>
            </form>
          </UCard>
        </template>
      </UModal>

      <!-- Delete Specialty Confirmation -->
      <UModal v-model:open="showSpecialtyDeleteModal">
        <template #content>
          <div class="bg-surface rounded-lg shadow-xl p-6 max-w-md">
            <div class="flex items-start gap-4">
              <div class="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--color-danger-soft)] flex items-center justify-center">
                <UIcon
                  name="i-lucide-trash-2"
                  class="w-5 h-5 text-danger-accent"
                />
              </div>
              <div class="flex-1">
                <h3 class="text-h1 text-default">
                  {{ t('specialties.delete') }}
                </h3>
                <p class="mt-2 text-caption text-subtle">
                  {{ t('specialties.deleteConfirm', { name: specialtyToDelete ? specialtiesApi.getSpecialtyName(specialtyToDelete) : '' }) }}
                </p>
                <p class="mt-1 text-sm text-subtle">
                  {{ t('specialties.deleteNote') }}
                </p>
              </div>
            </div>
            <div class="flex justify-end gap-2 mt-6">
              <UButton
                variant="ghost"
                @click="showSpecialtyDeleteModal = false"
              >
                {{ t('common.cancel') }}
              </UButton>
              <UButton
                color="error"
                :loading="isDeletingSpecialty"
                @click="handleSpecialtyDelete"
              >
                {{ t('common.delete') }}
              </UButton>
            </div>
          </div>
        </template>
      </UModal>
    </div>

    <div
      v-show="activeView === 'type'"
      class="space-y-6"
    >
      <!-- Filters -->
      <UCard>
        <div class="flex flex-col sm:flex-row gap-4">
          <div class="flex-1">
            <UInput
              v-model="searchQuery"
              icon="i-lucide-search"
              :placeholder="t('catalog.searchPlaceholder')"
            />
          </div>
          <div class="w-full sm:w-64">
            <USelect
              v-model="selectedCategoryId"
              :items="categoryOptions"
              value-key="value"
              label-key="label"
              :placeholder="t('catalog.selectCategory')"
            />
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <USwitch v-model="showRemoved" />
            <span class="text-sm text-muted dark:text-subtle">
              {{ t('catalog.showRemoved') }}
            </span>
          </div>
        </div>
      </UCard>

      <!-- Items list - Grouped View -->
      <div
        v-if="showGroupedView"
        class="space-y-4"
      >
        <!-- Header with expand/collapse buttons -->
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <h2 class="font-semibold text-default">
              {{ t('catalog.items') }}
            </h2>
            <UBadge
              variant="subtle"
              color="neutral"
            >
              {{ countLabel }}
            </UBadge>
          </div>
          <div class="flex gap-2">
            <UButton
              variant="ghost"
              size="xs"
              icon="i-lucide-chevrons-down"
              @click="expandAll"
            >
              {{ t('catalog.expandAll') }}
            </UButton>
            <UButton
              variant="ghost"
              size="xs"
              icon="i-lucide-chevrons-up"
              @click="collapseAll"
            >
              {{ t('catalog.collapseAll') }}
            </UButton>
          </div>
        </div>

        <!-- Loading state -->
        <div
          v-if="catalog.loading.value"
          class="space-y-3"
        >
          <USkeleton class="h-16 w-full" />
          <USkeleton class="h-16 w-full" />
          <USkeleton class="h-16 w-full" />
        </div>

        <!-- Category groups -->
        <template v-else>
          <UCard
            v-for="group in groupedItems"
            :key="group.category.id"
            class="overflow-hidden"
            :ui="isCategoryExpanded(group.category.id) ? undefined : { body: 'hidden' }"
          >
            <!-- Category header (clickable) -->
            <template #header>
              <button
                class="w-full flex items-center justify-between py-1 text-left"
                @click="toggleCategory(group.category.id)"
              >
                <div class="flex items-center gap-3">
                  <UIcon
                    :name="isCategoryExpanded(group.category.id) ? 'i-lucide-chevron-down' : 'i-lucide-chevron-right'"
                    class="w-5 h-5 text-subtle transition-transform"
                  />
                  <UIcon
                    v-if="group.category.icon"
                    :name="group.category.icon"
                    class="w-5 h-5 text-primary-accent"
                  />
                  <span class="font-semibold text-default">
                    {{ catalog.getCategoryName(group.category) }}
                  </span>
                  <UBadge
                    variant="subtle"
                    color="neutral"
                    size="xs"
                  >
                    {{ group.items.length }}
                  </UBadge>
                </div>
              </button>
            </template>

            <!-- Items table (collapsible) -->
            <div
              v-if="isCategoryExpanded(group.category.id)"
              class="overflow-x-auto -mx-4 sm:-mx-6"
            >
              <table class="w-full">
                <thead>
                  <tr class="border-b border-default bg-surface-muted/50">
                    <th class="text-left py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.code') }}
                    </th>
                    <th class="text-left py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.name') }}
                    </th>
                    <th class="text-right py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.price') }}
                    </th>
                    <th class="hidden sm:table-cell text-center py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.vatType') }}
                    </th>
                    <th class="text-center py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.visible') }}
                    </th>
                    <th class="hidden md:table-cell text-center py-2 px-4 font-medium text-muted text-sm">
                      {{ t('catalog.duration') }}
                    </th>
                    <th class="text-right py-2 px-4 font-medium text-muted text-sm" />
                  </tr>
                </thead>
                <tbody class="divide-y divide-[var(--color-border-subtle)]">
                  <CatalogItemRow
                    v-for="item in group.items"
                    :key="item.id"
                    :item="item"
                    variant="grouped"
                    :can-edit="canEditItems"
                    :toggling="isTogglingVisibility(item.id)"
                    :restoring="isRestoring(item.id)"
                    @save-price="savePrice"
                    @toggle-visible="toggleVisible"
                    @edit="openEditModal"
                    @delete="confirmDelete"
                    @restore="restoreItem"
                  />
                </tbody>
              </table>
            </div>
          </UCard>
        </template>
      </div>

      <!-- Items list - Flat View (when category is filtered) -->
      <UCard v-else>
        <template #header>
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <UIcon
                name="i-lucide-list"
                class="w-5 h-5 text-primary-accent"
              />
              <h2 class="font-semibold text-default">
                {{ t('catalog.items') }}
              </h2>
              <UBadge
                variant="subtle"
                color="neutral"
              >
                {{ countLabel }}
              </UBadge>
            </div>
          </div>
        </template>

        <!-- Loading state -->
        <div
          v-if="catalog.loading.value"
          class="space-y-3"
        >
          <USkeleton class="h-12 w-full" />
          <USkeleton class="h-12 w-full" />
          <USkeleton class="h-12 w-full" />
        </div>

        <!-- Empty state -->
        <div
          v-else-if="filteredItems.length === 0"
          class="text-center py-12 text-muted"
        >
          <UIcon
            name="i-lucide-package"
            class="w-12 h-12 mx-auto mb-4 opacity-50"
          />
          <p>{{ isFiltered ? t('catalog.noMatches') : t('catalog.noItems') }}</p>
        </div>

        <!-- Items table -->
        <div
          v-else
          class="overflow-x-auto"
        >
          <table class="w-full">
            <thead>
              <tr class="border-b border-default">
                <th class="text-left py-3 px-4 font-medium text-muted">
                  {{ t('catalog.code') }}
                </th>
                <th class="text-left py-3 px-4 font-medium text-muted">
                  {{ t('catalog.name') }}
                </th>
                <th class="hidden md:table-cell text-left py-3 px-4 font-medium text-muted">
                  {{ t('catalog.category') }}
                </th>
                <th class="text-right py-3 px-4 font-medium text-muted">
                  {{ t('catalog.price') }}
                </th>
                <th class="hidden sm:table-cell text-center py-3 px-4 font-medium text-muted">
                  {{ t('catalog.vatType') }}
                </th>
                <th class="text-center py-3 px-4 font-medium text-muted">
                  {{ t('catalog.visible') }}
                </th>
                <th class="hidden lg:table-cell text-center py-3 px-4 font-medium text-muted">
                  {{ t('catalog.duration') }}
                </th>
                <th class="text-right py-3 px-4 font-medium text-muted" />
              </tr>
            </thead>
            <tbody class="divide-y divide-[var(--color-border-subtle)]">
              <CatalogItemRow
                v-for="item in filteredItems"
                :key="item.id"
                :item="item"
                variant="flat"
                :category-name="getCategoryName(item.category_id)"
                :can-edit="canEditItems"
                :toggling="isTogglingVisibility(item.id)"
                :restoring="isRestoring(item.id)"
                @save-price="savePrice"
                @toggle-visible="toggleVisible"
                @edit="openEditModal"
                @delete="confirmDelete"
                @restore="restoreItem"
              />
            </tbody>
          </table>
        </div>
      </UCard>
    </div>

    <!-- Create/Edit Modal -->
    <CatalogItemModal
      v-model:open="showModal"
      :item="editingItem"
      :categories="catalog.categories.value"
      :loading="isSaving"
      @create="handleCreateItem"
      @save="handleSaveItem"
    />

    <!-- Delete Confirmation Modal -->
    <UModal v-model:open="showDeleteConfirm">
      <template #content>
        <div class="bg-surface rounded-lg shadow-xl p-6 max-w-md">
          <div class="flex items-start gap-4">
            <div class="flex-shrink-0 w-10 h-10 rounded-full bg-[var(--color-danger-soft)] flex items-center justify-center">
              <UIcon
                name="i-lucide-trash-2"
                class="w-5 h-5 text-danger-accent"
              />
            </div>
            <div class="flex-1">
              <h3 class="text-h1 text-default">
                {{ t('catalog.deleteItem') }}
              </h3>
              <p class="mt-2 text-caption text-subtle">
                {{ t('catalog.deleteItemConfirm', { name: itemToDelete ? getItemName(itemToDelete) : '' }) }}
              </p>
              <p class="mt-1 text-sm text-subtle">
                {{ t('catalog.deleteItemNote') }}
              </p>
            </div>
          </div>
          <div class="flex justify-end gap-2 mt-6">
            <UButton
              variant="ghost"
              @click="showDeleteConfirm = false"
            >
              {{ t('common.cancel') }}
            </UButton>
            <UButton
              color="error"
              :loading="isDeleting"
              @click="handleDeleteItem"
            >
              {{ t('common.delete') }}
            </UButton>
          </div>
        </div>
      </template>
    </UModal>
  </div>
</template>
