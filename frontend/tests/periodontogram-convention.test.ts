import { describe, expect, it } from 'vitest'
import {
  isNarrowKeratinizedGingiva,
  isPathologicalDepth
} from '../../backend/app/modules/periodontogram/frontend/utils/perioConvention'
import { probingDepthTone } from '../../backend/app/modules/periodontogram/frontend/composables/usePerioHeatmap'

describe('the SEPA red numbers', () => {
  it('writes a probing depth over 3 mm in red', () => {
    expect(isPathologicalDepth(3)).toBe(false)
    expect(isPathologicalDepth(4)).toBe(true)
    expect(isPathologicalDepth(null)).toBe(false)
  })

  it('writes keratinized gingiva of 2 mm or less in red', () => {
    expect(isNarrowKeratinizedGingiva(0)).toBe(true)
    expect(isNarrowKeratinizedGingiva(2)).toBe(true)
    expect(isNarrowKeratinizedGingiva(3)).toBe(false)
    expect(isNarrowKeratinizedGingiva(undefined)).toBe(false)
  })
})

describe('the site markers', () => {
  it('are green up to 3 mm and red over it, as the SEPA chart', () => {
    expect(probingDepthTone(null)).toBe('neutral')
    expect(probingDepthTone(0)).toBe('healthy')
    expect(probingDepthTone(3)).toBe('healthy')
    expect(probingDepthTone(4)).toBe('pathological')
    expect(probingDepthTone(9)).toBe('pathological')
  })
})
