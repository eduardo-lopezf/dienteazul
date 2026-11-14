/**
 * Slot registry — UI extension points.
 *
 * A "slot" is a named location in the UI (e.g. ``patient.detail.tabs``)
 * where any module can inject a component. Module layers register
 * entries at setup time via :func:`registerSlot`; the host page
 * renders them via :component:`<ModuleSlot>`.
 *
 * Canonical slot names (v1):
 *   - ``patient.detail.tabs``
 *   - ``patient.detail.sidebar``
 *   - ``appointment.detail.actions``
 *   - ``dashboard.widgets``
 *   - ``settings.sections``
 *
 * Registrations are stored in :func:`useState` so SSR + HMR preserve
 * them across reloads and every consumer (across layers) sees the
 * same map.
 */

import { markRaw } from 'vue'
import type { Component } from 'vue'
import type { SettingsCategoryId } from './useSettingsRegistry'

export interface SlotEntry<Ctx = unknown> {
  /**
   * Stable identifier for the entry. Required so HMR, re-registration
   * and test cleanup can operate deterministically. Convention:
   * ``<module>.<slot>.<qualifier>`` — e.g. ``billing.patient.detail.sidebar``.
   */
  id: string
  component: Component
  /**
   * Lower numbers render first. Ties resolve in registration order.
   */
  order?: number
  /**
   * Optional permission string (namespaced). When set, the entry
   * renders only when ``usePermissions().can(permission)`` is truthy.
   */
  permission?: string
  /**
   * Optional predicate evaluated at render time with the slot's
   * ``ctx`` prop. Return false to hide the entry for this context.
   */
  condition?: (ctx: Ctx) => boolean
  /**
   * Account tiers (``Clinic.account_tier``) the entry exists for. Unlike
   * ``condition`` it holds everywhere the entry is listed — the home page,
   * Settings → Widgets and the workspace layout — because a tier is a fact
   * of the clinic, not of one render. Hidden until the clinic is loaded.
   */
  tiers?: string[]
  // ---- settings.sections extensions ---------------------------------
  // Optional fields used by the ``settings.sections`` slot to place the
  // entry inside the categorised settings IA. Other slots ignore them,
  // except ``labelKey`` / ``descriptionKey``, which also name a tab
  // (``tab``) and a widget (``widget``).
  /** Settings category bucket. Default: ``'modules'`` (fallback). */
  category?: SettingsCategoryId
  /** Synonyms surfaced by Cmd-K search (lowercase substrings). */
  searchKeywords?: string[]
  /** i18n key for the label shown in nav + search. */
  labelKey?: string
  /** i18n key for one-line description. */
  descriptionKey?: string
  /** Renders an amber dot when truthy at resolve time. */
  attention?: () => boolean
  /**
   * List this entry in Settings → Apps → Widgets, with an example
   * (ADR 0040). Opt-in: a label alone does not make a widget — tabs and
   * settings pages carry one too. The component must then honour
   * ``useWidgetPreview()``.
   */
  widget?: boolean
  // ---- tab slots ------------------------------------------------------
  /**
   * For slots that render as tabs (``patient.detail.tabs``): the tab's
   * value — what ``?tab=`` carries, so it must stay stable — and its
   * icon. The label comes from ``labelKey``.
   */
  tab?: { value: string, icon: string }
  // ---- data hook ------------------------------------------------------
  /**
   * Data the host fetches on the entry's behalf and hands back through
   * ``ctx`` — one bulk request for a whole page of rows instead of one
   * per rendered row. The host passes its own API client, because
   * ``useApi()`` can only be created during a component's setup and this
   * runs later. The slot's documentation says what ``input`` and the
   * result are; the host knows neither the endpoint nor the module.
   */
  loader?: (api: ReturnType<typeof useApi>, input?: unknown) => Promise<unknown>
}

type SlotMap = Record<string, SlotEntry[]>

function useSlotState() {
  return useState<SlotMap>('modules:slots', () => ({}))
}

export function registerSlot(name: string, entry: SlotEntry): void {
  const state = useSlotState()
  const current = state.value[name] || []
  // Replace any existing entry with the same id — keeps HMR idempotent.
  const deduped = current.filter(e => e.id !== entry.id)
  // Mark the component raw so Vue stops wrapping it in a reactive
  // proxy when the slot map updates. Components are immutable
  // references — making them reactive triggers a noisy "Vue received
  // a Component that was made a reactive object" warning every time
  // the entry hits an `<component :is>` render.
  const sealed: SlotEntry = { ...entry, component: markRaw(entry.component) }
  state.value = {
    ...state.value,
    [name]: [...deduped, sealed]
  }
}

export function unregisterSlot(name: string, id: string): void {
  const state = useSlotState()
  const current = state.value[name]
  if (!current) return
  state.value = {
    ...state.value,
    [name]: current.filter(e => e.id !== id)
  }
}

export function clearSlots(name?: string): void {
  const state = useSlotState()
  state.value = name ? { ...state.value, [name]: [] } : {}
}

function tierAllows(entry: SlotEntry, tier: string | undefined): boolean {
  return !entry.tiers || (!!tier && entry.tiers.includes(tier))
}

function currentTier(): string | undefined {
  return useState<{ account_tier?: string } | null>('clinic:current', () => null).value?.account_tier
}

/**
 * Every registration, with the slot it went into. For screens that
 * describe the registry itself (Settings → Apps → Widgets) rather than
 * render one slot.
 */
export function listSlotEntries(): Array<{ slot: string, entry: SlotEntry }> {
  const state = useSlotState()
  const tier = currentTier()
  return Object.entries(state.value).flatMap(([slot, entries]) =>
    entries.filter(entry => tierAllows(entry, tier)).map(entry => ({ slot, entry }))
  )
}

export function resolveSlot<Ctx = unknown>(
  name: string,
  ctx: Ctx,
  opts: { can: (p: string) => boolean }
): SlotEntry<Ctx>[] {
  const state = useSlotState()
  const entries = (state.value[name] || []) as SlotEntry<Ctx>[]
  const tier = currentTier()
  return [...entries]
    .filter((entry) => {
      if (!tierAllows(entry as SlotEntry, tier)) return false
      if (entry.permission && !opts.can(entry.permission)) return false
      if (entry.condition && !entry.condition(ctx)) return false
      return true
    })
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
}

/**
 * Composable wrapper. Named ``useModuleSlots`` to avoid colliding with
 * Vue 3's built-in ``useSlots`` which is also auto-imported by Nuxt.
 */
export function useModuleSlots() {
  const { can } = usePermissions()

  function resolve<Ctx = unknown>(name: string, ctx: Ctx): SlotEntry<Ctx>[] {
    return resolveSlot<Ctx>(name, ctx, { can })
  }

  return {
    register: registerSlot,
    unregister: unregisterSlot,
    clear: clearSlots,
    resolve
  }
}
