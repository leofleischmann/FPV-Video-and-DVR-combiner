<template>
  <div>
    <div
      ref="stageEl"
      class="pip-stage"
      :style="{ aspectRatio: aspect }"
    >
      <video
        v-if="hiresSrc"
        ref="baseEl"
        class="base"
        :src="hiresSrc"
        muted
        playsinline
        preload="metadata"
        @click="togglePlay"
      />
      <div v-else class="base" style="display:flex;align-items:center;justify-content:center;color:#888;height:100%;">
        Hi-Res Vorschau wird vorbereitet …
      </div>

      <div
        v-if="dvrSrc && stageW > 0"
        class="pip-overlay"
        :class="{ dragging: isDragging }"
        :style="{
          left: (modelValue.x * stageW) + 'px',
          top: (modelValue.y * stageH) + 'px',
          width: (modelValue.width * stageW) + 'px',
          height: pipHeightPx + 'px',
        }"
        @mousedown.stop="startDrag"
        @touchstart.passive="startDrag"
      >
        <video
          ref="dvrEl"
          :src="dvrSrc"
          muted
          playsinline
          preload="metadata"
          @loadedmetadata="onDvrMeta"
        />
        <div
          class="resize-handle"
          @mousedown.stop="startResize"
          @touchstart.passive.stop="startResize"
        />
      </div>
    </div>

    <div class="row" style="margin-top: .75rem">
      <div class="col">
        <label>X-Position (Anteil): {{ (modelValue.x * 100).toFixed(1) }} %</label>
        <input type="range" min="0" max="1" step="0.001" :value="modelValue.x" @input="set('x', $event)" />
      </div>
      <div class="col">
        <label>Y-Position (Anteil): {{ (modelValue.y * 100).toFixed(1) }} %</label>
        <input type="range" min="0" max="1" step="0.001" :value="modelValue.y" @input="set('y', $event)" />
      </div>
      <div class="col">
        <label>Breite (Anteil): {{ (modelValue.width * 100).toFixed(1) }} %</label>
        <input type="range" min="0.05" max="1" step="0.001" :value="modelValue.width" @input="set('width', $event)" />
      </div>
    </div>
    <div class="muted" style="margin-top:.5rem">
      Tipp: Overlay direkt im Vorschau-Bild ziehen oder an der orangen Ecke skalieren.
      Höhe wird automatisch aus dem DVR-Seitenverhältnis berechnet.
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  hiresSrc: { type: String, default: '' },
  dvrSrc: { type: String, default: '' },
  outputWidth: { type: Number, required: true },
  outputHeight: { type: Number, required: true },
  modelValue: { type: Object, required: true }, // {x,y,width} as fractions of OUTPUT
})
const emit = defineEmits(['update:modelValue'])

const stageEl = ref(null)
const baseEl = ref(null)
const dvrEl = ref(null)
const stageW = ref(0)
const stageH = ref(0)
const dvrAspect = ref(16 / 9) // dvrW / dvrH

const aspect = computed(() => `${props.outputWidth} / ${props.outputHeight}`)

// PiP height in pixels on the preview stage, derived from DVR aspect.
const pipHeightPx = computed(() => {
  if (stageW.value === 0) return 0
  // pip width in PIXELS on stage:
  const wPx = props.modelValue.width * stageW.value
  return wPx / dvrAspect.value
})

function set(key, e) {
  const v = parseFloat(e.target.value)
  patch({ [key]: v })
}

function patch(obj) {
  const next = { ...props.modelValue, ...obj }
  // Clamp so the overlay doesn't escape the stage.
  next.x = Math.max(0, Math.min(1, next.x))
  next.y = Math.max(0, Math.min(1, next.y))
  next.width = Math.max(0.05, Math.min(1, next.width))
  // Clamp x/y so the right/bottom edge stays on stage.
  const wFracOfStage = next.width
  const hFracOfStage =
    stageH.value > 0
      ? (next.width * stageW.value / dvrAspect.value) / stageH.value
      : 0
  next.x = Math.min(next.x, Math.max(0, 1 - wFracOfStage))
  next.y = Math.min(next.y, Math.max(0, 1 - hFracOfStage))
  emit('update:modelValue', next)
}

function onDvrMeta() {
  if (!dvrEl.value) return
  if (dvrEl.value.videoWidth && dvrEl.value.videoHeight) {
    dvrAspect.value = dvrEl.value.videoWidth / dvrEl.value.videoHeight
    patch({}) // re-clamp
  }
}

// --- drag / resize ---
const isDragging = ref(false)
let dragKind = null  // 'move' | 'resize'
let dragStart = null

function pointer(e) {
  if (e.touches && e.touches[0]) return { x: e.touches[0].clientX, y: e.touches[0].clientY }
  return { x: e.clientX, y: e.clientY }
}

function startDrag(e) {
  if (!stageEl.value) return
  isDragging.value = true
  dragKind = 'move'
  const p = pointer(e)
  dragStart = {
    px: p.x, py: p.y,
    x0: props.modelValue.x, y0: props.modelValue.y,
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', endDrag)
  window.addEventListener('touchmove', onMove, { passive: false })
  window.addEventListener('touchend', endDrag)
}
function startResize(e) {
  if (!stageEl.value) return
  isDragging.value = true
  dragKind = 'resize'
  const p = pointer(e)
  dragStart = {
    px: p.x, py: p.y,
    w0: props.modelValue.width,
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', endDrag)
  window.addEventListener('touchmove', onMove, { passive: false })
  window.addEventListener('touchend', endDrag)
}
function onMove(e) {
  if (!dragStart) return
  if (e.cancelable) e.preventDefault()
  const p = pointer(e)
  const dx = p.x - dragStart.px
  const dy = p.y - dragStart.py
  if (dragKind === 'move') {
    patch({
      x: dragStart.x0 + dx / stageW.value,
      y: dragStart.y0 + dy / stageH.value,
    })
  } else if (dragKind === 'resize') {
    patch({
      width: dragStart.w0 + dx / stageW.value,
    })
  }
}
function endDrag() {
  isDragging.value = false
  dragKind = null
  dragStart = null
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', endDrag)
  window.removeEventListener('touchmove', onMove)
  window.removeEventListener('touchend', endDrag)
}

// --- size tracking ---
let ro = null
function measure() {
  if (!stageEl.value) return
  const r = stageEl.value.getBoundingClientRect()
  stageW.value = r.width
  stageH.value = r.height
}
onMounted(() => {
  measure()
  ro = new ResizeObserver(measure)
  ro.observe(stageEl.value)
  window.addEventListener('resize', measure)
})
onBeforeUnmount(() => {
  ro?.disconnect()
  window.removeEventListener('resize', measure)
  endDrag()
})
watch(() => [props.outputWidth, props.outputHeight], measure)

function togglePlay() {
  const v = baseEl.value
  if (!v) return
  if (v.paused) v.play().catch(() => {}); else v.pause()
  if (dvrEl.value) {
    if (v.paused) dvrEl.value.pause()
    else dvrEl.value.play().catch(() => {})
  }
}
</script>
