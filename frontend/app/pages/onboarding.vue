<script setup lang="ts">
// The welcome of a new clinic's holder, after they set their own password
// (`clinics.onboarding_pending`): review the clinic's details, set its
// hours and cabinets — or leave them for later — and accept the privacy
// agreement. Declining it closes the clinic to them. The global auth
// middleware holds an administrator here until it is over.
//
// The steps are the settings pages themselves, found in the registry: an
// App that is off registers none, and its step is not offered.
import type { SettingsCategoryId } from '~/composables/useSettingsRegistry'
import { PRIVACY_AGREEMENT_VERSION } from '~/config/privacyAgreement'

definePageMeta({ layout: 'guest' })

const { t } = useI18n()
const auth = useAuth()
const api = useApi()
const toast = useToast()
const registry = useSettingsRegistry()

interface SettingsStep {
  key: string
  category: SettingsCategoryId
  path: string
  skippable: boolean
}

const SETTINGS_STEPS: SettingsStep[] = [
  { key: 'clinic', category: 'general', path: 'clinic', skippable: false },
  { key: 'hours', category: 'workspace', path: 'clinic-hours', skippable: true },
  { key: 'cabinets', category: 'workspace', path: 'cabinets', skippable: true }
]

// A clinic already in use whose agreement changed is asked for the new
// one alone: no review of what it set up long ago. Declining it closes
// the clinic to all its staff, and the warning says so.
const renewal = computed(() => auth.privacyRenewal.value)

const steps = computed(() => [
  ...(renewal.value
    ? []
    : SETTINGS_STEPS
        .map(step => ({ ...step, entry: registry.findPage(step.category, step.path) }))
        .filter(step => step.entry?.component)),
  { key: renewal.value ? 'renewal' : 'privacy', skippable: false, entry: null }
])

const index = ref(0)
const step = computed(() => steps.value[Math.min(index.value, steps.value.length - 1)]!)
const skipped = ref<string[]>([])

/** "Configuración → Clínica y horarios → Gabinetes": where a step lives. */
function routeOf(key: string): string {
  const found = steps.value.find(s => s.key === key)
  if (!found?.entry) return ''
  const category = registry.findCategory(found.entry.category)
  return [t('settings.title'), category ? t(category.labelKey) : '', t(found.entry.labelKey)]
    .filter(Boolean)
    .join(' → ')
}

const component = shallowRef<unknown>(null)
watch(step, async (current) => {
  component.value = null
  if (!current.entry?.component) return
  const loaded = await current.entry.component()
  component.value = (loaded as { default?: unknown }).default ?? loaded
}, { immediate: true })

function next(skip = false) {
  const key = step.value.key
  skipped.value = skipped.value.filter(k => k !== key)
  if (skip) skipped.value.push(key)
  index.value += 1
  if (import.meta.client) window.scrollTo({ top: 0 })
}

const working = ref(false)
const confirmingDecline = ref(false)
// Whoever declined and signs in again finds the clinic closed, not the
// welcome: there is nothing left for them to do here.
const declined = ref(auth.clinicDeactivated.value)

async function accept() {
  working.value = true
  try {
    await api.post('/api/v1/auth/clinic/onboarding/accept', { version: PRIVACY_AGREEMENT_VERSION })
    await auth.fetchUser()
    toast.add({ title: t('onboarding.privacy.accepted'), color: 'success' })
    await navigateTo('/')
  } catch {
    toast.add({ title: t('auth.unknownError'), color: 'error' })
  } finally {
    working.value = false
  }
}

async function decline() {
  working.value = true
  try {
    await api.post('/api/v1/auth/clinic/onboarding/decline', {})
    confirmingDecline.value = false
    declined.value = true
  } catch {
    toast.add({ title: t('auth.unknownError'), color: 'error' })
  } finally {
    working.value = false
  }
}

const SECTIONS = ['framework', 'data', 'use', 'custody', 'rights', 'security', 'changes'] as const
</script>

