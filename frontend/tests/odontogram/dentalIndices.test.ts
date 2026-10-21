import { describe, expect, it } from 'vitest'
import type { Treatment } from '../../app/types'
import { dentalIndices } from '../../../backend/app/modules/odontogram/frontend/utils/dentalIndices'
import type { EruptionStatus } from '../../../backend/app/modules/odontogram/frontend/utils/dentitionLayout'

let day = 0
function tr(
  clinical_type: string,
  teeth: number[] | Array<{ tooth_number: number, role: 'pillar' | 'pontic' }>,
  status: 'existing' | 'planned' = 'existing'
): Treatment {
  day++
  const at = `2026-01-${String(day).padStart(2, '0')}T10:00:00+00:00`
  return {
    id: `t${day}`,
    clinical_type,
    scope: teeth.length > 1 ? 'multi_tooth' : 'tooth',
    status,
    teeth: teeth.map((t, i) => (typeof t === 'number'
      ? { id: `m${day}-${i}`, tooth_number: t, role: null, surfaces: null }
      : { id: `m${day}-${i}`, surfaces: null, ...t })),
    recorded_at: at,
    source_module: 'odontogram',
    created_at: at,
    updated_at: at
  } as unknown as Treatment
}

function said(statuses: Record<number, EruptionStatus>) {
  return (tooth: number) => statuses[tooth] ?? null
}

describe('CPO-D', () => {
  it('is zero on a chart with nothing charted', () => {
    expect(dentalIndices({ treatments: [] }).cpod).toEqual({ decayed: 0, missing: 0, filled: 0, total: 0 })
  })

  it('counts each permanent tooth once, under one letter', () => {
    const { cpod } = dentalIndices({
      treatments: [
        tr('caries', [16]),
        tr('caries', [26]),
        tr('caries', [26]), // the same tooth twice is one decayed tooth
        tr('missing', [36]),
        tr('filling_composite', [46]),
        tr('crown', [11]),
        tr('root_canal_full', [21])
      ]
    })
    expect(cpod).toEqual({ decayed: 2, missing: 1, filled: 3, total: 6 })
  })

  it('takes a caries restored afterwards as filled, and a later one as decayed', () => {
    const treated = dentalIndices({ treatments: [tr('caries', [16]), tr('filling_composite', [16])] })
    expect(treated.cpod).toMatchObject({ decayed: 0, filled: 1 })
    const recurrent = dentalIndices({ treatments: [tr('filling_amalgam', [16]), tr('caries', [16])] })
    expect(recurrent.cpod).toMatchObject({ decayed: 1, filled: 0 })
  })

  it('counts a lost tooth as lost, whatever else is on it', () => {
    const { cpod } = dentalIndices({
      treatments: [
        tr('caries', [16]),
        tr('extraction', [16]),
        tr('implant', [46]),
        tr('bridge', [
          { tooth_number: 24, role: 'pillar' },
          { tooth_number: 25, role: 'pontic' },
          { tooth_number: 26, role: 'pillar' }
        ])
      ]
    })
    // 16 extracted, 46 replaced by an implant, 25 a pontic. Abutments are not counted.
    expect(cpod).toEqual({ decayed: 0, missing: 3, filled: 0, total: 3 })
  })

  it('leaves out what is only planned, and what is not decay', () => {
    const { cpod } = dentalIndices({
      treatments: [
        tr('filling_composite', [16], 'planned'),
        tr('extraction', [36], 'planned'),
        tr('incipient_caries', [26]),
        tr('sealant', [46]),
        tr('veneer', [11])
      ]
    })
    expect(cpod.total).toBe(0)
  })

  it('counts a temporary filling as decayed', () => {
    expect(dentalIndices({ treatments: [tr('filling_temporary', [36])] }).cpod.decayed).toBe(1)
  })

  it('does not count a tooth that is not there by nature as lost', () => {
    const { cpod } = dentalIndices({
      treatments: [tr('missing', [12]), tr('missing', [38]), tr('unerupted', [48]), tr('missing', [48])],
      statusOf: said({ 12: 'congenitally_missing', 38: 'impacted' })
    })
    expect(cpod.missing).toBe(0)
  })

  it('takes the tooth record saying caries as the tooth now', () => {
    const { cpod } = dentalIndices({
      treatments: [tr('root_canal_half', [25])],
      conditionOf: tooth => (tooth === 25 ? 'caries' : null)
    })
    expect(cpod).toMatchObject({ decayed: 1, filled: 0 })
  })

  it('reads the whole-tooth condition of a record with no treatment behind it', () => {
    const conditions: Record<number, string> = { 17: 'missing', 27: 'caries', 37: 'crown', 47: 'healthy' }
    const { cpod } = dentalIndices({ treatments: [], conditionOf: tooth => conditions[tooth] })
    expect(cpod).toEqual({ decayed: 1, missing: 1, filled: 1, total: 3 })
  })
})

describe('ceo-d', () => {
  it('counts decayed, extraction indicated and filled primary teeth', () => {
    const { ceod, cpod } = dentalIndices({
      treatments: [
        tr('caries', [54]),
        tr('caries', [64]),
        tr('extraction', [64], 'planned'),
        tr('filling_composite', [74]),
        tr('crown', [84]),
        tr('root_canal_half', [85])
      ]
    })
    expect(ceod).toEqual({ decayed: 1, extraction: 1, filled: 3, total: 5 })
    expect(cpod.total).toBe(0)
  })

  it('does not count a primary tooth that is gone', () => {
    const { ceod } = dentalIndices({
      treatments: [tr('caries', [53]), tr('extraction', [54]), tr('missing', [55])],
      statusOf: said({ 53: 'exfoliated' })
    })
    expect(ceod.total).toBe(0)
  })

  it('takes the extraction indicated on the tooth record', () => {
    const { ceod } = dentalIndices({ treatments: [], conditionOf: t => (t === 75 ? 'extraction_indicated' : null) })
    expect(ceod.extraction).toBe(1)
  })
})
