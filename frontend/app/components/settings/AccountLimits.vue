<script setup lang="ts">
/**
 * What the clinic's account allows it, beside what it uses: its users
 * and the disk its files take. A limit the account does not have shows
 * as "no limit".
 */
import type { ApiResponse } from '~/types'

interface ClinicLimits {
  users: number
  /** The holder and the users the clinic may add; `null` is no limit. */
  users_limit: number | null
  storage_bytes: number
  storage_limit_bytes: number | null
}

const { t, locale } = useI18n()
const api = useApi()

const limits = ref<ClinicLimits | null>(null)

onMounted(async () => {
  try {
    limits.value = (await api.get<ApiResponse<ClinicLimits>>('/api/v1/auth/clinic/limits')).data
  } catch {
    // Informative only: without it the page is what it was.
  }
})

const megabytes = (bytes: number) =>
  new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(bytes / (1024 * 1024))

const rows = computed(() => {
  const held = limits.value
  if (!held) return []
  return [
    {
      key: 'users',
      icon: 'i-lucide-users',
      used: held.users,
      limit: held.users_limit,
      text: held.users_limit === null
        ? t('settings.workspace.limits.usersUnlimited', { used: held.users })
        : t('settings.workspace.limits.users', { used: held.users, limit: held.users_limit })
    },
    {
      key: 'storage',
      icon: 'i-lucide-hard-drive',
      used: held.storage_bytes,
      limit: held.storage_limit_bytes,
      text: held.storage_limit_bytes === null
        ? t('settings.workspace.limits.storageUnlimited', { used: megabytes(held.storage_bytes) })
        : t('settings.workspace.limits.storage', {
            used: megabytes(held.storage_bytes),
            limit: megabytes(held.storage_limit_bytes)
          })
    }
  ]
})

const percent = (used: number, limit: number) => Math.min(100, Math.round((used / limit) * 100))
</script>

<template>
  <UCard
    v-if="limits"
    data-testid="account-limits"
  >
    <h2 class="font-medium text-default">
      {{ t('settings.workspace.limits.title') }}
    </h2>
    <p class="text-sm text-muted">
      {{ t('settings.workspace.limits.intro') }}
    </p>
    <div class="mt-4 grid gap-4 sm:grid-cols-2">
      <div
        v-for="row in rows"
        :key="row.key"
        class="space-y-2"
      >
        <div class="flex items-center gap-2 text-sm">
          <UIcon
            :name="row.icon"
            class="size-4 text-muted"
          />
          <span class="font-medium text-default">{{ t(`settings.workspace.limits.${row.key}Label`) }}</span>
          <span class="ml-auto text-muted">{{ row.text }}</span>
        </div>
        <UProgress
          v-if="row.limit !== null"
          :model-value="percent(row.used, row.limit)"
          :color="row.used >= row.limit ? 'error' : 'primary'"
          size="sm"
        />
      </div>
    </div>
  </UCard>
</template>
