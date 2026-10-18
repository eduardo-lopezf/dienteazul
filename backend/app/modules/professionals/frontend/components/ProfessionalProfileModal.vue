<script setup lang="ts">
/**
 * ProfessionalProfileModal — the read-first view of a professional.
 *
 * Clicking a row used to open the edit form, which answered "change
 * this person" when the question is almost always "who is this person".
 * This is the answer to the second: a portrait, the disciplines they
 * practise, and how to reach them, laid out as a mosaic of tiles so the
 * eye can pick one fact without reading a form top to bottom. Editing is
 * one deliberate button away.
 *
 * The photo arrives as an object URL from the page, which fetches it
 * with the Bearer header the endpoint requires — an `<img>` cannot send
 * one itself. Without it, initials.
 */
import type { Professional } from '~~/app/types'
import type { ProfessionalWorkload } from '../composables/useProfessionalWorkload'

const props = defineProps<{
  open: boolean
  professional: Professional | null
  /** Object URL for the portrait; undefined falls back to initials. */
  photoSrc?: string
  /** Hides the edit action for read-only roles. */
  canEdit: boolean
  /** What is assigned to them; absent while it loads or fails. */
  workload?: ProfessionalWorkload
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'edit': [professional: Professional]
}>()

const { t, locale } = useI18n()
const { isPortrait } = useDevice()

/**
 * Held upright there is width to spare and height to fill, so the card
 * takes most of the screen; in landscape the opposite is true and it
 * stays narrow, because the constraint there is the short viewport, not
 * the long one. Orientation decides layout, as everywhere else.
 *
 * Reading `isPortrait` here is safe despite it being false during SSR:
 * this card only ever renders after someone taps a row, long past
 * hydration.
 */
const contentClass = computed(() =>
  isPortrait.value ? 'sm:max-w-[min(92vw,48rem)]' : 'sm:max-w-xl'
)

const initials = computed(() => {
  const parts = (props.professional?.full_name ?? '').trim().split(/\s+/)
  return parts.slice(0, 2).map(part => part[0] ?? '').join('').toUpperCase()
})

const specialtyNames = computed(() =>
  (props.professional?.specialties ?? [])
    .map(s => s.names[locale.value] || s.names.es || s.names.en || '')
    .filter(Boolean)
)

/**
 * What is assigned to them, in the order a clinic asks: who they see, then
 * what is booked, then the work. Only figures some running App supplied.
 */
const workloadStats = computed(() => {
  const w = props.workload
  if (!w) return []
  const stats = [{ key: 'patients', label: t('professionals.workload.patients'), value: w.patients }]
  const keys = [
    ['appointments_upcoming', 'appointmentsUpcoming'],
    ['appointments', 'appointments'],
    ['plans_in_progress', 'plansInProgress'],
    ['treatments_pending', 'treatmentsPending'],
    ['treatments_completed', 'treatmentsCompleted']
  ] as const
  for (const [key, label] of keys) {
    const value = w.counts[key]
    if (value !== undefined) stats.push({ key, label: t(`professionals.workload.${label}`), value })
  }
  return stats
})

/**
 * The mosaic. Only tiles with something to say are built, so a sparse
 * profile reads as a short, dense card rather than a grid of dashes.
 */
const tiles = computed(() => {
  const p = props.professional
  if (!p) return []

  const out: { icon: string, label: string, value: string, href?: string }[] = []

  if (p.license_number) {
    out.push({
      icon: 'i-lucide-badge-check',
      label: t('professionals.licenseNumber'),
      value: p.license_number
    })
  }
  if (p.email) {
    out.push({
      icon: 'i-lucide-mail',
      label: t('professionals.email'),
      value: p.email,
      href: `mailto:${p.email}`
    })
  }
  if (p.phone) {
    out.push({
      icon: 'i-lucide-phone',
      label: t('professionals.phone'),
      value: p.phone,
      href: `tel:${p.phone}`
    })
  }
  out.push({
    icon: p.has_system_access ? 'i-lucide-key-round' : 'i-lucide-lock',
    label: t('professionals.profile.access'),
    value: p.has_system_access
      ? t('professionals.status.hasSystemAccess')
      : t('professionals.profile.noAccess')
  })
  return out
})
</script>

