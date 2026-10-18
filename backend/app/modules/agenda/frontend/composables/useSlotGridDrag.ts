/**
 * useSlotGridDrag — pointer-driven drag for the week and day grids.
 *
 * Both grids are the same thing with a different column axis (days vs
 * professionals), and both carried a near-identical copy of this logic
 * built on `mousedown` plus document-level `mousemove`. Chrome on Android
 * emits mouse events only as compatibility events *after* the finger
 * lifts, so none of it tracked on a tablet: no create, no move, no
 * resize. This is one Pointer Events implementation for mouse, finger
 * and stylus alike.
 *
 * ## Fine pointer (mouse, trackpad)
 *
 * Unchanged: press and drag starts immediately. Press on an empty cell
 * and drag down to size a new appointment; press and release without
 * moving is a click on the slot.
 *
 * ## Coarse pointer (finger)
 *
 * A finger cannot hover and a press is ambiguous with a scroll, so the
 * grid uses select-then-drag, the pattern mobile calendars settled on:
 *
 * - Tap an appointment  → open it.
 * - Long-press (300 ms) → select it. The block lifts and grows handles.
 * - Drag a selected block → move it. Drag its handle → resize it.
 * - Tap an empty cell    → create there (no drag; see below).
 * - Tap elsewhere        → deselect.
 *
 * Selection is what makes this work at all. `touch-action: none` is the
 * only way to stop the browser scrolling instead of dragging, and
 * applying it to every block would make the grid unscrollable wherever
 * appointments sit. Applied only while a block is *selected*, the grid
 * scrolls normally until the user has said which block they mean.
 *
 * Drag-to-size on an empty cell is deliberately not offered by touch:
 * it would need `touch-action: none` across the whole canvas, which
 * costs scrolling everywhere to save one modal field. A tap creates at
 * the default duration instead.
 *
 * ## How the two paths are organised
 *
 * Each entry point is a thin dispatcher over a pair of functions named
 * for the capability they serve — `pressAppointmentWithMouse` and
 * `pressAppointmentByTouch` — so which code runs where is readable
 * without tracing conditionals.
 *
 * The split stops where the paths converge. `beginAppointmentDrag`,
 * `onPointerMove` and `onPointerUp` are shared, because once a drag is
 * under way a finger and a mouse want the identical thing; duplicating
 * that arithmetic is precisely how one density bug came to live in both
 * grids at once.
 *
 * The names say *capability*, never device. There is no `...OnIpad`
 * here and there should not be: iPad, Android tablet and a touchscreen
 * PC are one case — a coarse pointer — and Safari on iPad reports a
 * macOS user-agent anyway, so a device branch would not even fire. See
 * ADR 0022.
 */
import type { Ref } from 'vue'

/** A drag in progress on an existing appointment. */
export interface AppointmentDragState {
  type: 'move' | 'resize'
  appointmentId: string
  startX: number
  startY: number
  originalTop: number
  originalHeight: number
  originalColumnIndex: number
  currentColumnIndex: number
  currentTop: number
  currentHeight: number
}

/**
 * What a press on an appointment is asking for, bundled so the
 * capability branches can pass it along in one piece.
 */
export interface DragIntent {
  type: 'move' | 'resize'
  appointmentId: string
  columnIndex: number
  startSlot: number
  endSlot: number
}

/** A drag in progress on empty space, sizing a new appointment. */
export interface CreateDragState {
  columnIndex: number
  startSlot: number
  currentSlot: number
  startY: number
}

