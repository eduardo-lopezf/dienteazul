import type { PerioSnapshotDetail } from '../types'

/**
 * Whether a session recorded anything: a probing depth or margin, a
 * bleeding, plaque or suppuration mark, or a per-tooth finding (mobility,
 * furcation, keratinized gingiva). A session closed without charting —
 * opened by mistake, or closed to start again — has nothing to print.
 */
export function hasRecordedData(snapshot: Pick<PerioSnapshotDetail, 'teeth'>): boolean {
  return snapshot.teeth.some(tooth =>
    tooth.mobility != null
    || (tooth.furcation_buccal != null && tooth.furcation_buccal !== '0')
    || (tooth.furcation_lingual != null && tooth.furcation_lingual !== '0')
    || tooth.keratinized_gingiva_mm != null
    || tooth.sites.some(site =>
      site.probing_depth_mm != null
      || site.gingival_margin_mm != null
      || site.bleeding_on_probing
      || site.plaque
      || site.suppuration
    )
  )
}
