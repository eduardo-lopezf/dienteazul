<script setup lang="ts">
/**
 * One article's ledger: why its figure is what it is.
 *
 * This is the whole point of ADR 0065 made visible. A stock number
 * nobody can explain is a stock number nobody trusts, and the first
 * question anybody asks of a wrong one is "who took them". The answer is
 * a list of movements, newest first, each with its reason and note.
 */
import type { InventoryMovement } from '../composables/useInventory'
import { quantity } from '../composables/useInventory'

const props = defineProps<{
  open: boolean
  itemId: string | null
  itemName: string
  baseUnit: string
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const { t, locale } = useI18n()
const { movements } = useInventory()

const rows = ref<InventoryMovement[]>([])
const isLoading = ref(false)

watch(
  () => [props.open, props.itemId] as const,
  async ([open, itemId]) => {
    if (!open || !itemId) return
    isLoading.value = true
    try {
      rows.value = (await movements({ item_id: itemId, page_size: 50 })).data
    } finally {
      isLoading.value = false
    }
  },
  { immediate: true }
)

function formatMoment(iso: string): string {
  return new Date(iso).toLocaleString(locale.value, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function signed(value: string): string {
  const amount = quantity(value)
  return `${amount > 0 ? '+' : ''}${amount}`
}
</script>

<template>
  <USlideover
    :open="open"
    :title="itemName"
    :description="t('inventory.history.subtitle')"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #body>
      <USkeleton
        v-if="isLoading"
        class="h-40 w-full"
      />

      <p
        v-else-if="rows.length === 0"
        class="rounded-token-md border border-default bg-default p-6 text-center text-subtle"
      >
        {{ t('inventory.history.empty') }}
      </p>

      <ul
        v-else
        class="divide-y divide-default"
      >
        <li
          v-for="movement in rows"
          :key="movement.id"
          class="flex items-start justify-between gap-3 py-3"
        >
          <div class="min-w-0">
            <p class="text-sm font-medium">
              {{ t(`inventory.reasons.${movement.reason}`) }}
            </p>
            <p class="text-xs text-subtle">
              {{ formatMoment(movement.created_at) }} · {{ movement.location_name }}
              <template v-if="movement.lot_code">
                · {{ t('inventory.lot') }} {{ movement.lot_code }}
              </template>
            </p>
            <p
              v-if="movement.note"
              class="mt-1 text-xs text-toned"
            >
              {{ movement.note }}
            </p>
          </div>
          <span
            class="shrink-0 text-sm font-semibold tabular-nums"
            :class="quantity(movement.quantity_base) > 0 ? 'text-success' : 'text-error'"
          >
            {{ signed(movement.quantity_base) }} {{ baseUnit }}
          </span>
        </li>
      </ul>
    </template>
  </USlideover>
</template>