export interface SlotGridDragOptions {
  /** Pixel height of one slot. Read live — density can change it. */
  slotHeight: () => number
  /**
   * Pixel offset of the top of slot ``index`` (``index`` may be the slot
   * count, the bottom edge). For grids whose rows are not all one height —
   * a row grows to fit the appointment in it. Defaults to
   * ``index * slotHeight()``.
   */
  slotTop?: (index: number) => number
  /** Highest addressable slot index, i.e. slots per day minus one. */
  maxSlotIndex: () => number
  /** Number of data columns (days, or professionals). */
  columnCount: () => number
  /**
   * Columns rendered before the data columns — the time gutter. Used to
   * turn a horizontal delta into a column delta.
   */
  gutterColumns: number
  /** The scroll container, measured to size a column. */
  containerRef: Ref<HTMLElement | null>
  /** Committed when a create-drag covered more than one slot. */
  onCreateRange: (columnIndex: number, startSlot: number, endSlot: number) => void
  /** Committed when a press on empty space did not turn into a drag. */
  onCreatePoint: (columnIndex: number, slot: number) => void
  onMove: (appointmentId: string, columnIndex: number, startSlot: number, endSlot: number) => void
  onResize: (appointmentId: string, endSlot: number) => void
}

/** How long a finger must rest on a block before it is selected. */
const LONG_PRESS_MS = 300
/** Movement that cancels a pending long press — the user is scrolling. */
const LONG_PRESS_SLOP_PX = 10
/** Movement past which a drag suppresses the click that follows it. */
const DRAG_SLOP_PX = 5

