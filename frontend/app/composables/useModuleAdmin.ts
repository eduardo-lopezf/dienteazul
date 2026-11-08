/**
 * Admin-only composable for the module lifecycle API.
 *
 * Distinct from `useModules` (backend-driven nav for the sidebar). This
 * one powers the Settings pages over the App catalog —
 * /settings/apps (the list, its status, the doctor report and each app's
 * operation log), /settings/widgets and /settings/apis.
 */

import type {
  ApiResponse,
  AppInfo,
  ModuleDoctorReport,
  ModuleInfo,
  ModuleOperationLogEntry,
  ModuleStatus
} from '~/types'

const MODULES_BASE = '/api/v1/modules'

export function useModuleAdmin() {
  const api = useApi()
  const { t, te } = useI18n()
  // Taken here, in setup: composables cannot be reached for after an await.
  const activeModules = useModules()
  const auth = useAuth()

  const apps = ref<AppInfo[]>([])
  const modules = ref<ModuleInfo[]>([])
  const status = ref<ModuleStatus | null>(null)
  const doctor = ref<ModuleDoctorReport | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [appsResp, listResp, statusResp, doctorResp] = await Promise.all([
        api.get<ApiResponse<AppInfo[]>>('/api/v1/apps'),
        api.get<ApiResponse<ModuleInfo[]>>(MODULES_BASE),
        api.get<ApiResponse<ModuleStatus>>(`${MODULES_BASE}/-/status`),
        api.get<ApiResponse<ModuleDoctorReport>>(`${MODULES_BASE}/-/doctor`)
      ])
      apps.value = appsResp.data
      modules.value = listResp.data
      status.value = statusResp.data
      doctor.value = doctorResp.data
    } catch (err: unknown) {
      error.value = extractMessage(err)
      throw err
    } finally {
      loading.value = false
    }
  }

  /** Just the catalog: all the Widgets and APIs pages need. */
  async function refreshApps(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      apps.value = (await api.get<ApiResponse<AppInfo[]>>('/api/v1/apps')).data
    } catch (err: unknown) {
      error.value = extractMessage(err)
      throw err
    } finally {
      loading.value = false
    }
  }

  /**
   * Switch on an App the clinic was offered. It takes effect at once —
   * what a clinic has is checked per request — so the menu and the
   * permissions are read again.
   */
  async function enableApp(name: string): Promise<string[]> {
    const resp = await api.post<ApiResponse<{ also_enabled: string[] }>>(
      `/api/v1/apps/${encodeURIComponent(name)}/enable`
    )
    await Promise.all([refreshApps(), activeModules.ensureLoaded(true), auth.fetchUser()])
    return resp.data.also_enabled
  }

  /**
   * Switch an optional module of an App on or off for the clinic
   * (ADR 0066). Like an App, it takes effect at once, so the menu, the
   * slots and the permissions are read again.
   */
  async function setOptionalModule(app: string, module: string, on: boolean): Promise<void> {
    await api.post<ApiResponse<{ name: string, enabled: boolean }>>(
      `/api/v1/apps/${encodeURIComponent(app)}/modules/${encodeURIComponent(module)}/${on ? 'enable' : 'disable'}`
    )
    await Promise.all([refreshApps(), activeModules.ensureLoaded(true), auth.fetchUser()])
  }

  function appTitle(name: string): string {
    const key = `settings.apps.catalog.${name}.title`
    return te(key) ? t(key) : name
  }

  async function operations(name: string, limit = 20): Promise<ModuleOperationLogEntry[]> {
    const resp = await api.get<ApiResponse<ModuleOperationLogEntry[]>>(
      `${MODULES_BASE}/${encodeURIComponent(name)}/-/operations?limit=${limit}`
    )
    return resp.data
  }

  return {
    apps,
    modules,
    status,
    doctor,
    loading,
    error,
    refresh,
    refreshApps,
    enableApp,
    setOptionalModule,
    appTitle,
    operations
  }
}

function extractMessage(err: unknown): string {
  const e = err as { data?: { detail?: string, message?: string }, message?: string }
  return e?.data?.detail || e?.data?.message || e?.message || 'unknown error'
}
