<script setup lang="ts">
/**
 * ToothBox — one tooth of the box chart: a square of five surfaces, the
 * tooth number, and a code cell for whole-tooth work (on the outer side:
 * above an upper tooth, below a lower one). See `utils/boxChart.ts`.
 */
import type { Surface } from '~~/app/types'
import { surfaceAt, type BoxSide, type ToothBoxState } from '../../utils/boxChart'
import { NOM_COLORS, type NomTone } from '../../utils/nomColors'

const props = defineProps<{
  tooth: number
  state: ToothBoxState
  upper: boolean
  dimmed?: boolean
  selected?: boolean
  hovered?: boolean
  highlighted?: boolean
  readonly?: boolean
}>()

const emit = defineEmits<{
  surfaceClick: [surface: Surface]
  toothClick: []
  contextmenu: [event: MouseEvent]
  mouseenter: []
  mouseleave: []
}>()

const { t, te } = useI18n()

const SIDES: Array<{ side: BoxSide, points: string }> = [
  { side: 'top', points: '0,0 40,0 28,12 12,12' },
  { side: 'right', points: '40,0 40,40 28,28 28,12' },
  { side: 'bottom', points: '12,28 28,28 40,40 0,40' },
  { side: 'left', points: '0,0 12,12 12,28 0,40' },
  { side: 'center', points: '12,12 28,12 28,28 12,28' }
]

const surfaces = computed(() =>
  SIDES.map(({ side, points }) => {
    const surface = surfaceAt(props.tooth, side)
    return { side, points, surface, paint: props.state.surfaces[surface] ?? null }
  })
)

function codeOf(type: string): string {
  const key = `odontogram.boxes.codes.${type}`
  if (te(key)) return t(key)
  return t(`odontogram.treatments.types.${type}`, type).slice(0, 3)
}

const codes = computed(() =>
  props.state.codes.map(c => ({
    ...c,
    code: codeOf(c.type),
    name: t(`odontogram.treatments.types.${c.type}`, c.type)
  }))
)
const codesTitle = computed(() => codes.value.map(c => c.name).join(', '))

/** Light tones always: the colours are the record's, and print the same. */
function tone(value: NomTone): string {
  return NOM_COLORS[value].light
}

function onSurface(surface: Surface) {
  if (props.readonly) return
  emit('surfaceClick', surface)
}
</script>

<template>
  <div
    class="tooth-box"
    :class="{
      'tooth-box-dimmed': dimmed,
      'tooth-box-selected': selected,
      'tooth-box-hovered': hovered,
      'tooth-box-highlighted': highlighted
    }"
    :data-tooth="tooth"
    @contextmenu="(e: MouseEvent) => emit('contextmenu', e)"
    @mouseenter="emit('mouseenter')"
    @mouseleave="emit('mouseleave')"
  >
    <div
      v-if="upper"
      class="tooth-box-code"
      :title="codesTitle"
    >
      <span
        v-for="(c, i) in codes"
        :key="i"
        :style="{ color: tone(c.tone) }"
      >{{ c.code }}</span>
    </div>
    <button
      v-if="upper"
      type="button"
      class="tooth-box-number"
      :disabled="readonly"
      @click="emit('toothClick')"
    >
      {{ tooth }}
    </button>

    <svg
      viewBox="-4 -4 48 48"
      class="tooth-box-svg"
      role="img"
      :aria-label="String(tooth)"
    >
      <polygon
        v-for="s in surfaces"
        :key="s.side"
        :points="s.points"
        class="box-surface"
        :class="{ painted: s.paint }"
        :style="s.paint ? { fill: tone(s.paint) } : undefined"
        :data-surface="s.surface"
        @click="onSurface(s.surface)"
      >
        <title>{{ t(`odontogram.surfaces.${s.surface}`) }}</title>
      </polygon>
      <circle
        v-if="state.ring"
        cx="20"
        cy="20"
        r="23"
        class="box-ring"
        :stroke="tone(state.ring)"
      />
      <line
        v-if="state.rootLine"
        x1="20"
        y1="-4"
        x2="20"
        y2="44"
        class="box-root-line"
        :stroke="tone(state.rootLine)"
      />
      <g
        v-if="state.cross"
        class="box-cross"
        :stroke="tone(state.cross)"
      >
        <line
          x1="-2"
          y1="-2"
          x2="42"
          y2="42"
        />
        <line
          x1="42"
          y1="-2"
          x2="-2"
          y2="42"
        />
      </g>
    </svg>

    <button
      v-if="!upper"
      type="button"
      class="tooth-box-number"
      :disabled="readonly"
      @click="emit('toothClick')"
    >
      {{ tooth }}
    </button>
    <div
      v-if="!upper"
      class="tooth-box-code"
      :title="codesTitle"
    >
      <span
        v-for="(c, i) in codes"
        :key="i"
        :style="{ color: tone(c.tone) }"
      >{{ c.code }}</span>
    </div>
  </div>
</template>

<style scoped>
.tooth-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: var(--box-size, 36px);
  gap: 2px;
}

.tooth-box-code {
  width: calc(var(--box-size, 36px) - 2px);
  height: 18px;
  border: 1px solid var(--color-border-strong);
  border-radius: 2px;
  font-size: 9px;
  line-height: 16px;
  text-align: center;
  overflow: hidden;
  white-space: nowrap;
}

.tooth-box-code span + span {
  margin-left: 2px;
}

.tooth-box-number {
  font-size: 11px;
  line-height: 14px;
  color: var(--color-text-muted);
  font-variant-numeric: tabular-nums;
}

.tooth-box-svg {
  width: var(--box-size, 36px);
  height: var(--box-size, 36px);
  overflow: visible;
}

.box-surface {
  fill: transparent;
  stroke: var(--color-text-muted);
  stroke-width: 1;
  cursor: pointer;
}

.box-surface:not(.painted):hover {
  fill: var(--color-primary-soft);
}

.box-ring {
  fill: none;
  stroke-width: 2.5;
}

.box-cross line,
.box-root-line {
  stroke-width: 3;
  pointer-events: none;
}

.tooth-box-dimmed {
  opacity: 0.35;
}

.tooth-box-selected .box-surface,
.tooth-box-highlighted .box-surface {
  stroke: var(--color-primary);
  stroke-width: 2;
}

.tooth-box-hovered .tooth-box-number {
  color: var(--color-primary);
  font-weight: 600;
}

@media print {
  .tooth-box-dimmed {
    opacity: 0.45;
  }

  .box-surface:hover {
    fill: transparent;
  }
}
</style>
