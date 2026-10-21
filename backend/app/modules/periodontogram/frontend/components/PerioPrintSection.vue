<script setup lang="ts">
/**
 * PerioPrintSection — the periodontogram on the printed odontogram sheet.
 *
 * Registered into the `odontogram.print.sections` slot (ctx
 * `{ patientId }`): the sheet belongs to the odontogram, which knows
 * nothing of this module (ADR 0041). Prints the latest **closed** session
 * that recorded something (`hasRecordedData`) — a draft is not a finished
 * examination, and one closed empty has nothing to show — as a compact
 * table that fits an A4 page, in the SEPA colours (docs/technical/periodontogram/
 * color-convention.md): depth over 3 mm and keratinized gingiva of 2 mm or
 * less in red, bleeding red, suppuration yellow, plaque blue. With no such
 * session it prints nothing.
 */
import type { PerioSite, PerioSnapshotDetail, PerioTimelineResponse, PerioTooth, SiteCode } from '../types'
import { PALATAL_SITES, VESTIBULAR_SITES } from '../types'
import { isNarrowKeratinizedGingiva, isPathologicalDepth } from '../utils/perioConvention'
import { hasRecordedData } from '../utils/perioSnapshot'

const props = defineProps<{ ctx: { patientId: string } }>()

const { t, locale } = useI18n()
const api = useApi()

const snapshot = ref<PerioSnapshotDetail | null>(null)

onMounted(async () => {
  try {
    const timeline = await api.get<{ data: PerioTimelineResponse }>(
      `/api/v1/periodontogram/patients/${props.ctx.patientId}/timeline`
    )
    // Newest first, the first session that recorded something: one closed
    // without charting has nothing to print.
    for (const entry of [...timeline.data.dates].reverse()) {
      const detail = await api.get<{ data: PerioSnapshotDetail }>(
        `/api/v1/periodontogram/snapshots/${entry.snapshot_id}`
      )
      if (hasRecordedData(detail.data)) {
        snapshot.value = detail.data
        return
      }
    }
  } catch {
    // Without the periodontogram the sheet is still a complete odontogram.
    snapshot.value = null
  }
})

const ARCHES = [
  { key: 'upper', right: [18, 17, 16, 15, 14, 13, 12, 11], left: [21, 22, 23, 24, 25, 26, 27, 28], inner: 'palatal' },
  { key: 'lower', right: [48, 47, 46, 45, 44, 43, 42, 41], left: [31, 32, 33, 34, 35, 36, 37, 38], inner: 'lingual' }
] as const

const teeth = computed(() => new Map((snapshot.value?.teeth ?? []).map(tooth => [tooth.tooth_number, tooth])))

function siteOf(tooth: PerioTooth | undefined, code: SiteCode): PerioSite | undefined {
  return tooth?.sites.find(site => site.site_code === code)
}

type SiteRow = 'probing' | 'margin' | 'bleeding' | 'suppuration' | 'plaque'
const SITE_ROWS: SiteRow[] = ['probing', 'margin', 'bleeding', 'suppuration', 'plaque']

function siteText(site: PerioSite | undefined, row: SiteRow): string {
  if (!site) return '·'
  if (row === 'probing') return site.probing_depth_mm == null ? '·' : String(site.probing_depth_mm)
  if (row === 'margin') return site.gingival_margin_mm == null ? '·' : String(site.gingival_margin_mm)
  const on = row === 'bleeding' ? site.bleeding_on_probing : row === 'suppuration' ? site.suppuration : site.plaque
  return on ? '●' : '·'
}

function siteClass(site: PerioSite | undefined, row: SiteRow): string {
  if (!site) return ''
  if (row === 'probing') return isPathologicalDepth(site.probing_depth_mm) ? 'mark-red' : ''
  if (row === 'bleeding') return site.bleeding_on_probing ? 'mark-red' : ''
  if (row === 'suppuration') return site.suppuration ? 'mark-yellow' : ''
  if (row === 'plaque') return site.plaque ? 'mark-blue' : ''
  return ''
}

function toothText(tooth: PerioTooth | undefined, field: 'mobility' | 'furcation_buccal' | 'furcation_lingual' | 'keratinized_gingiva_mm'): string {
  const value = tooth?.[field]
  return value == null || value === '0' ? '·' : String(value)
}

const date = computed(() =>
  snapshot.value
    ? new Date(snapshot.value.closed_at ?? snapshot.value.recorded_at).toLocaleDateString(locale.value)
    : ''
)
</script>