<template>
  <div class="w-full max-w-4xl p-4 sm:p-6">
    <UCard
      v-if="declined"
      class="mx-auto max-w-lg text-center"
      data-testid="onboarding-declined"
    >
      <h1 class="text-h1 text-default">
        {{ t('onboarding.declined.title') }}
      </h1>
      <p class="mt-2 text-sm text-muted">
        {{ t('onboarding.declined.body') }}
      </p>
      <UButton
        class="mt-4"
        color="neutral"
        @click="auth.logout()"
      >
        {{ t('onboarding.declined.exit') }}
      </UButton>
    </UCard>

    <template v-else>
      <div class="mb-4">
        <p
          v-if="steps.length > 1"
          class="text-sm text-muted"
        >
          {{ t('onboarding.progress', { current: index + 1, total: steps.length }) }}
        </p>
        <h1 class="text-h1 text-default">
          {{ t(`onboarding.steps.${step.key}.title`) }}
        </h1>
        <p class="mt-1 text-sm text-muted">
          {{ t(`onboarding.steps.${step.key}.intro`) }}
        </p>
      </div>

      <UAlert
        v-for="key in skipped"
        :key="key"
        class="mb-3"
        color="info"
        variant="subtle"
        icon="i-lucide-info"
        :title="t('onboarding.skipped', { step: t(`onboarding.steps.${key}.title`) })"
        :description="t('onboarding.skippedRoute', { route: routeOf(key) })"
        data-testid="onboarding-skipped"
      />

      <UCard>
        <!-- Client-only: the settings pages register from client plugins. -->
        <ClientOnly v-if="step.entry">
          <component
            :is="component"
            v-if="component"
          />
        </ClientOnly>

        <div
          v-else
          class="max-h-[50vh] space-y-4 overflow-y-auto pr-2 text-sm"
          data-testid="onboarding-privacy"
        >
          <p class="text-xs text-muted">
            {{ t('onboarding.privacy.version', { version: PRIVACY_AGREEMENT_VERSION }) }}
          </p>
          <section
            v-for="section in SECTIONS"
            :key="section"
          >
            <h2 class="font-medium text-default">
              {{ t(`onboarding.privacy.sections.${section}.title`) }}
            </h2>
            <p class="mt-1 text-muted">
              {{ t(`onboarding.privacy.sections.${section}.body`) }}
            </p>
          </section>
        </div>

        <template #footer>
          <div class="flex flex-wrap items-center justify-between gap-2">
            <UButton
              v-if="index > 0"
              color="neutral"
              variant="ghost"
              icon="i-lucide-arrow-left"
              @click="index -= 1"
            >
              {{ t('onboarding.back') }}
            </UButton>
            <span v-else />

            <div
              v-if="step.entry"
              class="flex gap-2"
            >
              <UButton
                v-if="step.skippable"
                color="neutral"
                variant="outline"
                data-testid="onboarding-skip"
                @click="next(true)"
              >
                {{ t('onboarding.skip') }}
              </UButton>
              <UButton
                trailing-icon="i-lucide-arrow-right"
                data-testid="onboarding-next"
                @click="next()"
              >
                {{ t('onboarding.next') }}
              </UButton>
            </div>
            <div
              v-else
              class="flex gap-2"
            >
              <UButton
                color="error"
                variant="outline"
                data-testid="onboarding-decline"
                @click="confirmingDecline = true"
              >
                {{ t('onboarding.privacy.decline') }}
              </UButton>
              <UButton
                :loading="working"
                data-testid="onboarding-accept"
                @click="accept"
              >
                {{ t('onboarding.privacy.accept') }}
              </UButton>
            </div>
          </div>
        </template>
      </UCard>
    </template>

    <UModal
      v-model:open="confirmingDecline"
      :title="t('onboarding.privacy.declineTitle')"
      :description="t(renewal ? 'onboarding.privacy.declineWarningRenewal' : 'onboarding.privacy.declineWarning')"
    >
      <template #footer>
        <div class="flex w-full justify-end gap-2">
          <UButton
            color="neutral"
            variant="ghost"
            @click="confirmingDecline = false"
          >
            {{ t('common.cancel') }}
          </UButton>
          <UButton
            color="error"
            :loading="working"
            data-testid="onboarding-decline-confirm"
            @click="decline"
          >
            {{ t('onboarding.privacy.declineConfirm') }}
          </UButton>
        </div>
      </template>
    </UModal>
  </div>
</template>
