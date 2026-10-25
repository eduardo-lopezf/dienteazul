import { mockNuxtImport } from '@nuxt/test-utils/runtime'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCalendarBounds } from '../../../backend/app/modules/agenda/frontend/composables/useCalendarBounds'

const get = vi.fn()

mockNuxtImport('useApi', () => () => ({ get }))

describe('useCalendarBounds', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockResolvedValue({
      data: {
        timezone: 'America/Mexico_City',
        ranges: [{
          start: '2026-10-24T09:00:00-06:00',
          end: '2026-10-24T17:00:00-06:00',
          state: 'open',
          professional_id: null,
          reason: null
        }]
      }
    })
  })

  it('queries the calendar dates in local time, not the UTC date', async () => {
    const start = new Date(2026, 9, 24)
    const end = new Date(2026, 9, 24)
    vi.spyOn(start, 'toISOString').mockReturnValue('2026-10-23T10:00:00.000Z')
    vi.spyOn(end, 'toISOString').mockReturnValue('2026-10-23T10:00:00.000Z')

    const bounds = await useCalendarBounds().compute({ start, end })

    expect(get).toHaveBeenCalledWith(expect.stringContaining('start=2026-10-24&end=2026-10-24'))
    expect(bounds).toEqual({ startHour: 9, endHour: 17 })
  })
})
