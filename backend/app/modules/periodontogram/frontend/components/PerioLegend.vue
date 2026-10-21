<script setup lang="ts">
/**
 * PerioLegend — what the colours on the periodontogram mean, after the SEPA
 * chart (see docs/technical/periodontogram/color-convention.md). Swatches
 * reuse the chart's own tokens so the key always matches what is drawn.
 */
const { t } = useI18n()

const LINES = [
  { key: 'gingivalMargin', color: 'var(--perio-gm-stroke)' },
  { key: 'probingDepth', color: 'var(--perio-pd-stroke)' }
] as const

const MARKS = [
  { key: 'bleeding', background: 'var(--color-danger-soft)', border: 'var(--color-danger-accent)' },
  { key: 'suppuration', background: 'var(--color-warning-soft)', border: '#EAB308' },
  { key: 'plaque', background: 'var(--color-primary-soft)', border: 'var(--color-primary)' }
] as const
</script>

<template>
  <div
    class="perio-legend flex flex-wrap items-center gap-x-5 gap-y-2 text-caption text-muted"
    data-testid="perio-legend"
  >
    <span class="font-medium text-default">{{ t('periodontogram.legend.title') }}</span>
    <span
      v-for="line in LINES"
      :key="line.key"
      class="inline-flex items-center gap-1.5"
    >
      <i
        class="perio-legend-line"
        :style="{ background: line.color }"
      />
      {{ t(`periodontogram.legend.${line.key}`) }}
    </span>
    <span
      v-for="mark in MARKS"
      :key="mark.key"
      class="inline-flex items-center gap-1.5"
    >
      <i
        class="perio-legend-mark"
        :style="{ background: mark.background, borderColor: mark.border }"
      />
      {{ t(`periodontogram.legend.${mark.key}`) }}
    </span>
    <span class="inline-flex items-center gap-1.5">
      <b class="text-[color:var(--color-danger-accent)]">4</b>
      {{ t('periodontogram.legend.redNumbers') }}
    </span>
  </div>
</template>

<style scoped>
.perio-legend-line {
  display: inline-block;
  width: 16px;
  height: 3px;
  border-radius: 2px;
}

.perio-legend-mark {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 1.5px solid;
  border-radius: 3px;
}
</style>
