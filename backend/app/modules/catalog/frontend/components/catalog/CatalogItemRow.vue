<script setup lang="ts">
/**
 * One treatment row of the catalog management screen.
 *
 * A component of its own so the screen stays responsive with the whole
 * catalog on it. Inline in the page, every change of page state — opening a
 * modal, switching tab, saving one price — re-evaluated the template of every
 * row (several hundred, in both tabs), and the browser froze for seconds. As
 * a component, a row re-renders only when its own props change.
 *
 * That only holds if the parent passes stable props: plain values and the
 * item object, and handlers by reference (`@edit="openEditModal"`), never an
 * inline closure, which is a new function each render.
 *
 * `variant`: `grouped` (list view, grouped by category), `flat` (list view
 * filtered to one category, adds the category column) or `specialty`
 * (specialty view: no VAT, duration or actions).
 */
import type { TreatmentCatalogItem, VatTypeBrief } from '~~/app/types'

const props = defineProps<{
  item: TreatmentCatalogItem
  variant: 'grouped' | 'flat' | 'specialty'
  categoryName?: string
  canEdit: boolean
  toggling: boolean
  restoring?: boolean
}>()

const emit = defineEmits<{
  savePrice: [item: TreatmentCatalogItem, price: number]
  toggleVisible: [item: TreatmentCatalogItem]
  edit: [item: TreatmentCatalogItem]
  delete: [item: TreatmentCatalogItem]
  restore: [item: TreatmentCatalogItem]
}>()

const { t, locale } = useI18n()

const name = computed(() =>
  props.item.names[locale.value] || props.item.names.es || props.item.names.en || props.item.internal_code
)

const cell = computed(() => (props.variant === 'flat' ? 'py-3 px-4' : 'py-2.5 px-4'))

function vatLabel(vatType: VatTypeBrief | undefined): string {
  if (!vatType) return '-'
  return vatType.names[locale.value] || vatType.names.es || vatType.names.en || '-'
}

// Color based on rate: 0% = green, < 10% = yellow, >= 10% = red
function vatColor(vatType: VatTypeBrief | undefined): 'neutral' | 'success' | 'warning' | 'error' {
  if (!vatType) return 'neutral'
  if (vatType.rate === 0) return 'success'
  if (Number(vatType.rate) < 10) return 'warning'
  return 'error'
}

function onSavePrice(price: number) {
  emit('savePrice', props.item, price)
}
</script>

<template>
  <tr class="hover:bg-surface-muted">
    <td :class="cell">
      <span class="font-mono text-sm text-muted dark:text-subtle">
        {{ item.internal_code }}
      </span>
    </td>

    <!-- Specialty view -->
    <template v-if="variant === 'specialty'">
      <td :class="cell">
        <span class="font-medium text-default">
          {{ name }}
        </span>
        <UBadge
          v-if="!item.is_active"
          variant="subtle"
          color="error"
          class="ml-2"
          size="xs"
        >
          {{ t('common.inactive') }}
        </UBadge>
      </td>
      <td :class="['hidden sm:table-cell text-muted dark:text-subtle', cell]">
        {{ categoryName }}
      </td>
      <td :class="['text-center', cell]">
        <UCheckbox
          :model-value="item.is_visible !== false"
          :disabled="!canEdit || toggling"
          @update:model-value="emit('toggleVisible', item)"
        />
      </td>
      <td :class="['text-right font-medium', cell]">
        <CatalogPriceCell
          :item="item"
          :editable="canEdit && !item.deleted_at"
          @save="onSavePrice"
        />
      </td>
    </template>

    <!-- List view, grouped or filtered to one category -->
    <template v-else>
      <td :class="cell">
        <span class="font-medium text-default">
          {{ name }}
        </span>
        <UBadge
          v-if="item.is_system"
          variant="subtle"
          color="info"
          class="ml-2"
          size="xs"
        >
          {{ t('catalog.system') }}
        </UBadge>
        <UBadge
          v-if="item.deleted_at"
          variant="subtle"
          color="error"
          class="ml-2"
          size="xs"
        >
          {{ t('catalog.removed') }}
        </UBadge>
        <UBadge
          v-else-if="!item.is_active"
          variant="subtle"
          color="warning"
          class="ml-2"
          size="xs"
        >
          {{ t('common.inactive') }}
        </UBadge>
      </td>
      <td
        v-if="variant === 'flat'"
        :class="['hidden md:table-cell text-muted dark:text-subtle', cell]"
      >
        {{ categoryName }}
      </td>
      <td :class="['text-right font-medium', cell]">
        <CatalogPriceCell
          :item="item"
          :editable="canEdit && !item.deleted_at"
          @save="onSavePrice"
        />
      </td>
      <td :class="['hidden sm:table-cell text-center', cell]">
        <UBadge
          :color="vatColor(item.vat_type)"
          variant="subtle"
          size="xs"
        >
          {{ vatLabel(item.vat_type) }}
        </UBadge>
      </td>
      <td :class="['text-center', cell]">
        <UCheckbox
          :model-value="item.is_visible !== false"
          :disabled="!canEdit || toggling || Boolean(item.deleted_at)"
          @update:model-value="emit('toggleVisible', item)"
        />
      </td>
      <td
        :class="[
          variant === 'flat' ? 'hidden lg:table-cell' : 'hidden md:table-cell',
          'text-center text-muted dark:text-subtle',
          cell
        ]"
      >
        {{ item.default_duration_minutes ? `${item.default_duration_minutes} min` : '-' }}
      </td>
      <td :class="['text-right', cell]">
        <div
          v-if="canEdit"
          class="flex items-center justify-end gap-1"
        >
          <UButton
            v-if="item.deleted_at"
            icon="i-lucide-undo-2"
            size="xs"
            variant="ghost"
            color="neutral"
            :loading="restoring"
            @click="emit('restore', item)"
          >
            {{ t('catalog.restore') }}
          </UButton>
          <template v-else>
            <UButton
              icon="i-lucide-pencil"
              size="xs"
              variant="ghost"
              color="neutral"
              :aria-label="t('actions.edit')"
              @click="emit('edit', item)"
            />
            <UButton
              icon="i-lucide-trash-2"
              size="xs"
              variant="ghost"
              color="error"
              :aria-label="t('actions.delete')"
              @click="emit('delete', item)"
            />
          </template>
        </div>
      </td>
    </template>
  </tr>
</template>
