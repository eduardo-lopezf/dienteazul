/**
 * The two ways a working tab stopped keeping its session alive.
 *
 * `last_activity_at` on the session family is the only clock the backend
 * honours, and `POST /auth/activity` is the only thing that moves it
 * (ADR 0062). Both defects below ended the same way: an hour of real
 * work, then "your session expired" mid-task, with the server's clock
 * frozen and the browser's cookie fresh.
 *
 * 1. The stamp went down before the signal was sent, and the signal was
 *    fired and forgotten — so every dropped request pushed the browser's
 *    idea of the session ahead of the server's.
 * 2. `start` stood down when a watch already existed. With the layout
 *    remounted before the old instance unmounted, the new instance got
 *    an inert stopper and the old unmount took the real watch away: that
 *    tab then neither stamped nor signalled anything.
 */
import { mockNuxtImport, mountSuspended } from '@nuxt/test-utils/runtime'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { STORAGE_KEYS } from '~/constants/storage'

mockNuxtImport('$fetch', original => vi.fn(original))

const ACTIVITY = '/api/v1/auth/activity'
const COOKIE = STORAGE_KEYS.LAST_ACTIVITY

async function fetchMock() {
  return vi.mocked((await import('#imports')).$fetch)
}

function activityCalls(mock: Awaited<ReturnType<typeof fetchMock>>): unknown[][] {
  return mock.mock.calls.filter(call => call[0] === ACTIVITY)
}

function stamp(): number | null {
  const match = new RegExp(`(?:^|;\\s*)${COOKIE}=(\\d+)`).exec(document.cookie)
  return match ? Number(match[1]) : null
}

function clearStamp(): void {
  document.cookie = `${COOKIE}=; Path=/; Max-Age=0`
}

// The 30 s throttle is module state inside the composable and cannot be
// reset between cases, so this clock only ever moves forward — a fake
// timer restarted at the real time would look like time travelling
// backwards and the throttle would swallow the interaction.
let clock = Date.now()

/** An interaction the watch is listening for, past its 30 s throttle. */
function interact(): void {
  clock += 31_000
  vi.setSystemTime(clock)
  window.dispatchEvent(new Event('pointerdown'))
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i++) await Promise.resolve()
}

/**
 * Start a watch the way the default layout does: inside a mounted
 * component, with a session the BFF would accept.
 */
async function authenticatedWatch(): Promise<() => void> {
  let stop!: () => void
  const component = defineComponent({
    setup() {
      useState<boolean>('auth:session', () => true).value = true
      stop = useSessionActivity().start(() => {})
      return () => h('div')
    }
  })
  await mountSuspended(component)
  return stop
}

beforeEach(async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(clock)
  const mock = await fetchMock()
  mock.mockReset()
  mock.mockResolvedValue(undefined as never)
})

afterEach(() => {
  vi.useRealTimers()
  clearStamp()
})

describe('useSessionActivity', () => {
  it('stamps the shared cookie only once the backend took the signal', async () => {
    const mock = await fetchMock()
    const stop = await authenticatedWatch()
    clearStamp()

    let land!: () => void
    mock.mockImplementation(((path: string) =>
      path === ACTIVITY
        ? new Promise<void>((resolve) => { land = resolve })
        : Promise.resolve(undefined)) as never)
    interact()
    await settle()

    // In flight: the server has not agreed yet, so neither has the cookie.
    expect(activityCalls(mock)).toHaveLength(1)
    expect(stamp()).toBeNull()

    land()
    await settle()
    expect(stamp()).not.toBeNull()
    stop()
  })

  it('leaves the cookie alone when the signal did not land', async () => {
    const mock = await fetchMock()
    const stop = await authenticatedWatch()
    clearStamp()

    mock.mockImplementation(((path: string) =>
      path === ACTIVITY
        ? Promise.reject(new Error('offline'))
        : Promise.resolve(undefined)) as never)
    interact()
    await settle()

    // The whole point: no stamp means this tab does not believe the
    // session is younger than the server does.
    expect(activityCalls(mock)).toHaveLength(1)
    expect(stamp()).toBeNull()
    stop()
  })

  it('replaces a watch that is already running instead of standing down', async () => {
    const mock = await fetchMock()
    const first = await authenticatedWatch()
    const second = await authenticatedWatch()
    expect(second).not.toBe(first)

    // The layout instance that was replaced unmounts afterwards. It must
    // take its own listeners away and leave the live watch alone.
    first()
    mock.mockClear()
    interact()
    await settle()

    expect(activityCalls(mock)).toHaveLength(1)
    second()
  })

  it('stops signalling once the live watch is stopped', async () => {
    const mock = await fetchMock()
    const stop = await authenticatedWatch()
    stop()
    mock.mockClear()
    interact()
    await settle()

    expect(activityCalls(mock)).toHaveLength(0)
  })
})
