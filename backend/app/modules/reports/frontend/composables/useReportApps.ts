/**
 * Which Apps the reports can read right now.
 *
 * Every figure comes from another App — the agenda, budgets, invoices,
 * payments — and the deployment can switch each off (ADR 0037, ADR 0038).
 * A section whose App is off is hidden, and its endpoint answers 404; it
 * comes back with the App. Until the active-module list has arrived each
 * App counts as on: the API is the real gate.
 *
 * It reads the active-module **state**, not `useModules()`. That one also
 * resolves `useI18n()` for the sidebar labels, and this composable is
 * called from `plugins/slots.client.ts`, where there is no setup function:
 * `useI18n()` threw "Must be called at the top of a `setup` function"
 * during the plugin phase, which is before anything renders — so every
 * screen answered 500 and nothing hydrated, not just the report tiles.
 * The state is filled by the default layout's `ensureLoaded()`.
 */
import type { ActiveModule } from '~~/app/types'

export function useReportApps() {
  const active = useState<ActiveModule[] | null>('modules:active', () => null)

  /** True while every one of `modules` is running. */
  function on(...modules: string[]): boolean {
    const running = active.value
    return running === null || modules.every(name => running.some(module => module.name === name))
  }

  return { on, loaded: computed(() => active.value !== null) }
}
