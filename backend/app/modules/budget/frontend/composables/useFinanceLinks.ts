/**
 * What Budgets and payments can link to right now.
 *
 * Patients, the treatment catalog and Professionals belong to other Apps,
 * which the deployment can switch off (ADR 0037, ADR 0038). This App runs
 * either way: with Patients off it only reads, with the catalog off no
 * line is added, with Professionals off none is assigned. These flags
 * decide whether a screen offers the action or says why it cannot.
 *
 * Until the active-module list has arrived each flag is true: the API is
 * the real gate. `payments` and `billing` depend on `budget`, so its
 * layer is always there for them.
 */
export function useFinanceLinks() {
  const { active, isActive } = useModules()

  const available = (module: string) =>
    computed(() => active.value === null || isActive(module))

  return {
    patientsAvailable: available('patients'),
    catalogAvailable: available('catalog'),
    professionalsAvailable: available('professionals')
  }
}
