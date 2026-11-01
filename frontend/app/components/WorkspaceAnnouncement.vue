<script setup lang="ts">
/**
 * The operator's notice to this clinic — a maintenance window, something
 * new, a survey — shown beside the clinic's name at the top of the
 * workspace, and meant to be easy to miss: muted text, no colour, one
 * line. "Ocultar" puts it away on this device.
 *
 * A notice is read in a popover. A **survey** is a questionnaire of up to
 * ten questions, so the line shows its title ("Encuesta de Calidad") and
 * opens a modal instead: yes/no questions, each with room to explain, and
 * open ones answered in prose.
 *
 * Every question is optional and the answers are saved together. Sending
 * it again corrects what it holds rather than counting twice, so the form
 * opens on what this member already said.
 *
 * Read on load and every ten minutes; the newest one in force shows.
 */
import type { ApiResponse } from '~/types'

interface Question {
  id: string
  kind: 'yes_no' | 'open'
  text: string
}

interface Answer {
  question_id: string
  yes: boolean | null
  comment: string | null
}

interface Announcement {
  id: string
  kind: 'maintenance' | 'feature' | 'survey'
  message: string
  starts_at: string
  ends_at: string | null
  /** What the banner shows for a survey; `null` for the other kinds. */
  title: string | null
  questions: Question[] | null
  /** What this member has already answered. */
  answers: Answer[]
}

const { t, locale } = useI18n()
const api = useApi()
const toast = useToast()

const STORAGE_KEY = 'announcements:dismissed'
const REFRESH_MS = 10 * 60 * 1000
const MAX_COMMENT = 1000

const announcements = ref<Announcement[]>([])
const dismissed = ref<string[]>([])

function readDismissed(): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    return Array.isArray(stored) ? stored.filter(id => typeof id === 'string') : []
  } catch {
    return []
  }
}

const shown = computed(() => announcements.value.find(a => !dismissed.value.includes(a.id)) ?? null)

async function load() {
  try {
    announcements.value = (await api.get<ApiResponse<Announcement[]>>('/api/v1/announcements')).data
    // Forget what was put away and no longer shows, so the list stays short.
    const live = new Set(announcements.value.map(a => a.id))
    dismissed.value = dismissed.value.filter(id => live.has(id))
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dismissed.value))
  } catch {
    // A notice is never worth an error on screen.
  }
}

function dismiss(id: string) {
  dismissed.value = [...dismissed.value, id]
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(dismissed.value))
  } catch {
    // Without storage it stays hidden until the page is loaded again.
  }
}

const ICONS = {
  maintenance: 'i-lucide-wrench',
  feature: 'i-lucide-sparkles',
  survey: 'i-lucide-clipboard-list'
} as const

/** The line itself: a survey's title, or the message. */
const headline = computed(() =>
  shown.value?.kind === 'survey' ? (shown.value.title ?? shown.value.message) : shown.value?.message
)

const until = computed(() =>
  shown.value?.ends_at
    ? new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
        .format(new Date(shown.value.ends_at))
    : null
)

// --- Answering the questionnaire -------------------------------------------

const open = ref(false)
const sending = ref(false)
/** Keyed by question id, so reordering the survey never shifts an answer. */
const draft = ref<Record<string, { yes: boolean | null, comment: string }>>({})
/** Which yes/no questions have their "explain" box showing. */
const expanded = ref<Set<string>>(new Set())

function openSurvey(survey: Announcement) {
  const given = new Map(survey.answers.map(a => [a.question_id, a]))
  draft.value = Object.fromEntries(
    (survey.questions ?? []).map(q => [
      q.id,
      { yes: given.get(q.id)?.yes ?? null, comment: given.get(q.id)?.comment ?? '' }
    ])
  )
  // A question already explained opens showing the explanation.
  expanded.value = new Set(
    (survey.questions ?? []).filter(q => given.get(q.id)?.comment).map(q => q.id)
  )
  open.value = true
}

function choose(id: string, yes: boolean) {
  const current = draft.value[id]
  if (!current) return
  // Clicking the chosen answer again clears it: an answer nobody gave is
  // not the same as a no.
  draft.value = { ...draft.value, [id]: { ...current, yes: current.yes === yes ? null : yes } }
}

function toggleComment(id: string) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

const answeredCount = computed(
  () => Object.values(draft.value).filter(a => a.yes !== null || a.comment.trim()).length
)

