import type { ApiResponse, PatientAlert } from '~~/app/types'
import { sampleAlerts } from '../utils/previewSamples'

export function usePatientAlerts(patientId: Ref<string | undefined>) {
  const api = useApi()

  const alerts = ref<PatientAlert[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // Computed properties
  const hasAlerts = computed(() => alerts.value.length > 0)

  const criticalAlerts = computed(() =>
    alerts.value.filter(a => a.severity === 'critical')
  )

  const highAlerts = computed(() =>
    alerts.value.filter(a => a.severity === 'high')
  )

  const hasCriticalAlerts = computed(() => criticalAlerts.value.length > 0)

  // Alert type helpers
  const hasAllergy = computed(() =>
    alerts.value.some(a => a.type === 'allergy')
  )

  const isPregnant = computed(() =>
    alerts.value.some(a => a.type === 'pregnancy')
  )

  const isOnAnticoagulants = computed(() =>
    alerts.value.some(a => a.type === 'anticoagulant')
  )

  const hasAnesthesiaReaction = computed(() =>
    alerts.value.some(a => a.type === 'anesthesia_reaction')
  )

  // Inside a widget example (Settings → Widgets) the alerts are made up
  // and nothing is fetched (ADR 0040).
  const preview = useWidgetPreview()

  async function fetchAlerts() {
    if (!patientId.value) return
    if (preview) {
      alerts.value = sampleAlerts()
      return
    }

    isLoading.value = true
    error.value = null

    try {
      const response = await api.get<ApiResponse<{ alerts: PatientAlert[] }>>(
        `/api/v1/patients_clinical/patients/${patientId.value}/alerts`
      )
      alerts.value = response.data.alerts
    } catch (e) {
      error.value = 'Failed to fetch alerts'
      console.error('Failed to fetch patient alerts:', e)
    } finally {
      isLoading.value = false
    }
  }

  // Get icon for alert type
  function getAlertIcon(type: PatientAlert['type']): string {
    const icons: Record<PatientAlert['type'], string> = {
      asa: 'i-lucide-shield-plus',
      allergy: 'i-lucide-alert-triangle',
      pregnancy: 'i-lucide-baby',
      lactating: 'i-lucide-heart',
      anticoagulant: 'i-lucide-droplet',
      anesthesia_reaction: 'i-lucide-syringe',
      systemic_disease: 'i-lucide-activity'
    }
    return icons[type] || 'i-lucide-alert-circle'
  }

  // Get color for severity
  function getSeverityColor(severity: PatientAlert['severity']): string {
    const colors: Record<PatientAlert['severity'], string> = {
      critical: 'error',
      high: 'warning',
      medium: 'info',
      low: 'neutral'
    }
    return colors[severity] || 'neutral'
  }

  // Watch patientId and fetch when it changes
  watch(patientId, (newId) => {
    if (newId) {
      fetchAlerts()
    } else {
      alerts.value = []
    }
  }, { immediate: true })

  return {
    alerts,
    isLoading,
    error,
    // Computed
    hasAlerts,
    criticalAlerts,
    highAlerts,
    hasCriticalAlerts,
    hasAllergy,
    isPregnant,
    isOnAnticoagulants,
    hasAnesthesiaReaction,
    // Methods
    fetchAlerts,
    getAlertIcon,
    getSeverityColor
  }
}