<template>
  <section
    v-if="snapshot"
    class="perio-print"
    data-testid="perio-print-section"
  >
    <h2 class="perio-print-title">
      {{ t('periodontogram.print.title') }}
      <span class="perio-print-date">{{ t('periodontogram.print.closedOn', { date }) }}</span>
    </h2>

    <p
      v-if="snapshot.indices"
      class="perio-print-indices"
    >
      <span>{{ t('periodontogram.print.bleeding') }} <strong>{{ snapshot.indices.bop_pct.toFixed(1) }}%</strong></span>
      <span>{{ t('periodontogram.print.plaque') }} <strong>{{ snapshot.indices.pi_pct.toFixed(1) }}%</strong></span>
      <span>{{ t('periodontogram.print.cal') }} <strong>{{ snapshot.indices.cal_mean_mm.toFixed(1) }} mm</strong></span>
      <span>{{ t('periodontogram.print.deepPockets') }} <strong>{{ snapshot.indices.deep_pockets_count }}</strong></span>
    </p>

    <table
      v-for="arch in ARCHES"
      :key="arch.key"
      class="perio-print-table"
    >
      <thead>
        <tr>
          <th class="row-label">
            {{ t(`periodontogram.print.${arch.key}`) }}
          </th>
          <th
            v-for="n in [...arch.right, ...arch.left]"
            :key="n"
            :class="{ midline: n === arch.left[0], absent: teeth.get(n) && !teeth.get(n)!.is_present }"
          >
            {{ n }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="field in (['mobility', 'keratinized_gingiva_mm', 'furcation_buccal'] as const)"
          :key="field"
        >
          <th class="row-label">
            {{ t(`periodontogram.print.rows.${field}`) }}
          </th>
          <td
            v-for="n in [...arch.right, ...arch.left]"
            :key="n"
            :class="{
              'midline': n === arch.left[0],
              'mark-red': field === 'keratinized_gingiva_mm' && isNarrowKeratinizedGingiva(teeth.get(n)?.keratinized_gingiva_mm)
            }"
          >
            {{ toothText(teeth.get(n), field) }}
          </td>
        </tr>
        <template
          v-for="side in (['buccal', arch.inner] as const)"
          :key="side"
        >
          <tr
            v-for="row in SITE_ROWS"
            :key="`${side}-${row}`"
            :class="{ 'side-start': row === 'probing' }"
          >
            <th class="row-label">
              {{ t(`periodontogram.print.rows.${row}`) }}
              <span class="side-tag">{{ t(`periodontogram.print.side.${side}`) }}</span>
            </th>
            <td
              v-for="n in [...arch.right, ...arch.left]"
              :key="n"
              :class="{ midline: n === arch.left[0] }"
            >
              <span
                v-for="code in (side === 'buccal' ? VESTIBULAR_SITES : PALATAL_SITES)"
                :key="code"
                class="site"
                :class="siteClass(siteOf(teeth.get(n), code), row)"
              >{{ teeth.get(n)?.is_present === false ? '–' : siteText(siteOf(teeth.get(n), code), row) }}</span>
            </td>
          </tr>
        </template>
        <tr>
          <th class="row-label">
            {{ t('periodontogram.print.rows.furcation_lingual') }}
          </th>
          <td
            v-for="n in [...arch.right, ...arch.left]"
            :key="n"
            :class="{ midline: n === arch.left[0] }"
          >
            {{ toothText(teeth.get(n), 'furcation_lingual') }}
          </td>
        </tr>
      </tbody>
    </table>

    <p class="perio-print-key">
      <span class="mark-red">4</span> {{ t('periodontogram.print.keyRed') }} ·
      <span class="mark-red">●</span> {{ t('periodontogram.legend.bleeding') }} ·
      <span class="mark-yellow">●</span> {{ t('periodontogram.legend.suppuration') }} ·
      <span class="mark-blue">●</span> {{ t('periodontogram.legend.plaque') }}
    </p>
  </section>
</template>

<style scoped>
.perio-print {
  margin-top: 16px;
  break-inside: avoid-page;
}

.perio-print-title {
  font-size: 14px;
  font-weight: 700;
  margin: 16px 0 6px;
  border-bottom: 1px solid #999;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}

.perio-print-date {
  font-size: 11px;
  font-weight: 400;
  color: #555;
}

.perio-print-indices {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 11px;
  margin-bottom: 6px;
}

.perio-print-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 8.5px;
  margin-bottom: 8px;
  font-variant-numeric: tabular-nums;
}

.perio-print-table th,
.perio-print-table td {
  border: 1px solid #ccc;
  padding: 1px 0;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
}

.perio-print-table thead th {
  background: #f2f2f2;
  font-size: 9px;
}

.perio-print-table .row-label {
  width: 92px;
  text-align: left;
  padding-left: 4px;
  font-weight: 500;
  background: #fafafa;
}

.side-tag {
  color: #777;
  font-size: 7.5px;
  margin-left: 2px;
}

.side-start th,
.side-start td {
  border-top: 1.5px solid #888;
}

.midline {
  border-left: 1.5px solid #666 !important;
}

.absent {
  color: #aaa;
  text-decoration: line-through;
}

.site {
  display: inline-block;
  width: 33%;
}

.mark-red {
  color: #DC2626;
  font-weight: 700;
}

.mark-yellow {
  color: #CA8A04;
}

.mark-blue {
  color: #1D4ED8;
}

.perio-print-key {
  font-size: 10px;
  color: #555;
}
</style>
