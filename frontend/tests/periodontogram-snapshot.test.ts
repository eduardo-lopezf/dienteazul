import { describe, expect, it } from 'vitest'
import type { PerioTooth } from '../../backend/app/modules/periodontogram/frontend/types'
import { hasRecordedData } from '../../backend/app/modules/periodontogram/frontend/utils/perioSnapshot'

function tooth(patch: Partial<PerioTooth> = {}, site: Record<string, unknown> = {}): PerioTooth {
  return {
    tooth_number: 16,
    is_present: true,
    is_implant: false,
    mobility: null,
    prognosis: null,
    furcation_buccal: null,
    furcation_lingual: null,
    keratinized_gingiva_mm: null,
    sites: [{
      site_code: 'MV',
      probing_depth_mm: null,
      gingival_margin_mm: null,
      bleeding_on_probing: false,
      plaque: false,
      suppuration: false,
      ...site
    }],
    ...patch
  } as PerioTooth
}

describe('a session with something to print', () => {
  it('has nothing when closed without charting', () => {
    expect(hasRecordedData({ teeth: [tooth(), tooth({ furcation_buccal: '0' })] })).toBe(false)
  })

  it('has something once a site or a tooth is charted', () => {
    expect(hasRecordedData({ teeth: [tooth({}, { probing_depth_mm: 2 })] })).toBe(true)
    expect(hasRecordedData({ teeth: [tooth({}, { bleeding_on_probing: true })] })).toBe(true)
    expect(hasRecordedData({ teeth: [tooth({ mobility: 0 })] })).toBe(true)
    expect(hasRecordedData({ teeth: [tooth({ furcation_lingual: 'II' })] })).toBe(true)
  })
})
