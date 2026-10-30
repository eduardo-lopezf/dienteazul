<script setup lang="ts">
/**
 * Opens a report's printable page in a tab.
 *
 * A PDF to glance at and print, so it is *opened*, not downloaded. The
 * tab is reserved **synchronously on the tap** and filled once the file
 * arrives: Safari on iPad drops a popup opened after a network
 * round-trip, which is the same trap `usePrescriptions` documents.
 *
 * It fetches through `$api` because the session is a bearer token, not a
 * cookie — a plain link would open a 401.
 */
interface Props {
  /** API path, without the period — e.g. `/api/v1/reports/summary.pdf`. */
  endpoint: string
  label: string
}

const props = defineProps<Props>()

const { t } = useI18n()
const api = useApi()
const toast = useToast()
const { period } = useReportPeriod()

const loading = ref(false)

async function open() {
  if (loading.value) return
  loading.value = true
  const tab = window.open('', '_blank')
  try {
    const { from, to } = period.value
    const params = new URLSearchParams({ date_from: from, date_to: to })
    const blob = await api.$api<Blob>(`${props.endpoint}?${params.toString()}`, {
      responseType: 'blob'
    })
    const url = URL.createObjectURL(blob)
    if (tab) tab.location.href = url
    else window.location.href = url
  } catch {
    tab?.close()
    toast.add({ title: t('reports.summaryPdf.failed'), color: 'error' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <UButton
    variant="soft"
    color="neutral"
    icon="i-lucide-file-text"
    :loading="loading"
    :aria-label="label"
    @click="open"
  >
    {{ label }}
  </UButton>
</template>
