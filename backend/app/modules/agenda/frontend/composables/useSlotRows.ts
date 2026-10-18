/**
 * Row heights of a slot grid, grown where an appointment needs the room.
 *
 * Every slot starts at the density's height (28 px, 18 compact). A short
 * appointment — fifteen minutes is one slot — cannot show its patient and
 * time in that, so the slots it covers grow until its card reaches
 * `minCardHeight`, shared out evenly across them. A long appointment that
 * already has the room changes nothing, and a row with no appointment keeps
 * its height: the day stays as compact as it was where nothing is booked.
 *
 * Rows are shared across columns (the week's days, the day's professionals),
 * so a row takes the tallest any column asks of it. Everything that places
 * something on the grid — cards, the closed-hours bands, the drag ghost and
 * the drag maths — reads `top()` rather than multiplying by one height.
 */
export interface SlotSpan {
  /** First slot covered. */
  start: number
  /** Slot after the last one covered. */
  end: number
}

export function useSlotRows(options: {
  slotCount: () => number
  baseHeight: () => number
  /** The spans of the appointments currently on the grid. */
  spans: () => SlotSpan[]
}) {
  /** Enough for the name line and the time line of a card. */
  const minCardHeight = computed(() => (options.baseHeight() < 24 ? 36 : 44))

  const heights = computed<number[]>(() => {
    const base = options.baseHeight()
    const count = options.slotCount()
    const out = Array.from({ length: count }, () => base)
    for (const span of options.spans()) {
      const start = Math.max(0, span.start)
      const end = Math.min(count, Math.max(span.end, span.start + 1))
      if (end <= start) continue
      const each = Math.ceil(minCardHeight.value / (end - start))
      if (each <= base) continue
      for (let slot = start; slot < end; slot++) out[slot] = Math.max(out[slot]!, each)
    }
    return out
  })

  /** Top of every slot boundary; the last entry is the grid's full height. */
  const offsets = computed<number[]>(() => {
    const out = [0]
    for (const height of heights.value) out.push(out[out.length - 1]! + height)
    return out
  })

  /** Pixel offset of the top of slot `index` (the slot count = the bottom). */
  function top(index: number): number {
    const all = offsets.value
    return all[Math.max(0, Math.min(index, all.length - 1))] ?? 0
  }

  /** Pixel height from slot `start` to slot `end`. */
  function span(start: number, end: number): number {
    return top(end) - top(start)
  }

  return { heights, top, span }
}