<template>
  <UModal
    :open="open"
    :ui="{ content: contentClass }"
    @update:open="(v: boolean) => emit('update:open', v)"
  >
    <template #content>
      <div
        v-if="professional"
        class="flex h-full flex-col"
      >
        <!-- Portrait band. The tinted strip gives the photo an edge to sit
             against; without it a round image on a white sheet reads as a
             stray element rather than the subject of the card. -->
        <div class="relative">
          <div class="h-24 rounded-t-[var(--radius-xl)] bg-[var(--color-primary-soft)]" />
          <UButton
            icon="i-lucide-x"
            color="neutral"
            variant="ghost"
            class="absolute right-2 top-2"
            :aria-label="t('actions.close', 'Cerrar')"
            @click="emit('update:open', false)"
          />
          <div class="-mt-12 flex flex-col items-center px-6">
            <img
              v-if="photoSrc"
              :src="photoSrc"
              :alt="professional.full_name"
              class="h-24 w-24 rounded-full object-cover ring-4 ring-[var(--color-surface)] shadow-token-md"
            >
            <div
              v-else
              class="flex h-24 w-24 items-center justify-center rounded-full bg-surface-muted text-h1 text-muted ring-4 ring-[var(--color-surface)] shadow-token-md"
            >
              {{ initials }}
            </div>

            <h2 class="mt-3 text-h1 text-default text-center text-pretty">
              {{ professional.full_name }}
            </h2>

            <div class="mt-2 flex flex-wrap items-center justify-center gap-2">
              <UBadge
                color="neutral"
                variant="subtle"
              >
                {{ t(`professionals.types.${professional.professional_type}`) }}
              </UBadge>
              <UBadge
                :color="professional.is_active ? 'success' : 'neutral'"
                variant="subtle"
              >
                {{ t(professional.is_active ? 'professionals.status.active' : 'professionals.status.inactive') }}
              </UBadge>
            </div>

            <!-- Disciplines get their own row of chips rather than a tile:
                 there can be several, and they are what one most often
                 opens this card to check. -->
            <div
              v-if="specialtyNames.length"
              class="mt-3 flex flex-wrap items-center justify-center gap-1.5"
            >
              <UBadge
                v-for="name in specialtyNames"
                :key="name"
                color="primary"
                variant="subtle"
              >
                {{ name }}
              </UBadge>
            </div>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto px-6 pb-2 pt-5">
          <section
            v-if="workloadStats.length"
            class="mb-4"
            data-testid="professional-workload"
          >
            <p class="text-caption text-subtle mb-2">
              {{ t('professionals.workload.title') }}
            </p>
            <dl class="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <div
                v-for="stat in workloadStats"
                :key="stat.key"
                class="rounded-token-lg border border-subtle bg-surface-muted px-3 py-2"
              >
                <dt class="text-caption text-subtle">
                  {{ stat.label }}
                </dt>
                <dd class="text-h2 text-default tabular-nums">
                  {{ stat.value }}
                </dd>
              </div>
            </dl>
            <p class="mt-2 text-caption text-subtle">
              {{ t('professionals.workload.help') }}
            </p>
          </section>

          <!-- The mosaic. Two columns where there is room, one where
               there is not; each tile is one fact.

               A last tile that lands on an odd position has no partner,
               so it takes the whole row rather than leaving a hole beside
               it — which grew noticeable once the card widened in
               portrait. Same rule covers a profile with a single tile. -->
          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:[&>*:nth-child(odd):last-child]:col-span-2">
            <component
              :is="tile.href ? 'a' : 'div'"
              v-for="tile in tiles"
              :key="tile.label"
              :href="tile.href"
              class="flex items-start gap-3 rounded-token-lg border border-subtle bg-surface-muted px-4 py-3 transition-colors"
              :class="tile.href ? 'hover:bg-surface hover:border-default' : ''"
            >
              <UIcon
                :name="tile.icon"
                class="mt-0.5 h-5 w-5 shrink-0 text-subtle"
              />
              <div class="min-w-0">
                <p class="text-caption text-subtle">
                  {{ tile.label }}
                </p>
                <p class="text-ui text-default break-words">
                  {{ tile.value }}
                </p>
              </div>
            </component>
          </div>

          <div
            v-if="professional.notes"
            class="mt-3 rounded-token-lg border border-subtle bg-surface-muted px-4 py-3"
          >
            <p class="text-caption text-subtle">
              {{ t('professionals.notes') }}
            </p>
            <p class="mt-1 text-body text-default whitespace-pre-line">
              {{ professional.notes }}
            </p>
          </div>
        </div>

        <div class="flex items-center justify-end gap-2 border-t border-subtle px-6 py-4">
          <UButton
            color="neutral"
            variant="ghost"
            @click="emit('update:open', false)"
          >
            {{ t('actions.close', 'Cerrar') }}
          </UButton>
          <UButton
            v-if="canEdit"
            color="primary"
            variant="soft"
            icon="i-lucide-pencil"
            @click="emit('edit', professional)"
          >
            {{ t('professionals.edit') }}
          </UButton>
        </div>
      </div>
    </template>
  </UModal>
</template>
