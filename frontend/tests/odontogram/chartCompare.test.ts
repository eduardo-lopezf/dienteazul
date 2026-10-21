import { describe, expect, it } from 'vitest'
import type { Treatment } from '../../app/types'
import { compareCharts } from '../../../backend/app/modules/odontogram/frontend/utils/chartCompare'

function tr(id: string, clinical_type: string, teeth: number[], status = 'performed'): Treatment {
  return {
    id,
    clinical_type,
    status,
    teeth: teeth.map(n => ({ tooth_number: n }))
  } as unknown as Treatment
}

describe('what changed between two dates', () => {
  it('finds work charted, done and withdrawn in between', () => {
    const before = {
      treatments: [tr('a', 'caries', [36]), tr('b', 'filling_composite', [16], 'planned'), tr('c', 'sealant', [26])],
      teeth: []
    }
    const after = {
      treatments: [
        tr('a', 'caries', [36]),
        tr('b', 'filling_composite', [16]),
        tr('d', 'crown', [46], 'planned'),
        tr('e', 'hygiene', [])
      ],
      teeth: []
    }
    expect(compareCharts(before, after)).toEqual([
      { kind: 'performed', tooth: 16, teeth: [16], type: 'filling_composite' },
      { kind: 'removed', tooth: 26, teeth: [26], type: 'sealant' },
      { kind: 'added', tooth: 46, teeth: [46], type: 'crown', planned: true },
      { kind: 'added', tooth: null, teeth: [], type: 'hygiene', planned: false }
    ])
  })

  it('finds the exchange of a primary tooth', () => {
    const before = { treatments: [], teeth: [{ tooth_number: 54, eruption_status: null }] }
    const after = {
      treatments: [],
      teeth: [
        { tooth_number: 54, eruption_status: 'exfoliated' },
        { tooth_number: 14, eruption_status: 'erupting' }
      ]
    }
    expect(compareCharts(before, after)).toEqual([
      { kind: 'eruption', tooth: 14, teeth: [14], type: 'erupting', from: null },
      { kind: 'eruption', tooth: 54, teeth: [54], type: 'exfoliated', from: null }
    ])
  })

  it('finds a tooth whose record changed condition', () => {
    const before = { treatments: [], teeth: [{ tooth_number: 25, general_condition: 'healthy' }] }
    const after = { treatments: [], teeth: [{ tooth_number: 25, general_condition: 'caries' }] }
    expect(compareCharts(before, after)).toEqual([
      { kind: 'condition', tooth: 25, teeth: [25], type: 'caries', from: 'healthy' }
    ])
  })

  it('finds nothing between two equal charts', () => {
    const chart = { treatments: [tr('a', 'caries', [36])], teeth: [{ tooth_number: 36, eruption_status: 'erupted' }] }
    expect(compareCharts(chart, chart)).toEqual([])
  })
})
