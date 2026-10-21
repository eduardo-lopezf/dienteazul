<script setup lang="ts">
/**
 * ToothBoxChart — the box view of the odontogram, as on the paper forms:
 * permanent teeth on the outer rows, primary teeth on the inner ones. Used
 * by `OdontogramChart` (view switch) and by the printable sheet.
 *
 * It draws and reports clicks; what a click does is the chart's business.
 */
import type { Surface, ToothTreatmentView } from '~~/app/types'
import { boxRows, toothBoxState } from '../../utils/boxChart'
import type { ShownDentition } from '../../utils/dentitionLayout'

const props = withDefaults(defineProps<{
  dentition: ShownDentition
  getTreatments: (tooth: number) => ToothTreatmentView[]
  /** The tooth record's whole-tooth condition (`healthy` draws nothing). */
  getCondition?: (tooth: number) => string | null | undefined
  /** Teeth drawn dimmed (not in the mouth). */
  dimmedTeeth?: number[]
  readonly?: boolean
  selectedTooth?: number | null
  hoveredTooth?: number | null
  highlightedTeeth?: number[]
  /** Hide the colour key (the printed sheet has its own). */
  hideLegend?: boolean
}>(), {
  dimmedTeeth: () => [],
  readonly: false,
  selectedTooth: null,
  hoveredTooth: null,
  highlightedTeeth: () => [],
  hideLegend: false
})

const emit = defineEmits<{
  toothClick: [tooth: number]
  surfaceClick: [tooth: number, surface: Surface]
  toothContextMenu: [tooth: number, event: MouseEvent]
  toothHover: [tooth: number | null]
}>()

const { t } = useI18n()

const rows = computed(() => boxRows(props.dentition))
const dimmed = computed(() => new Set(props.dimmedTeeth))
const highlighted = computed(() => new Set(props.highlightedTeeth))
</script>

<template>
  <div class="tooth-box-frame">
    <div class="tooth-box-chart">
      <template
        v-for="(row, index) in rows"
        :key="row.key"
      >
        <!-- The midline between the arches. -->
        <div
          v-if="index > 0 && rows[index - 1]!.upper && !row.upper"
          class="arch-divider"
        />
        <div
          class="box-row"
          :data-row="row.key"
        >
          <div class="box-half box-half-right">
            <ToothBox
              v-for="tooth in row.right"
              :key="tooth"
              :tooth="tooth"
              :state="toothBoxState(getTreatments(tooth), getCondition?.(tooth))"
              :upper="row.upper"
              :dimmed="dimmed.has(tooth)"
              :selected="selectedTooth === tooth"
              :hovered="hoveredTooth === tooth"
              :highlighted="highlighted.has(tooth)"
              :readonly="readonly"
              @surface-click="(s: Surface) => emit('surfaceClick', tooth, s)"
              @tooth-click="emit('toothClick', tooth)"
              @contextmenu="(e: MouseEvent) => emit('toothContextMenu', tooth, e)"
              @mouseenter="emit('toothHover', tooth)"
              @mouseleave="emit('toothHover', null)"
            />
          </div>
          <div class="box-midline" />
          <div class="box-half">
            <ToothBox
              v-for="tooth in row.left"
              :key="tooth"
              :tooth="tooth"
              :state="toothBoxState(getTreatments(tooth), getCondition?.(tooth))"
              :upper="row.upper"
              :dimmed="dimmed.has(tooth)"
              :selected="selectedTooth === tooth"
              :hovered="hoveredTooth === tooth"
              :highlighted="highlighted.has(tooth)"
              :readonly="readonly"
              @surface-click="(s: Surface) => emit('surfaceClick', tooth, s)"
              @tooth-click="emit('toothClick', tooth)"
              @contextmenu="(e: MouseEvent) => emit('toothContextMenu', tooth, e)"
              @mouseenter="emit('toothHover', tooth)"
              @mouseleave="emit('toothHover', null)"
            />
          </div>
        </div>
      </template>

      <div
        v-if="!hideLegend"
        class="box-legend text-caption text-muted"
      >
        <span><i class="swatch swatch-todo" />{{ t('odontogram.boxes.legend.todo') }}</span>
        <span><i class="swatch swatch-done" />{{ t('odontogram.boxes.legend.done') }}</span>
        <span>✕ {{ t('odontogram.boxes.legend.cross') }}</span>
        <span>◯ {{ t('odontogram.boxes.legend.ring') }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tooth-box-frame {
  /* The box size follows the width there is: sixteen teeth and a midline
     across, 36 px at most, never under 14. */
  container-type: inline-size;
  width: 100%;
}

.tooth-box-chart {
  --box-size: clamp(14px, calc((100cqw - 32px) / 16 - 4px), 36px);
  display: flex;
  flex-direction: column;
  /* `safe`: when it cannot fit, it scrolls from the left edge instead of
     losing the third molars off both sides. */
  align-items: safe center;
  gap: 10px;
  overflow-x: auto;
  max-width: 100%;
}

.box-row {
  display: flex;
  align-items: flex-start;
  gap: 4px;
}

.box-half {
  display: flex;
  gap: 4px;
  /* Primary rows have five teeth: they sit against the midline, under the
     permanent teeth they precede. */
  width: calc(8 * var(--box-size) + 7 * 4px);
}

.box-half-right {
  justify-content: flex-end;
}

.box-midline {
  width: 1px;
  align-self: stretch;
  margin: 0 4px;
  background: var(--color-border-strong);
}

.arch-divider {
  width: 100%;
  height: 1px;
  background: var(--color-border-strong);
}

.box-legend {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 16px;
  margin-top: 4px;
}

.swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  margin-right: 4px;
  vertical-align: -1px;
}

.swatch-todo {
  background: #DC2626;
}

.swatch-done {
  background: #2563EB;
}
</style>