async function send(survey: Announcement) {
  if (sending.value) return
  sending.value = true
  try {
    const answers = (survey.questions ?? []).map(q => ({
      question_id: q.id,
      yes: draft.value[q.id]?.yes ?? null,
      comment: draft.value[q.id]?.comment.trim() || null
    }))
    await api.put(`/api/v1/announcements/${survey.id}/answers`, { answers })
    toast.add({ title: t('announcements.survey.sent'), color: 'success' })
    open.value = false
    // Re-read so the form reopens on what was just saved.
    await load()
  } catch {
    toast.add({ title: t('announcements.survey.failed'), color: 'error' })
  } finally {
    sending.value = false
  }
}

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  dismissed.value = readDismissed()
  load()
  timer = setInterval(load, REFRESH_MS)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <!-- A survey: the line opens the questionnaire. -->
  <template v-if="shown && shown.kind === 'survey'">
    <button
      type="button"
      class="ml-3 flex min-w-0 max-w-[40vw] items-center gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-caption text-subtle hover:text-muted"
      :aria-label="t('announcements.kind.survey')"
      data-testid="workspace-announcement"
      @click="openSurvey(shown)"
    >
      <UIcon
        :name="ICONS.survey"
        class="size-3.5 shrink-0"
      />
      <span class="hide-on-phone truncate">{{ headline }}</span>
    </button>

    <UModal
      v-model:open="open"
      :title="shown.title ?? t('announcements.kind.survey')"
      :description="shown.message"
      :ui="{ content: 'max-w-xl' }"
    >
      <template #body>
        <form
          id="survey"
          class="space-y-5"
          @submit.prevent="send(shown)"
        >
          <p class="text-caption text-subtle">
            {{ t('announcements.survey.optional') }}
            {{ t('announcements.survey.noPatientData') }}
          </p>

          <div
            v-for="(question, index) in shown.questions ?? []"
            :key="question.id"
            class="space-y-2"
            :data-testid="`survey-question-${index}`"
          >
            <p class="text-default">
              <span class="text-subtle">{{ index + 1 }}.</span> {{ question.text }}
            </p>

            <!-- Yes or no, and room to explain either. -->
            <template v-if="question.kind === 'yes_no'">
              <div class="flex flex-wrap items-center gap-2">
                <UButton
                  size="xs"
                  :color="draft[question.id]?.yes === true ? 'primary' : 'neutral'"
                  :variant="draft[question.id]?.yes === true ? 'solid' : 'outline'"
                  :data-testid="`survey-yes-${index}`"
                  @click="choose(question.id, true)"
                >
                  {{ t('announcements.survey.yes') }}
                </UButton>
                <UButton
                  size="xs"
                  :color="draft[question.id]?.yes === false ? 'primary' : 'neutral'"
                  :variant="draft[question.id]?.yes === false ? 'solid' : 'outline'"
                  :data-testid="`survey-no-${index}`"
                  @click="choose(question.id, false)"
                >
                  {{ t('announcements.survey.no') }}
                </UButton>
                <UButton
                  size="xs"
                  variant="link"
                  color="neutral"
                  class="px-0"
                  @click="toggleComment(question.id)"
                >
                  {{ expanded.has(question.id)
                    ? t('announcements.survey.collapse')
                    : t('announcements.survey.expand') }}
                </UButton>
              </div>
              <UTextarea
                v-if="expanded.has(question.id) && draft[question.id]"
                v-model="draft[question.id]!.comment"
                :maxlength="MAX_COMMENT"
                :rows="2"
                autoresize
                :placeholder="t('announcements.survey.expandPlaceholder')"
                class="w-full"
              />
            </template>

            <!-- An open question: prose only. -->
            <UTextarea
              v-else-if="draft[question.id]"
              v-model="draft[question.id]!.comment"
              :maxlength="MAX_COMMENT"
              :rows="3"
              autoresize
              :placeholder="t('announcements.survey.openPlaceholder')"
              class="w-full"
              :data-testid="`survey-open-${index}`"
            />
          </div>
        </form>
      </template>

      <template #footer>
        <div class="flex w-full items-center justify-between gap-2">
          <span class="text-caption text-subtle">
            {{ t('announcements.survey.progress', {
              done: answeredCount,
              total: (shown.questions ?? []).length
            }) }}
          </span>
          <div class="flex gap-2">
            <UButton
              color="neutral"
              variant="ghost"
              data-testid="workspace-announcement-dismiss"
              @click="open = false; dismiss(shown.id)"
            >
              {{ t('announcements.dismiss') }}
            </UButton>
            <UButton
              type="submit"
              form="survey"
              :loading="sending"
              data-testid="survey-send"
            >
              {{ t('announcements.survey.send') }}
            </UButton>
          </div>
        </div>
      </template>
    </UModal>
  </template>

  <!-- Everything else: the quiet line, read in place. -->
  <UPopover
    v-else-if="shown"
    :content="{ align: 'start' }"
  >
    <button
      type="button"
      class="ml-3 flex min-w-0 max-w-[40vw] items-center gap-1.5 rounded-[var(--radius-sm)] px-1.5 py-0.5 text-caption text-subtle hover:text-muted"
      :aria-label="t(`announcements.kind.${shown.kind}`)"
      data-testid="workspace-announcement"
    >
      <UIcon
        :name="ICONS[shown.kind]"
        class="size-3.5 shrink-0"
      />
      <span class="hide-on-phone truncate">{{ headline }}</span>
    </button>

    <template #content>
      <div class="max-w-xs space-y-2 p-3 text-sm">
        <div class="flex items-center gap-1.5 text-caption text-muted">
          <UIcon
            :name="ICONS[shown.kind]"
            class="size-3.5"
          />
          {{ t(`announcements.kind.${shown.kind}`) }}
        </div>
        <p class="text-default">
          {{ shown.message }}
        </p>
        <p
          v-if="until"
          class="text-caption text-subtle"
        >
          {{ t('announcements.until', { date: until }) }}
        </p>
        <div class="flex justify-end">
          <UButton
            size="xs"
            color="neutral"
            variant="ghost"
            data-testid="workspace-announcement-dismiss"
            @click="dismiss(shown.id)"
          >
            {{ t('announcements.dismiss') }}
          </UButton>
        </div>
      </div>
    </template>
  </UPopover>
</template>
