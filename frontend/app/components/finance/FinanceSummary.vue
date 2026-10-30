<script setup lang="ts">
/**
 * Resumen — the doors to the registers, and where the figures went.
 *
 * This tab used to carry the clinic's money figures (collected today and
 * this month, receivables, the till), contributed by each module through
 * `finance.summary`. Productividad answers the same question with a date
 * range, a comparison against the previous period and a drill-down, so
 * the two screens showed the same number and neither said which was the
 * one to act on.
 *
 * The boundary drawn instead: **Finanzas operates the money, Productividad
 * analyses it.** Anything with a period and a comparison belongs there;
 * what is left here is the way into each register, plus the pointer to
 * where the figures live. `finance.summary` keeps its registrations and
 * stops being rendered — dormant, like `reports.categories`.
 *
 * The doors come from `finance.tabs`, the same registry the page builds
 * its tabs from, so they inherit its permission gating and a module that
 * is not installed contributes no door. No cross-module import (ADR 0001).
 */
const { t } = useI18n()
const { resolve } = useModuleSlots()
const { active: activeModules } = useModules()

/**
 * One door per register. The tab key is the registry id's first segment,
 * exactly as `finanzas.vue` derives it for the URL.
 */
const registers = computed(() =>
  resolve('finance.tabs', {}).map(entry => ({
    key: entry.id.split('.')[0] ?? entry.id,
    label: entry.labelKey ? t(entry.labelKey) : entry.id
  }))
)

// Productividad can be switched off for the whole deployment (ADR 0038);
// until the module list arrives, assume it is there, as the reports tiles do.
const analysisAvailable = computed(() =>
  activeModules.value === null || activeModules.value.some(m => m.name === 'reports')
)
</script>

<template>
  <div class="finance-summary">
    <template v-if="registers.length">
      <p class="text-body text-muted max-w-prose">
        {{ t('finance.summary.intro') }}
      </p>

      <div class="finance-summary-grid">
        <NuxtLink
          v-for="register in registers"
          :key="register.key"
          :to="{ path: '/finanzas', query: { tab: register.key } }"
          class="register-door"
        >
          <span class="truncate">{{ register.label }}</span>
          <UIcon
            name="i-lucide-arrow-right"
            class="w-4 h-4 shrink-0 text-primary-accent"
          />
        </NuxtLink>
      </div>

      <NuxtLink
        v-if="analysisAvailable"
        to="/reports"
        class="text-ui text-primary-accent inline-flex items-center gap-1.5"
      >
        <UIcon
          name="i-lucide-bar-chart-3"
          class="w-4 h-4"
        />
        {{ t('finance.summary.analysis') }}
      </NuxtLink>
    </template>

    <EmptyState
      v-else
      icon="i-lucide-wallet"
      :title="t('finance.summary.empty')"
      :description="t('finance.summary.emptyHint')"
    />
  </div>
</template>

<style scoped>
.finance-summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* Doors size themselves; the row wraps rather than squeezing six labels
   into a tablet's width. */
.finance-summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.register-door {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 56px;
  padding: 12px 16px;
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-token-lg, 12px);
  background: var(--color-surface);
  font-weight: 500;
  transition: background-color 0.15s, border-color 0.15s;
}

.register-door:hover {
  background: var(--color-surface-muted);
  border-color: var(--color-primary-accent);
}
</style>
