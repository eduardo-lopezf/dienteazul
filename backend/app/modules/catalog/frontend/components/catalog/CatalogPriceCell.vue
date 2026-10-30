<script setup lang="ts">
/**
 * The price of one treatment, edited where it is read.
 *
 * Setting prices is the first real job on this screen: a clinic arrives to
 * 136 seeded treatments carrying demonstration prices, and every one of them
 * had to be changed through a modal — open, find the field, save, wait for the
 * list, find the next row. The number is right there in the table, so it is
 * the number you type into.
 *
 * Deliberately one cell at a time. A "raise everything 10%" is a different
 * feature with a different blast radius, and it is not what a clinic does on
 * its first afternoon: it walks its own price list and copies it across.
 *
 * Treatments billed in stages are not editable here — `sessions` must add up
 * to the total, and a cell cannot ask about the stages. They keep the form,
 * and the cell says so instead of failing on save.
 */
import type { TreatmentCatalogItem } from '~~/app/types'

const props = defineProps<{
  item: TreatmentCatalogItem
  /** False while the user lacks `catalog.write`, or the row is removed. */
  editable: boolean
}>()

const emit = defineEmits<{ save: [price: number] }>()

const { t } = useI18n()
// Only the formatter: a cell is drawn once per row, and `useCatalog()` set up
// the whole catalog composable (state, API client, toasts) for each of them.
const { symbol, format } = useCurrency()
const price = computed(() =>
  props.item.default_price == null ? '-' : format(props.item.default_price)
)

const editing = ref(false)
const saving = ref(false)
/**
 * What is in the box.
 *
 * `UInput type="number"` declares a string model and hands back a **number**
 * once it has been typed into, so the raw ref holds either and `draft` is the
 * string view the rest of the component reads. Without it, `commit()` called
 * `.trim()` on a number and the keypress died in an unhandled handler error —
 * with the value typed, the row unchanged, and nothing said.
 */
const rawDraft = ref<string | number>('')
const draft = computed<string>({
  get: () => (rawDraft.value === null || rawDraft.value === undefined ? '' : String(rawDraft.value)),
  set: (value) => {
    rawDraft.value = value
  }
})
const input = ref<{ $el?: HTMLElement } | HTMLInputElement | null>(null)

/** Billed in stages: the total is the sum of its sessions, not a free number. */
const hasSessions = computed(() => (props.item.sessions?.length ?? 0) > 0)
const canEdit = computed(() => props.editable && !hasSessions.value)

async function open() {
  if (!canEdit.value || saving.value) return
  draft.value = props.item.default_price == null ? '' : String(props.item.default_price)
  editing.value = true
  await nextTick()
  const el = (input.value as { $el?: HTMLElement })?.$el?.querySelector('input')
    ?? (input.value as HTMLInputElement | null)
  el?.focus()
  el?.select()
}

function cancel() {
  editing.value = false
}

/**
 * Commit, unless nothing changed or the value is not a price.
 *
 * An empty box is not zero — a treatment with no price set is a different
 * thing from a free one, and the plan screen already distinguishes them — so
 * it is treated as "no change" rather than silently pricing the treatment at
 * nothing.
 */
async function commit() {
  if (!editing.value) return
  const raw = draft.value.trim().replace(',', '.')
  const value = Number(raw)

  if (!raw || Number.isNaN(value) || value < 0) {
    editing.value = false
    return
  }
  if (Math.abs(value - Number(props.item.default_price ?? NaN)) < 0.005) {
    editing.value = false
    return
  }

  saving.value = true
  try {
    emit('save', value)
  } finally {
    saving.value = false
    editing.value = false
  }
}
</script>

<template>
  <div class="flex items-center justify-end gap-1">
    <UInput
      v-if="editing"
      ref="input"
      v-model="draft"
      type="number"
      step="0.01"
      min="0"
      size="xs"
      class="w-32"
      :aria-label="t('catalog.price')"
      data-catalog-price-input
      @keyup.enter="commit"
      @keyup.esc="cancel"
      @blur="commit"
    >
      <template #trailing>
        <span class="text-xs text-dimmed">{{ symbol }}</span>
      </template>
    </UInput>

    <UTooltip
      v-else-if="hasSessions && editable"
      :text="t('catalog.priceFromSessions')"
    >
      <span class="inline-flex items-center gap-1 font-medium">
        {{ price }}
        <UIcon
          name="i-lucide-layers"
          class="size-3.5 text-dimmed"
        />
      </span>
    </UTooltip>

    <button
      v-else-if="canEdit"
      type="button"
      class="catalog-price-edit font-medium"
      :title="t('catalog.editPrice')"
      :disabled="saving"
      @click="open"
    >
      {{ price }}
    </button>

    <span
      v-else
      class="font-medium"
    >
      {{ price }}
    </span>
  </div>
</template>

<style scoped>
/* The native spinner steals the room the currency suffix needs, and nobody
   prices a crown by clicking an arrow 400 times. */
:deep(input[type="number"]) {
  appearance: textfield;
}

:deep(input[type="number"]::-webkit-outer-spin-button),
:deep(input[type="number"]::-webkit-inner-spin-button) {
  appearance: none;
  margin: 0;
}

/* A cell that can be typed into should look like one before it is clicked,
   without turning a price list into a form. */
.catalog-price-edit {
  border-radius: 0.25rem;
  padding: 0.125rem 0.375rem;
  border: 1px solid transparent;
  transition: border-color 0.12s ease, background-color 0.12s ease;
}

.catalog-price-edit:hover:not(:disabled) {
  border-color: var(--color-border-subtle);
  background: var(--color-surface-muted);
}

.catalog-price-edit:focus-visible {
  outline: none;
  border-color: var(--color-primary-accent);
}

.catalog-price-edit:disabled {
  opacity: 0.6;
}
</style>
