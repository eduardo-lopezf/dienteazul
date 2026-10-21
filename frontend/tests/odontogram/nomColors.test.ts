import { describe, expect, it } from 'vitest'
import { nomColor, nomTone } from '../../../backend/app/modules/odontogram/frontend/utils/nomColors'

describe('the NOM-013 colour convention', () => {
  it('draws work done blue', () => {
    for (const type of ['filling_composite', 'filling_amalgam', 'root_canal_full', 'crown', 'implant', 'missing']) {
      expect(nomTone(type, 'existing')).toBe('blue')
    }
  })

  it('draws active lesions and anything planned red', () => {
    expect(nomTone('caries', 'existing')).toBe('red')
    expect(nomTone('periapical_large', 'existing')).toBe('red')
    expect(nomTone('crown', 'planned')).toBe('red')
    expect(nomTone('sealant', 'planned')).toBe('red')
    // A tooth record's condition, as the change history shows it.
    expect(nomTone('extraction_indicated', 'existing')).toBe('red')
  })

  it('draws incipient caries and provisional work green', () => {
    expect(nomTone('incipient_caries', 'existing')).toBe('green')
    expect(nomTone('filling_temporary', 'existing')).toBe('green')
    expect(nomTone('provisional_crown_on_implant', 'existing')).toBe('green')
  })

  it('draws prevention yellow', () => {
    expect(nomTone('sealant', 'existing')).toBe('yellow')
  })

  it('has a lighter rendering for dark mode', () => {
    expect(nomColor('caries', 'existing')).toBe('#DC2626')
    expect(nomColor('caries', 'existing', true)).not.toBe('#DC2626')
  })
})
