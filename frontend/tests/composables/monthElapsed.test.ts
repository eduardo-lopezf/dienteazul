import { describe, expect, it } from 'vitest'
import { monthElapsedPct } from '../../../backend/app/modules/reports/frontend/composables/useMonthlyTargets'

/**
 * The targets card paints a bar against the calendar, not only against
 * the goal: half a target on the 5th is ahead and the same half on the
 * 28th is behind. Everything that judgement rests on is this function.
 */
describe('monthElapsedPct', () => {
  it('reports how much of the running month has gone', () => {
    // 15 September of a 30-day month.
    expect(monthElapsedPct('2026-09-01', new Date(2026, 8, 15))).toBe(50)
  })

  it('counts the short months by their own length', () => {
    // 14 February of a 28-day month is half, not 14/31.
    expect(monthElapsedPct('2026-02-01', new Date(2026, 1, 14))).toBe(50)
  })

  it('treats a month already over as complete', () => {
    expect(monthElapsedPct('2026-09-01', new Date(2026, 9, 3))).toBe(100)
  })

  it('treats a month still ahead as untouched', () => {
    // Otherwise next month's goals would open painted red.
    expect(monthElapsedPct('2026-12-01', new Date(2026, 9, 3))).toBe(0)
  })

  it('does not confuse the same month of another year', () => {
    expect(monthElapsedPct('2025-09-01', new Date(2026, 8, 15))).toBe(100)
  })
})
