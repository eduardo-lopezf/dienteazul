<script setup lang="ts">
/**
 * "Exportar" — the report on screen, as a ZIP of CSVs.
 *
 * The file is built by the backend from the same services the screen
 * reads, so the download cannot disagree with what the user is looking
 * at, and the period is whatever the shared filter says.
 *
 * It goes through `$api` rather than a plain link because the session is
 * a bearer token, not a cookie: an `<a href>` would download a 401.
 *
 * Host-level so the collections report can use it too — that screen
 * belongs to `payments` and the Productividad ones to `reports`, and
 * neither may import the other.
 */
interface Props {
  /** API path, without the period — e.g. `/api/v1/reports/billing/export`. */
  endpoint: string
  /** Start of the downloaded filename: `facturacion_2026-09-01_…zip`. */
  stem: string
  /** Anything the report needs besides the period, such as `granularity`. */
  query?: Record<string, string>
}

const props = withDefaults(defineProps<Props>(), {
  query: () => ({})
})

const { t } = useI18n()
const api = useApi()
const toast = useToast()
const { period } = useReportPeriod()

const downloading = ref(false)

async function download() {
  if (downloading.value) return
  downloading.value = true
  try {
    const { from, to } = period.value
    const params = new URLSearchParams({ date_from: from, date_to: to, ...props.query })
    const blob = await api.$api<Blob>(`${props.endpoint}?${params.toString()}`, {
      responseType: 'blob'
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${props.stem}_${from}_${to}.zip`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch {
    // `$api` already reports the failure; this says which action it was.
    toast.add({ title: t('common.exportFailed'), color: 'error' })
  } finally {
    downloading.value = false
  }
}
</script>

<template>
  <UButton
    variant="soft"
    color="neutral"
    icon="i-lucide-download"
    :loading="downloading"
    :aria-label="t('common.export')"
    @click="download"
  >
    {{ t('common.export') }}
  </UButton>
</template>
