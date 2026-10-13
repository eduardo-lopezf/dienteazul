<script setup lang="ts">
/**
 * A canvas the patient signs on with a finger, a stylus or a mouse.
 * Emits the drawing as a PNG data URL, or null once cleared.
 *
 * In the host because more than one App asks for a signature: a consent
 * letter (Clinical record) and the health questionnaire (Patients).
 */
const model = defineModel<string | null>({ default: null })

withDefaults(defineProps<{ testid?: string }>(), { testid: 'consent-signature-pad' })

const { t } = useI18n()
const canvas = ref<HTMLCanvasElement | null>(null)
let drawing = false
let last = { x: 0, y: 0 }

// The canvas is drawn at a fixed resolution and stretched by CSS, so a
// pointer position has to be scaled back into canvas pixels.
function point(ev: PointerEvent): { x: number, y: number } {
  const el = canvas.value!
  const rect = el.getBoundingClientRect()
  return {
    x: (ev.clientX - rect.left) * (el.width / rect.width),
    y: (ev.clientY - rect.top) * (el.height / rect.height)
  }
}

function start(ev: PointerEvent) {
  if (!canvas.value) return
  drawing = true
  last = point(ev)
  canvas.value.setPointerCapture(ev.pointerId)
}

function move(ev: PointerEvent) {
  const ctx = canvas.value?.getContext('2d')
  if (!drawing || !ctx) return
  const next = point(ev)
  ctx.strokeStyle = '#0f172a'
  ctx.lineWidth = 2.5
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(last.x, last.y)
  ctx.lineTo(next.x, next.y)
  ctx.stroke()
  last = next
}

function end() {
  if (!drawing || !canvas.value) return
  drawing = false
  model.value = canvas.value.toDataURL('image/png')
}

function clear() {
  const el = canvas.value
  el?.getContext('2d')?.clearRect(0, 0, el.width, el.height)
  model.value = null
}
</script>

<template>
  <div>
    <!-- `data-dense`: the cell is a drawing surface, not a button. -->
    <div
      data-dense
      class="rounded-md border border-default bg-white touch-none"
    >
      <canvas
        ref="canvas"
        width="800"
        height="240"
        class="block w-full h-44 cursor-crosshair"
        :data-testid="testid"
        @pointerdown="start"
        @pointermove="move"
        @pointerup="end"
        @pointercancel="end"
      />
    </div>
    <UButton
      color="neutral"
      variant="ghost"
      size="xs"
      class="mt-2"
      icon="i-lucide-eraser"
      @click="clear"
    >
      {{ t('common.clear') }}
    </UButton>
  </div>
</template>