export function useSlotGridDrag(options: SlotGridDragOptions) {
  const { isTouch } = useDevice()

  const dragState = ref<AppointmentDragState | null>(null)
  const createDragState = ref<CreateDragState | null>(null)

  /**
   * The appointment a finger has long-pressed. Null with a mouse, which
   * needs no selection step. Drives `touch-action: none` on the block.
   */
  const selectedId = ref<string | null>(null)

  const hasMoved = ref(false)
  const wasDragging = ref(false)

  let longPressTimer: ReturnType<typeof setTimeout> | null = null
  let longPressOrigin: { x: number, y: number } | null = null
  /** The press in progress already selected its block by holding. */
  let longPressFired = false
  let activePointerId: number | null = null
  let activeElement: HTMLElement | null = null

  /**
   * Swallow the click the browser fires after a gesture that was not a
   * plain tap. `wasDragging` is what the components check before opening
   * an appointment.
   */
  function suppressNextClick() {
    wasDragging.value = true
    setTimeout(() => {
      wasDragging.value = false
    }, 300)
  }

  function cancelLongPress() {
    if (longPressTimer !== null) {
      clearTimeout(longPressTimer)
      longPressTimer = null
    }
    longPressOrigin = null
  }

  function releasePointer() {
    if (activeElement && activePointerId !== null && activeElement.hasPointerCapture(activePointerId)) {
      activeElement.releasePointerCapture(activePointerId)
    }
    activePointerId = null
    activeElement = null
  }

  /**
   * Capture the pointer on the element that started the gesture, so the
   * drag keeps tracking when the finger leaves the block — which it
   * always does, since blocks are ~28 px tall.
   */
  function capture(event: PointerEvent) {
    const el = event.currentTarget as HTMLElement | null
    if (!el) return
    activePointerId = event.pointerId
    activeElement = el
    el.setPointerCapture(event.pointerId)
  }

  function top(index: number): number {
    return options.slotTop ? options.slotTop(index) : index * options.slotHeight()
  }

  /** The slot boundary nearest to ``px``. */
  function nearestSlot(px: number): number {
    if (!options.slotTop) return Math.round(px / options.slotHeight())
    const last = options.maxSlotIndex() + 1
    let best = 0
    for (let i = 1; i <= last; i++) {
      if (Math.abs(top(i) - px) < Math.abs(top(best) - px)) best = i
    }
    return best
  }

  /** The slot that contains ``px``. */
  function slotAt(px: number): number {
    if (!options.slotTop) return Math.floor(px / options.slotHeight())
    const last = options.maxSlotIndex()
    let slot = 0
    while (slot < last && top(slot + 1) <= px) slot++
    return slot
  }

  // ---------------------------------------------------------------- create

  /**
   * Press on empty space. Dispatches on pointer capability; the two
   * paths below are genuinely different gestures, not one gesture with
   * a parameter.
   */
  function onCellPointerDown(columnIndex: number, slot: number, event: PointerEvent) {
    if (dragState.value) return
    if (isTouch.value) {
      pressCellByTouch()
    } else {
      pressCellWithMouse(columnIndex, slot, event)
    }
  }

  /**
   * Mouse and trackpad: the press opens a create-drag straight away, so
   * dragging down over the slots sizes the new appointment. Releasing
   * without moving falls through to `onCreatePoint` as a plain click.
   */
  function pressCellWithMouse(columnIndex: number, slot: number, event: PointerEvent) {
    event.preventDefault()
    capture(event)
    createDragState.value = {
      columnIndex,
      startSlot: slot,
      currentSlot: slot,
      startY: event.clientY
    }
  }

  /**
   * Finger and stylus: no drag at all. Sizing by dragging would need
   * `touch-action: none` across the whole canvas, trading the grid's
   * scrolling for one field the modal already has, so the press only
   * clears the selection and the `click` that follows creates the
   * appointment at the default duration.
   */
  function pressCellByTouch() {
    selectedId.value = null
  }

  // ------------------------------------------------------------ move/resize

  /**
   * Shared by both capabilities on purpose. Once a drag has actually
   * started, a finger and a mouse want exactly the same thing, and a
   * second copy of this arithmetic is how the density bug came to be
   * present in both grids at once. Split where the paths differ; share
   * where they do not.
   */
  function beginAppointmentDrag(intent: DragIntent, event: PointerEvent) {
    const startTop = top(intent.startSlot)
    const height = top(Math.max(intent.startSlot + 1, intent.endSlot)) - startTop
    dragState.value = {
      type: intent.type,
      appointmentId: intent.appointmentId,
      startX: event.clientX,
      startY: event.clientY,
      originalTop: startTop,
      originalHeight: height,
      originalColumnIndex: intent.columnIndex,
      currentColumnIndex: intent.columnIndex,
      currentTop: startTop,
      currentHeight: height
    }
    capture(event)
  }

  /**
   * Press on an existing appointment, to move or resize it. Dispatches
   * on pointer capability: the two paths are different state machines,
   * and the difference is entirely about whether the press might still
   * turn out to be a scroll.
   */
  function onAppointmentPointerDown(intent: DragIntent, event: PointerEvent) {
    event.stopPropagation()
    if (isTouch.value) {
      pressAppointmentByTouch(intent, event)
    } else {
      pressAppointmentWithMouse(intent, event)
    }
  }

  /**
   * Mouse and trackpad: a press is unambiguous — the cursor was already
   * over the block, nothing else could have been meant by it — so the
   * drag starts on the spot, with no selection step.
   */
  function pressAppointmentWithMouse(intent: DragIntent, event: PointerEvent) {
    event.preventDefault()
    beginAppointmentDrag(intent, event)
  }

  /**
   * Finger and stylus: a press is ambiguous with a scroll, so the block
   * has to be picked first.
   *
   * Already selected — the user has said which block they mean, and
   * `touch-action: none` has been on it since, so the browser will not
   * claim this gesture for a scroll. Drag immediately.
   *
   * Not selected — arm a long press and, crucially, do NOT preventDefault:
   * this press may still be a scroll, and stealing it would freeze the
   * grid under the finger.
   */
  function pressAppointmentByTouch(intent: DragIntent, event: PointerEvent) {
    if (selectedId.value === intent.appointmentId) {
      event.preventDefault()
      beginAppointmentDrag(intent, event)
      return
    }

    longPressOrigin = { x: event.clientX, y: event.clientY }
    longPressFired = false
    longPressTimer = setTimeout(() => {
      longPressTimer = null
      selectedId.value = intent.appointmentId
      // The release that follows still fires a click, which would open
      // the appointment the user was only trying to pick up. It is
      // swallowed on release, not from here: a finger held past the
      // suppression window used to open the appointment after all.
      longPressFired = true
    }, LONG_PRESS_MS)
  }

  // ------------------------------------------------------------------ move

  function onPointerMove(event: PointerEvent) {
    if (longPressOrigin) {
      const moved = Math.hypot(event.clientX - longPressOrigin.x, event.clientY - longPressOrigin.y)
      if (moved > LONG_PRESS_SLOP_PX) cancelLongPress()
    }

    if (createDragState.value) {
      const deltaY = event.clientY - createDragState.value.startY
      const under = slotAt(top(createDragState.value.startSlot) + Math.max(0, deltaY))
      createDragState.value.currentSlot = Math.max(
        createDragState.value.startSlot,
        Math.min(options.maxSlotIndex(), under)
      )
      return
    }

    const state = dragState.value
    if (!state) return

    const deltaY = event.clientY - state.startY
    const deltaX = event.clientX - state.startX

    if (Math.abs(deltaY) > DRAG_SLOP_PX || Math.abs(deltaX) > DRAG_SLOP_PX) {
      hasMoved.value = true
    }

    const startSlot = nearestSlot(state.originalTop)
    if (state.type === 'resize') {
      const endSlot = Math.max(
        startSlot + 1,
        nearestSlot(state.originalTop + state.originalHeight + deltaY)
      )
      state.currentHeight = top(endSlot) - state.originalTop
      return
    }

    const duration = nearestSlot(state.originalTop + state.originalHeight) - startSlot
    const newStart = Math.min(
      nearestSlot(Math.max(0, state.originalTop + deltaY)),
      options.maxSlotIndex() + 1 - duration
    )
    state.currentTop = top(newStart)
    state.currentHeight = top(newStart + duration) - state.currentTop

    const container = options.containerRef.value
    const columns = options.columnCount()
    if (container && columns > 1) {
      const columnWidth = container.offsetWidth / (columns + options.gutterColumns)
      const columnDelta = Math.round(deltaX / columnWidth)
      state.currentColumnIndex = Math.max(
        0,
        Math.min(columns - 1, state.originalColumnIndex + columnDelta)
      )
    }
  }

  // ------------------------------------------------------------------- end

  function onPointerUp() {
    cancelLongPress()
    releasePointer()
    if (longPressFired) {
      longPressFired = false
      suppressNextClick()
    }

    if (createDragState.value) {
      const { columnIndex, startSlot, currentSlot } = createDragState.value
      createDragState.value = null
      if (currentSlot > startSlot) {
        options.onCreateRange(columnIndex, startSlot, currentSlot + 1)
      } else {
        options.onCreatePoint(columnIndex, startSlot)
      }
      return
    }

    // Suppress the click the browser fires after a drag, so releasing a
    // moved appointment does not also open it.
    if (hasMoved.value) suppressNextClick()
    hasMoved.value = false

    const state = dragState.value
    dragState.value = null
    if (!state) return

    if (state.type === 'resize') {
      options.onResize(state.appointmentId, nearestSlot(state.originalTop + state.currentHeight))
      return
    }

    const newStartSlot = nearestSlot(state.currentTop)
    options.onMove(
      state.appointmentId,
      state.currentColumnIndex,
      newStartSlot,
      nearestSlot(state.currentTop + state.currentHeight)
    )
  }

  function onPointerCancel() {
    cancelLongPress()
    releasePointer()
    longPressFired = false
    createDragState.value = null
    dragState.value = null
    hasMoved.value = false
  }

  /** Tap on empty space clears the touch selection. */
  function clearSelection() {
    selectedId.value = null
  }

  onUnmounted(() => {
    cancelLongPress()
    releasePointer()
  })

  return {
    dragState,
    createDragState,
    selectedId,
    wasDragging,
    isTouch,
    onCellPointerDown,
    onAppointmentPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    clearSelection
  }
}
