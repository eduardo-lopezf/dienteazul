<script setup lang="ts">
import { safeRedirect } from '~/utils/session'

definePageMeta({
  layout: 'guest'
})

const { t } = useI18n()
const auth = useAuth()
const toast = useToast()
const route = useRoute()

// Why the user is here, when it was not their choice. Without it an
// expired session reads as a crash: one moment a patient, the next a
// login form. The reason is the backend's own (ADR 0062) — `revoked`
// means the session was ended somewhere else, which waiting will not
// undo, so it must not read as "it timed out".
const sessionNotice = computed(() => {
  switch (route.query.reason) {
    case 'idle': return t('auth.sessionIdle')
    case 'expired': return t('auth.sessionExpired')
    case 'revoked': return t('auth.sessionRevoked')
    default: return ''
  }
})

// The reference of the refusal that ended the session: one string that
// finds its line in the operator's log (ADR 0059, ADR 0060). Shown only
// alongside a notice, and only if it looks like a request id — it
// arrives in a URL anybody can write.
const sessionReference = computed(() => {
  const ref = route.query.ref
  const value = Array.isArray(ref) ? ref[0] : ref
  return typeof value === 'string' && /^[\w-]{1,64}$/.test(value) ? value : ''
})

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

const isLoading = ref(false)

const formState = reactive({
  email: '',
  password: ''
})
const errorMessage = ref('')
const emailError = ref('')
const passwordError = ref('')

function validate(): boolean {
  emailError.value = ''
  passwordError.value = ''

  const email = formState.email.trim()
  if (!email) {
    emailError.value = t('auth.emailRequired')
  } else if (!EMAIL_RE.test(email)) {
    emailError.value = t('auth.emailInvalid')
  }

  if (!formState.password) {
    passwordError.value = t('auth.passwordRequired')
  }

  return !emailError.value && !passwordError.value
}

function mapError(err: unknown): string {
  const e = err as {
    statusCode?: number
    status?: number
    message?: string
    data?: { message?: string }
  }
  const status = e.statusCode ?? e.status

  switch (status) {
    case 400:
    case 401:
      return t('auth.invalidCredentials')
    case 403:
      return t('auth.accountInactive')
    case 422:
      return t('auth.invalidCredentials')
    case 429:
      return t('auth.tooManyAttempts')
  }

  if (!status || status === 0 || (e.message && /network|fetch|failed/i.test(e.message))) {
    return t('auth.networkError')
  }
  if (status >= 500) {
    return t('auth.serverError')
  }
  return t('auth.unknownError')
}

async function onSubmit() {
  errorMessage.value = ''
  if (!validate()) return

  isLoading.value = true
  try {
    await auth.login({
      email: formState.email.trim(),
      password: formState.password
    })
  } catch (error: unknown) {
    console.error('Login error:', error)
    errorMessage.value = mapError(error)
    return
  } finally {
    isLoading.value = false
  }

  // Only the credentials check is guarded above. Past this line the
  // session exists, so a failure here is not a login failure: navigating
  // fetches the app manifest, which 404s for a client still running the
  // build a deploy replaced. Inside the `try` that surfaced as "unexpected
  // error, try again" next to the success toast — telling an already
  // authenticated user to retry, and hiding the real cause.
  toast.add({
    title: t('auth.loginSuccess'),
    color: 'success'
  })

  // Back to where the session ended, if it ended somewhere. `safeRedirect`
  // refuses anything outside this app: the parameter arrives in the URL.
  await navigateTo(safeRedirect(route.query.redirect) ?? '/')
}

watch(() => formState.email, () => {
  if (emailError.value) emailError.value = ''
  if (errorMessage.value) errorMessage.value = ''
})
watch(() => formState.password, () => {
  if (passwordError.value) passwordError.value = ''
  if (errorMessage.value) errorMessage.value = ''
})
</script>

<template>
  <div class="w-full max-w-[400px] p-6">
    <!-- Brand -->
    <div class="text-center mb-6">
      <img
        src="/dienteazul-icon.svg"
        alt="Dental Demo"
        width="56"
        height="56"
        class="mx-auto mb-3"
      >
      <h1 class="text-h1 text-default">
        Dental Demo
      </h1>
      <p class="text-caption text-muted mt-1">
        {{ t('app.tagline') }}
      </p>
    </div>

    <UCard>
      <!--
        The form has **no submit button** — the control below is a
        `type="button"`. A browser only submits a form implicitly when it has
        one, so this form cannot be submitted by the browser at all: not on
        Enter, not by a password manager, and not in the moment before Vue
        hydrates. Vue drives both paths itself, from the button's `@click` and
        the fields' `@keydown.enter`.

        What this replaces: the submit button used to be disabled until
        `onMounted` ran, which prevented the same stray submission but made the
        one page a user must always be able to use depend on hydration
        finishing. When it did not finish, the form accepted typing and the
        button stayed dead — only a reload got them in. `method="post"` stays
        as the last line of defence for the credentials.
      -->
      <form
        method="post"
        class="space-y-4"
        @submit.prevent="onSubmit"
      >
        <div
          v-if="sessionNotice && !errorMessage"
          class="alert-surface-info rounded-token-md px-3 py-2 flex items-start gap-2"
          role="status"
        >
          <UIcon
            name="i-lucide-clock"
            class="w-4 h-4 mt-0.5 shrink-0"
            :style="{ color: 'var(--color-info-accent)' }"
          />
          <span class="text-body">
            {{ sessionNotice }}
            <span
              v-if="sessionReference"
              class="text-caption block opacity-70"
            >{{ t('auth.sessionReference', { reference: sessionReference }) }}</span>
          </span>
        </div>

        <!-- Error message — pastel danger (DESIGN §2.4) -->
        <div
          v-if="errorMessage"
          class="alert-surface-danger rounded-token-md px-3 py-2 flex items-start gap-2"
          role="alert"
        >
          <UIcon
            name="i-lucide-alert-circle"
            class="w-4 h-4 mt-0.5 shrink-0"
            :style="{ color: 'var(--color-danger-accent)' }"
          />
          <span class="text-body">
            {{ errorMessage }}
          </span>
        </div>

        <UFormField
          :label="t('auth.email')"
          name="email"
          :error="emailError || undefined"
        >
          <UInput
            v-model="formState.email"
            type="email"
            class="w-full"
            :placeholder="t('auth.email')"
            icon="i-lucide-mail"
            autocomplete="email"
            :disabled="isLoading"
            @keydown.enter="onSubmit"
          />
        </UFormField>

        <UFormField
          :label="t('auth.password')"
          name="password"
          :error="passwordError || undefined"
        >
          <UInput
            v-model="formState.password"
            type="password"
            class="w-full"
            :placeholder="t('auth.password')"
            icon="i-lucide-lock"
            autocomplete="current-password"
            :disabled="isLoading"
            @keydown.enter="onSubmit"
          />
        </UFormField>

        <UButton
          type="button"
          color="primary"
          variant="soft"
          block
          :loading="isLoading"
          :disabled="isLoading"
          @click="onSubmit"
        >
          {{ t('auth.loginButton') }}
        </UButton>
      </form>
    </UCard>

    <DemoCredentialsHint />

    <p class="text-center text-caption text-subtle mt-6">
      &copy; {{ new Date().getFullYear() }} Dental Demo
    </p>
  </div>
</template>
