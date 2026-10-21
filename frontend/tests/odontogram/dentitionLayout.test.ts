import { describe, expect, it } from 'vitest'
import {
  dimmedTeeth,
  eruptionAlerts,
  type EruptionStatus,
  fitsTooth,
  offeredOn,
  predecessorOf,
  shownDentition,
  successorOf,
  teethLayout
} from '../../../backend/app/modules/odontogram/frontend/utils/dentitionLayout'

function said(statuses: Record<number, EruptionStatus>) {
  return (tooth: number) => statuses[tooth] ?? null
}

describe('the chart follows the patient', () => {
  it('draws what the age suggests unless the clinician chose', () => {
    expect(shownDentition('auto', 'mixed')).toBe('mixed')
    expect(shownDentition('permanent', 'mixed')).toBe('permanent')
  })

  it('shows the 20 primary teeth to a small child', () => {
    const layout = teethLayout('deciduous', { age: 4 })
    expect(Object.values(layout).flat()).toHaveLength(20)
    expect(layout.upperRight).toEqual([55, 54, 53, 52, 51])
  })

  it('shows one tooth per position in a mixed dentition, by eruption age', () => {
    // Eight: first molars and incisors are out, canines and premolars not yet.
    const layout = teethLayout('mixed', { age: 8 })
    expect(layout.upperRight).toEqual([16, 55, 54, 53, 12, 11])
    expect(layout.lowerLeft).toEqual([31, 32, 73, 74, 75, 36])
  })

  it('lets what is charted win over the age', () => {
    // A lower canine treated at seven is in the mouth, whatever the table says.
    const layout = teethLayout('mixed', { age: 7, charted: tooth => tooth === 43 })
    expect(layout.lowerRight).toContain(43)
    expect(layout.lowerRight).not.toContain(83)
  })

  it('shows second molars once their age comes', () => {
    expect(teethLayout('mixed', { age: 10 }).upperLeft).not.toContain(27)
    expect(teethLayout('mixed', { age: 12 }).upperLeft).toContain(27)
  })

  it('follows a clinic chronology', () => {
    const ages = {
      upper: { 1: 7, 2: 8, 3: 11, 4: 10, 5: 10, 6: 6, 7: 10, 8: 17 },
      lower: { 1: 6, 2: 7, 3: 9, 4: 10, 5: 11, 6: 6, 7: 11, 8: 17 }
    }
    expect(teethLayout('mixed', { age: 10, ages }).upperLeft).toContain(27)
  })

  it('dims third molars before eighteen unless something is charted on them', () => {
    expect(dimmedTeeth('permanent', { age: 15 })).toEqual([18, 28, 48, 38])
    expect(dimmedTeeth('permanent', { age: 15, charted: tooth => tooth === 38 })).toEqual([18, 28, 48])
    expect(dimmedTeeth('permanent', { age: 30 })).toEqual([])
    expect(dimmedTeeth('permanent', { age: null })).toEqual([])
  })

  it('knows which tooth replaces which', () => {
    expect(predecessorOf(11)).toBe(51)
    expect(predecessorOf(45)).toBe(85)
    expect(predecessorOf(36)).toBeNull()
    expect(successorOf(54)).toBe(14)
    expect(successorOf(75)).toBe(35)
    expect(successorOf(14)).toBeNull()
  })
})

describe('the eruption status decides before the chronology', () => {
  it('shows the successor once the primary tooth is exfoliated', () => {
    // At seven the upper canine is years away; the 53 fell out early.
    const layout = teethLayout('mixed', { age: 7, statusOf: said({ 53: 'exfoliated' }) })
    expect(layout.upperRight).toContain(13)
    expect(layout.upperRight).not.toContain(53)
  })

  it('keeps the primary tooth when the successor is said not to be there', () => {
    // At eleven the 11 is due — but the clinician charted it unerupted.
    const layout = teethLayout('mixed', { age: 11, statusOf: said({ 11: 'unerupted' }) })
    expect(layout.upperRight).toContain(51)
    expect(layout.upperRight).not.toContain(11)
  })

  it('draws a molar charted as not there yet, dimmed', () => {
    const facts = { age: 9, statusOf: said({ 17: 'unerupted' }) }
    expect(teethLayout('mixed', facts).upperRight).toContain(17)
    expect(dimmedTeeth('mixed', facts)).toContain(17)
  })

  it('dims what is not in the mouth, in any view', () => {
    const facts = { age: 30, statusOf: said({ 24: 'congenitally_missing', 38: 'impacted' }) }
    expect(dimmedTeeth('permanent', facts)).toEqual(expect.arrayContaining([24, 38]))
  })
})

describe('warnings come from what is charted', () => {
  it('warns of nothing when nothing is said', () => {
    expect(eruptionAlerts({ age: 15 })).toEqual([])
  })

  it('warns of a primary tooth kept too long', () => {
    // The 53 is charted in the mouth at fourteen; the 13 is due at eleven.
    const alerts = eruptionAlerts({ age: 14, statusOf: said({ 53: 'erupted' }) })
    expect(alerts).toEqual([{ kind: 'retained_primary', tooth: 53, successor: 13, usualAge: 11 }])
  })

  it('does not warn when the successor is absent from birth', () => {
    const alerts = eruptionAlerts({
      age: 14,
      statusOf: said({ 53: 'erupted', 13: 'congenitally_missing' })
    })
    expect(alerts).toEqual([])
  })

  it('warns of a late eruption, never of a third molar', () => {
    const alerts = eruptionAlerts({
      age: 15,
      statusOf: said({ 13: 'impacted', 38: 'unerupted', 15: 'unerupted' })
    })
    expect(alerts.map(alert => alert.tooth)).toEqual([15, 13])
    expect(alerts.every(alert => alert.kind === 'delayed_eruption')).toBe(true)
  })

  it('waits for the tolerance to pass', () => {
    expect(eruptionAlerts({ age: 12, statusOf: said({ 13: 'unerupted' }) })).toEqual([])
    expect(eruptionAlerts({ age: 13, statusOf: said({ 13: 'unerupted' }) })).toHaveLength(1)
  })
})

describe('a treatment is offered where it fits', () => {
  it('fits the teeth of its dentition', () => {
    expect(fitsTooth('deciduous', 84)).toBe(true)
    expect(fitsTooth('deciduous', 46)).toBe(false)
    expect(fitsTooth('permanent', 16)).toBe(true)
    expect(fitsTooth('permanent', 54)).toBe(false)
    expect(fitsTooth('both', 54)).toBe(true)
    // An item that does not say fits any tooth.
    expect(fitsTooth(undefined, 54)).toBe(true)
  })

  it('leaves out of the bar what the drawn dentition has no tooth for', () => {
    expect(offeredOn('permanent', 'deciduous')).toBe(false)
    expect(offeredOn('deciduous', 'permanent')).toBe(false)
    expect(offeredOn('deciduous', 'deciduous')).toBe(true)
    expect(offeredOn('both', 'permanent')).toBe(true)
  })

  it('offers everything on a mixed dentition, where the tooth decides', () => {
    expect(offeredOn('permanent', 'mixed')).toBe(true)
    expect(offeredOn('deciduous', 'mixed')).toBe(true)
  })
})
