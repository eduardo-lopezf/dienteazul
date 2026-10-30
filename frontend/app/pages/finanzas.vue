<script setup lang="ts">
/**
 * Finanzas — the money side of a patient's care, in one place.
 *
 * Cobros, Presupuestos and Facturas used to be three sidebar entries.
 * They are one entry and three tabs, in the order money actually moves
 * backwards from: what has been collected, what has been quoted, what
 * has been invoiced.
 *
 * The page owns no knowledge of those modules. Each registers its tab in
 * the `finance.tabs` slot, so uninstalling `billing` simply removes its
 * tab — the mount authority stays `core_module.state` (ADR 0018) and no
 * cross-module import is introduced (ADR 0001).
 */
definePageMeta({ middleware: 'auth' })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { resolve } = useModuleSlots()

const entries = computed(() => resolve('finance.tabs', {}))

/**
 * The tab key in the URL is the owning module's name, taken from the
 * registry id (`payments.finance.tabs` → `payments`). The full id is
 * unique but reads as plumbing in an address bar, and the module name is
 * both stable and what a person would guess.
 */
/**
 * Registros leads, and it is the page's own tab rather than a module's:
 * it lists the way into every register, and no module should own the
 * index of its siblings.
 *
 * It used to be `Resumen` and carried the clinic's money figures,
 * contributed through `finance.summary`. Productividad answers the same
 * question with a period, a comparison and a drill-down, so the two
 * screens showed the same number and neither said which to act on —
 * ADR 0063 gave the figures to Productividad and left the doors here.
 */
const items = computed(() => [
  {
    // Renamed from `resumen` when the tab stopped carrying figures
    // (ADR 0063). An old `?tab=resumen` link is not broken by it: an
    // unknown key falls back to the first tab, which is this one.
    value: 'registros',
    label: t('finance.summary.tab'),
    component: resolveComponent('FinanceSummary')
  },
  ...entries.value.map(entry => ({
    value: entry.id.split('.')[0] ?? entry.id,
    label: entry.labelKey ? t(entry.labelKey) : entry.id,
    component: entry.component
  }))
])

/**
 * The active tab lives in the URL so a deep link, a browser back and the
 * redirects from the old `/payments`, `/budgets` and `/invoices` routes
 * all land where they mean to.
 */
const active = computed<string>({
  get() {
    const wanted = route.query.tab
    const known = items.value.map(i => i.value)
    if (typeof wanted === 'string' && known.includes(wanted)) return wanted
    return known[0] ?? ''
  },
  set(value) {
    router.replace({ query: { ...route.query, tab: value } })
  }
})
</script>

<template>
  <div>
    <PageHeader :title="t('nav.finance')" />

    <!-- Client-only: the tabs come from `slots.client.ts` registrations,
         which do not exist during SSR. Rendered on the server, this block
         always took the empty-state branch, and hydration then put the
         tabs *inside* the empty state's centred box — every finance list
         read centred, under a 48 px gap, with a hydration-mismatch
         warning in the console. -->
    <ClientOnly>
      <UTabs
        v-model="active"
        :items="items"
        :ui="{ content: 'overflow-visible' }"
      >
        <template #content="{ item }">
          <div class="mt-4 overflow-visible">
            <component :is="item.component" />
          </div>
        </template>
      </UTabs>

      <template #fallback>
        <USkeleton class="h-10 w-full rounded-md" />
      </template>
    </ClientOnly>
  </div>
</template>
