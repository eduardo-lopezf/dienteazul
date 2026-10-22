import { describe, expect, it } from 'vitest'
import { perioLayout } from '../../backend/app/modules/periodontogram/frontend/utils/perioLayout'

describe('the periodontogram fits the screen it is on', () => {
  it('draws each whole arch on a wide screen', () => {
    expect(perioLayout(1152)).toEqual({ split: false, zoom: 1 })
    expect(perioLayout(1060)).toEqual({ split: false, zoom: 1 })
  })

  it('draws an arch as its two quadrants on a tablet, on its side or upright', () => {
    // 1024 wide with the sidebar open; 768 upright with the rail.
    expect(perioLayout(736)).toEqual({ split: true, zoom: 1 })
    expect(perioLayout(640)).toEqual({ split: true, zoom: 1 })
  })

  it('shrinks a quadrant where even that does not fit, but not past 75 %', () => {
    expect(perioLayout(480)).toEqual({ split: true, zoom: 0.83 })
    expect(perioLayout(300)).toEqual({ split: true, zoom: 0.75 })
  })

  it('draws the whole chart before the width is known', () => {
    expect(perioLayout(0)).toEqual({ split: false, zoom: 1 })
  })
})
