import { describe, expect, it } from 'vitest'
import type { ToothTreatmentView } from '../../app/types'
import {
  ALL_FINDINGS,
  MAIN_FINDINGS,
  clearDraft,
  findingByKey,
  draftChanges,
  draftViews,
  effectiveOn,
  findingState,
  selectionSummary,
  toggleDraft,
  type TeethFacts
} from '../../../backend/app/modules/odontogram/frontend/utils/toothFindings'

function view(
  clinical_type: string,
  options: { status?: 'existing' | 'planned', catalog?: boolean, multi?: boolean, id?: string } = {}
): ToothTreatmentView {
  return {
    treatment_id: options.id ?? `t-${clinical_type}`,
    clinical_type,
    treatment_type: clinical_type,
    status: options.status ?? 'existing',
    catalog_item_id: options.catalog ? 'cat-1' : null,
    is_multi: options.multi ?? false
  } as unknown as ToothTreatmentView
}

const finding = (key: string) => findingByKey(key)!

describe('the tooth card', () => {
  it('offers the diagnosis findings in the order asked for', () => {
    expect(MAIN_FINDINGS.map(f => f.key)).toEqual([
      'missing',
      'extraction_indicated',
      'impacted',
      'rotation_left',
      'rotation_right',
      'intrusion',
      'extrusion',
      'diastema',
      'crowding',
      'bracket',
      'caries'
    ])
  })

  it('shows on each switch the icon the chart draws it with', () => {
    expect(finding('diastema').icon).toBe('diastema')
    expect(finding('crowding').icon).toBe('crowding')
    expect(finding('bracket').icon).toBe('bracket')
    expect(finding('extraction_indicated').icon).toBe('extraction')
    expect(finding('impacted').icon).toBe('unerupted')
  })

  it('pairs the opposite movements', () => {
    expect(finding('rotation_left').excludes).toBe('rotation_right')
    expect(finding('rotation_right').excludes).toBe('rotation_left')
    expect(finding('intrusion').excludes).toBe('extrusion')
    expect(finding('extrusion').excludes).toBe('intrusion')
  })

  it('has unique keys', () => {
    const keys = ALL_FINDINGS.map(f => f.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('whether a finding is on the tooth', () => {
  it('reads a diagnostic treatment of its type and status', () => {
    const state = findingState(finding('crowding'), [view('crowding')], null)
    expect(state).toEqual({ active: true, removable: ['t-crowding'], locked: false })
    expect(findingState(finding('diastema'), [view('crowding')], null).active).toBe(false)
  })

  it('takes "indicated for extraction" as a planned extraction, not a done one', () => {
    const indicated = finding('extraction_indicated')
    expect(findingState(indicated, [view('extraction', { status: 'planned' })], null).active).toBe(true)
    expect(findingState(indicated, [view('extraction')], null).active).toBe(false)
  })

  it('leaves alone what was charted from the catalog or on several teeth', () => {
    const fromCatalog = findingState(
      finding('extraction_indicated'),
      [view('extraction', { status: 'planned', catalog: true })],
      null
    )
    expect(fromCatalog).toEqual({ active: true, removable: [], locked: true })
    const bridgeLike = findingState(finding('bracket'), [view('bracket', { multi: true })], null)
    expect(bridgeLike.locked).toBe(true)
  })

  it('reads a retained tooth from the eruption status', () => {
    expect(findingState(finding('impacted'), [], 'impacted').active).toBe(true)
    expect(findingState(finding('impacted'), [], 'erupted').active).toBe(false)
    expect(findingState(finding('impacted'), [], null).active).toBe(false)
  })
})

describe('a switch over several teeth, kept pending', () => {
  function facts(charted: Record<number, ToothTreatmentView[]>, statuses: Record<number, string> = {}): TeethFacts {
    return {
      viewsOf: tooth => charted[tooth] ?? [],
      statusOf: tooth => (statuses[tooth] ?? null) as never
    }
  }
  const none = new Map<string, boolean>()
  const keys = (changes: ReturnType<typeof draftChanges>) =>
    changes.map(c => `${c.finding.key}:${c.tooth}:${c.on ? 'on' : 'off'}`)

  it('puts brackets on every picked tooth that lacks them', () => {
    const f = facts({ 12: [view('bracket', { id: 'b12' })] })
    const draft = toggleDraft(finding('bracket'), [11, 12, 21], f, none)
    expect(keys(draftChanges(draft))).toEqual(['bracket:11:on', 'bracket:21:on'])
    expect(effectiveOn(finding('bracket'), 11, f, draft)).toBe(true)
  })

  it('takes them off all the teeth when every one has them', () => {
    const f = facts({ 11: [view('bracket', { id: 'b11' })], 21: [view('bracket', { id: 'b21' })] })
    const draft = toggleDraft(finding('bracket'), [11, 21], f, none)
    expect(keys(draftChanges(draft))).toEqual(['bracket:11:off', 'bracket:21:off'])
  })

  it('pressing twice leaves nothing pending', () => {
    const f = facts({})
    const once = toggleDraft(finding('diastema'), [11], f, none)
    expect(toggleDraft(finding('diastema'), [11], f, once).size).toBe(0)
  })

  it('swaps the turn, taking the opposite off first', () => {
    const f = facts({ 11: [view('rotation_right', { id: 'r11' })] })
    const draft = toggleDraft(finding('rotation_left'), [11, 12], f, none)
    expect(keys(draftChanges(draft))).toEqual(['rotation_right:11:off', 'rotation_left:11:on', 'rotation_left:12:on'])
  })

  it('sets and clears a retained tooth through the eruption status', () => {
    const on = toggleDraft(finding('impacted'), [18, 28], facts({}, { 28: 'impacted' }), none)
    expect(keys(draftChanges(on))).toEqual(['impacted:18:on'])
    const off = toggleDraft(finding('impacted'), [18, 28], facts({}, { 18: 'impacted', 28: 'impacted' }), none)
    expect(keys(draftChanges(off))).toEqual(['impacted:18:off', 'impacted:28:off'])
  })

  it('leaves surface findings to the surface picker', () => {
    expect(toggleDraft(finding('caries'), [11], facts({}), none).size).toBe(0)
  })

  it('never drafts off what the card cannot take off', () => {
    const f = facts({ 21: [view('bracket', { id: 'b21', catalog: true })] })
    expect(toggleDraft(finding('bracket'), [21], f, none).size).toBe(0)
  })

  it('counts pending presses, and locks what the card cannot take off', () => {
    const f = facts({ 11: [view('bracket', { id: 'b11' })], 21: [view('bracket', { id: 'b21', catalog: true })] })
    expect(selectionSummary(finding('bracket'), [11, 12, 21], f)).toEqual({ active: 2, total: 3, locked: false })
    const draft = toggleDraft(finding('bracket'), [12], f, none)
    expect(selectionSummary(finding('bracket'), [11, 12, 21], f, draft).active).toBe(3)
    expect(selectionSummary(finding('bracket'), [21], f).locked).toBe(true)
  })

  it('previews the teeth as they will be once saved', () => {
    const f = facts({ 11: [view('crowding', { id: 'c11' })] })
    let draft = toggleDraft(finding('crowding'), [11], f, none)
    draft = toggleDraft(finding('bracket'), [11], f, draft)
    expect(draftViews(11, f, draft).map(v => v.clinical_type)).toEqual(['bracket'])
  })
})

describe('*Limpiar*: the picked teeth as blank as the card can leave them', () => {
  function facts(charted: Record<number, ToothTreatmentView[]>, statuses: Record<number, string> = {}): TeethFacts {
    return {
      viewsOf: tooth => charted[tooth] ?? [],
      statusOf: tooth => (statuses[tooth] ?? null) as never
    }
  }
  const none = new Map<string, boolean>()
  const keys = (changes: ReturnType<typeof draftChanges>) =>
    changes.map(c => `${c.finding.key}:${c.tooth}:${c.on ? 'on' : 'off'}`)

  it('takes every charted finding off every picked tooth', () => {
    const f = facts({
      11: [view('crowding', { id: 'c11' }), view('bracket', { id: 'b11' })],
      21: [view('diastema', { id: 'd21' })]
    })
    const { next, cleared, locked } = clearDraft([11, 21], f, none)
    expect(keys(draftChanges(next)).sort()).toEqual(['bracket:11:off', 'crowding:11:off', 'diastema:21:off'])
    expect({ cleared, locked }).toEqual({ cleared: 3, locked: 0 })
  })

  it('leaves what the card may not take off, and says how much', () => {
    const f = facts({ 11: [view('bracket', { id: 'b11', catalog: true }), view('crowding', { id: 'c11' })] })
    const { next, cleared, locked } = clearDraft([11], f, none)
    expect(keys(draftChanges(next))).toEqual(['crowding:11:off'])
    expect({ cleared, locked }).toEqual({ cleared: 1, locked: 1 })
  })

  it('clears a retained tooth through the eruption status', () => {
    const { next, cleared } = clearDraft([18], facts({}, { 18: 'impacted' }), none)
    expect(keys(draftChanges(next))).toEqual(['impacted:18:off'])
    expect(cleared).toBe(1)
  })

  it('takes caries off, which only going back on needs the surface picker for', () => {
    const f = facts({ 11: [view('caries', { id: 'k11' })] })
    expect(keys(draftChanges(clearDraft([11], f, none).next))).toEqual(['caries:11:off'])
  })

  it('swallows a pending press instead of charting and removing it', () => {
    const f = facts({})
    const pressed = toggleDraft(finding('diastema'), [11], f, none)
    const { next, cleared } = clearDraft([11], f, pressed)
    expect(next.size).toBe(0)
    expect(cleared).toBe(1)
  })

  it('has nothing to do on a tooth the card charts nothing on', () => {
    const f = facts({ 11: [view('bracket', { id: 'b11', catalog: true })] })
    expect(clearDraft([11], f, none)).toEqual({ next: new Map(), cleared: 0, locked: 1 })
    expect(clearDraft([12], facts({}), none).cleared).toBe(0)
  })
})
