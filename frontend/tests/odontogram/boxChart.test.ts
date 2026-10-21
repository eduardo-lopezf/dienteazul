import { describe, expect, it } from 'vitest'
import type { ToothTreatmentView } from '../../app/types'
import {
  boxDimmedTeeth,
  boxRows,
  surfaceAt,
  toothBoxState
} from '../../../backend/app/modules/odontogram/frontend/utils/boxChart'

let n = 0
function view(
  clinical_type: string,
  options: { surfaces?: string[], status?: 'existing' | 'planned', role?: 'pillar' | 'pontic' } = {}
): ToothTreatmentView {
  n++
  return {
    clinical_type,
    treatment_type: clinical_type,
    surfaces: options.surfaces ?? null,
    status: options.status ?? 'existing',
    role: options.role ?? null,
    recorded_at: `2026-01-${String(n).padStart(2, '0')}T10:00:00+00:00`
  } as unknown as ToothTreatmentView
}

describe('rows of the box chart', () => {
  it('draws permanent teeth outside and primary teeth inside', () => {
    expect(boxRows('mixed').map(r => r.key)).toEqual([
      'upperPermanent', 'upperPrimary', 'lowerPrimary', 'lowerPermanent'
    ])
    expect(boxRows('permanent').map(r => r.key)).toEqual(['upperPermanent', 'lowerPermanent'])
    expect(boxRows('deciduous').map(r => r.key)).toEqual(['upperPrimary', 'lowerPrimary'])
  })

  it('dims, in a mixed dentition, the teeth that are not in the mouth', () => {
    // At eight the 13 is years away, so the 53 is in; the 11 has come through.
    const dimmed = boxDimmedTeeth('mixed', { age: 8 })
    expect(dimmed).toContain(13)
    expect(dimmed).not.toContain(53)
    expect(dimmed).toContain(51)
    expect(dimmed).not.toContain(11)
    expect(boxDimmedTeeth('permanent', { age: 30 })).toEqual([])
  })
})

describe('a side of the square is a surface', () => {
  it('puts the vestibular face outward', () => {
    expect(surfaceAt(16, 'top')).toBe('V')
    expect(surfaceAt(16, 'bottom')).toBe('L')
    expect(surfaceAt(36, 'bottom')).toBe('V')
    expect(surfaceAt(36, 'top')).toBe('L')
    expect(surfaceAt(54, 'center')).toBe('O')
  })

  it('turns the mesial face to the midline', () => {
    // The patient's right is the chart's left: its midline is to the right.
    expect(surfaceAt(16, 'right')).toBe('M')
    expect(surfaceAt(16, 'left')).toBe('D')
    expect(surfaceAt(26, 'left')).toBe('M')
    expect(surfaceAt(46, 'right')).toBe('M')
    expect(surfaceAt(36, 'left')).toBe('M')
    expect(surfaceAt(84, 'right')).toBe('M')
    expect(surfaceAt(74, 'left')).toBe('M')
  })
})

describe('what a tooth square shows', () => {
  it('paints caries red, work done blue and planned work lighter red', () => {
    const state = toothBoxState([
      view('caries', { surfaces: ['M'] }),
      view('filling_composite', { surfaces: ['O'] }),
      view('filling_composite', { surfaces: ['D'], status: 'planned' })
    ])
    expect(state.surfaces).toEqual({ M: 'caries', O: 'done', D: 'planned' })
  })

  it('shows the later mark on a surface', () => {
    const state = toothBoxState([
      view('caries', { surfaces: ['O'] }),
      view('filling_amalgam', { surfaces: ['O'] })
    ])
    expect(state.surfaces.O).toBe('done')
  })

  it('crosses out a tooth that is gone, and in red one to extract', () => {
    expect(toothBoxState([view('missing')]).cross).toBe('existing')
    expect(toothBoxState([view('extraction', { status: 'planned' })]).cross).toBe('planned')
    expect(toothBoxState([view('extraction'), view('extraction', { status: 'planned' })]).cross).toBe('existing')
    expect(toothBoxState([view('bridge', { role: 'pontic' })]).cross).toBe('existing')
  })

  it('rings a crown and writes the rest as codes', () => {
    const state = toothBoxState([
      view('crown'),
      view('root_canal_full'),
      view('implant', { status: 'planned' })
    ])
    expect(state.ring).toBe('existing')
    expect(state.codes).toEqual([
      { type: 'root_canal_full', status: 'existing' },
      { type: 'implant', status: 'planned' }
    ])
  })

  it('draws the tooth record first, and what is charted over it', () => {
    expect(toothBoxState([], 'caries').surfaces.O).toBe('caries')
    expect(toothBoxState([], 'missing').cross).toBe('existing')
    expect(toothBoxState([], 'extraction_indicated').cross).toBe('planned')
    expect(toothBoxState([], 'healthy')).toEqual({ surfaces: {}, cross: null, ring: null, codes: [] })
    const restored = toothBoxState([view('filling_composite', { surfaces: ['O'] })], 'caries')
    expect(restored.surfaces.O).toBe('done')
  })
})
