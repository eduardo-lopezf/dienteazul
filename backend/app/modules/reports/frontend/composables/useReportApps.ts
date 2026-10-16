/**
 * Which Apps the reports can read right now.
 *
 * Every figure comes from another App — the agenda, budgets, invoices,
 * payments — and the deployment can switch each off (ADR 0037, ADR 0038).
 * A section whose App is off is hidden, and its endpoint answers 404; it
 * comes back with the App. Until the active-module list has arrived each
 * App counts as on: the API is the real gate.
 */
export function useReportApps() {
  const { active, isActive } = useModules()

  /** True while every one of `modules` is running. */
  function on(...modules: string[]): boolean {
    return active.value === null || modules.every(module => isActive(module))
  }

  return { on, loaded: computed(() => active.value !== null) }
}
