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
        @loadedmetadata="onBaseMeta"
        @timeupdate="onBaseTimeUpdate"
        @durationchange="onBaseMeta"
        @click="togglePlay"
      />
      <div v-else class="base" style="display:flex;align-items:center;justify-content:center;color:#888;height:100%;">
        Hi-Res Vorschau wird gerade generiert …
      </div>

      <div
        v-if="stageW > 0"
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
          v-if="dvrSrc"
          ref="dvrEl"
          :src="dvrSrc"
          muted
          playsinline
          preload="metadata"
          @loadedmetadata="onDvrMeta"
        />
        <div
          v-else
          style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#aaa;font-size:.8rem;text-align:center;padding:.25rem;line-height:1.2"
        >
          DVR-Vorschau<br/>wird transcodiert …
        </div>
        <div
          class="resize-handle"
          @mousedown.stop="startResize"
          @touchstart.passive.stop="startResize"
        />
      </div>
    </div>

    <!-- Master playback bar driving BOTH videos in sync along the output timeline. -->
    <div v-if="hiresSrc" style="margin-top:.6rem;display:flex;flex-direction:column;gap:.4rem">
      <input
        type="range"
        :min="0"
        :max="outputDuration || 0"
        step="0.01"
        :value="playhead"
        @input="onSeek"
        title="Output-Position"
      />
      <div style="display:flex;gap:.4rem;align-items:center;flex-wrap:wrap">
        <button @click="togglePlay" :title="playing ? 'Pause' : 'Play'">
          {{ playing ? '⏸' : '▶' }}
        </button>
        <button @click="skip(-1)" title="−1 s">−1 s</button>
        <button @click="skip(-0.1)" title="−100 ms">−0.1 s</button>
        <button @click="nudgeFrame(-1)" title="ein Frame zurück">◀ frame</button>
        <button @click="nudgeFrame(1)" title="ein Frame vor">frame ▶</button>
        <button @click="skip(0.1)" title="+100 ms">+0.1 s</button>
        <button @click="skip(1)" title="+1 s">+1 s</button>
        <button @click="toggleFullscreen" title="Vollbild">⛶ Großbild</button>
        <span class="time" style="margin-left:auto;font-variant-numeric: tabular-nums">
          {{ formatTime(playhead) }} / {{ formatTime(outputDuration) }}
        </span>
      </div>
      <div class="muted" style="font-size:.8rem">
        Beide Videos sind über die Output-Timeline synchronisiert (Hi-Res ab
        {{ formatTime(hiresTrim.start || 0) }}, DVR ab {{ formatTime(dvrTrim.start || 0) }}).
        Änderungen oben im Trim-Bereich wirken sich sofort hier aus.
      </div>
    </div>

    <!-- PIP layout sliders -->
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
  hiresTrim: { type: Object, default: () => ({ start: 0, end: null }) },
  dvrTrim: { type: Object, default: () => ({ start: 0, end: null }) },
  hiresDuration: { type: Number, default: 0 },
  dvrDuration: { type: Number, default: 0 },
  fps: { type: Number, default: 30 },
})
const emit = defineEmits(['update:modelValue'])

const stageEl = ref(null)
const baseEl = ref(null)
const dvrEl = ref(null)
const stageW = ref(0)
const stageH = ref(0)
const dvrAspect = ref(16 / 9)

const aspect = computed(() => `${props.outputWidth} / ${props.outputHeight}`)

// PiP overlay height in stage pixels.
const pipHeightPx = computed(() => {
  if (stageW.value === 0) return 0
  const wPx = props.modelValue.width * stageW.value
  return wPx / dvrAspect.value
})

// ---------------------------------------------------------------------------
// Master playback driving both <video>s along the OUTPUT timeline:
//   hires.currentTime = hiresTrim.start + playhead
//   dvr.currentTime   = dvrTrim.start   + playhead
// "playhead" is in output seconds (0..outputDuration).
// ---------------------------------------------------------------------------
const playhead = ref(0)
const playing = ref(false)

const hiresEffEnd = computed(() => props.hiresTrim.end ?? props.hiresDuration ?? 0)
const outputDuration = computed(() =>
  Math.max(0, hiresEffEnd.value - (props.hiresTrim.start || 0))
)

let suppressBaseUpdate = false  // avoid feedback loops while we seek programmatically

function targetHires() { return (props.hiresTrim.start || 0) + playhead.value }
function targetDvr()   { return (props.dvrTrim.start || 0) + playhead.value }

function syncVideosToPlayhead() {
  const v = baseEl.value
  if (v && isFinite(v.duration)) {
    const t = targetHires()
    if (Math.abs(v.currentTime - t) > 0.03) {
      suppressBaseUpdate = true
      try { v.currentTime = Math.max(0, Math.min(v.duration, t)) } catch { /* ignore */ }
    }
  }
  const d = dvrEl.value
  if (d && isFinite(d.duration)) {
    const t = targetDvr()
    if (Math.abs(d.currentTime - t) > 0.03) {
      try { d.currentTime = Math.max(0, Math.min(d.duration, t)) } catch { /* ignore */ }
    }
  }
}

// External trim changes (frame nudges in the trim component above) should
// immediately re-seek both videos so the user can verify the alignment.
watch(
  () => [props.hiresTrim.start, props.dvrTrim.start],
  () => syncVideosToPlayhead(),
)

// If the trim end shrinks below the playhead, clamp.
watch(outputDuration, (d) => {
  if (playhead.value > d) {
    playhead.value = d
    syncVideosToPlayhead()
  }
})

function onBaseMeta() {
  syncVideosToPlayhead()
}
function onDvrMeta() {
  if (dvrEl.value && dvrEl.value.videoWidth && dvrEl.value.videoHeight) {
    dvrAspect.value = dvrEl.value.videoWidth / dvrEl.value.videoHeight
    patchPip({})
  }
  syncVideosToPlayhead()
}

function onBaseTimeUpdate() {
  if (suppressBaseUpdate) { suppressBaseUpdate = false; return }
  const v = baseEl.value
  if (!v) return
  // Map hires time back onto the output timeline.
  const out = v.currentTime - (props.hiresTrim.start || 0)
  playhead.value = Math.max(0, Math.min(outputDuration.value, out))
  // Keep the DVR overlay in lockstep.
  const d = dvrEl.value
  if (d && isFinite(d.duration)) {
    const t = targetDvr()
    if (Math.abs(d.currentTime - t) > 0.05) {
      try { d.currentTime = Math.max(0, Math.min(d.duration, t)) } catch { /* ignore */ }
    }
  }
  // Auto-stop at the end of the output range.
  if (playing.value && out >= outputDuration.value) {
    pauseAll()
  }
}

function onSeek(e) {
  playhead.value = parseFloat(e.target.value)
  syncVideosToPlayhead()
}

function skip(deltaSec) {
  playhead.value = Math.max(0, Math.min(outputDuration.value, playhead.value + deltaSec))
  syncVideosToPlayhead()
}
function nudgeFrame(frames) {
  skip(frames / Math.max(1, props.fps))
}

function playAll() {
  const v = baseEl.value
  const d = dvrEl.value
  if (!v) return
  // If we're past the end, restart.
  if (playhead.value >= outputDuration.value - 0.001) {
    playhead.value = 0
    syncVideosToPlayhead()
  }
  v.play().catch(() => {})
  d?.play().catch(() => {})
  playing.value = true
}
function pauseAll() {
  baseEl.value?.pause()
  dvrEl.value?.pause()
  playing.value = false
}
function togglePlay() {
  if (playing.value) pauseAll(); else playAll()
}

function toggleFullscreen() {
  const target = stageEl.value
  if (!target) return
  if (document.fullscreenElement) {
    document.exitFullscreen?.()
  } else if (target.requestFullscreen) {
    target.requestFullscreen().catch(() => {})
  } else if (target.webkitRequestFullscreen) {
    target.webkitRequestFullscreen()
  }
}

function formatTime(s) {
  if (!isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(2)
  return `${m}:${sec.padStart(5, '0')}`
}

// ---------------------------------------------------------------------------
// PiP layout (drag/resize) — unchanged from the previous version.
// ---------------------------------------------------------------------------
function set(key, e) {
  patchPip({ [key]: parseFloat(e.target.value) })
}

function patchPip(obj) {
  const next = { ...props.modelValue, ...obj }
  next.x = Math.max(0, Math.min(1, next.x))
  next.y = Math.max(0, Math.min(1, next.y))
  next.width = Math.max(0.05, Math.min(1, next.width))
  const wFracOfStage = next.width
  const hFracOfStage =
    stageH.value > 0
      ? (next.width * stageW.value / dvrAspect.value) / stageH.value
      : 0
  next.x = Math.min(next.x, Math.max(0, 1 - wFracOfStage))
  next.y = Math.min(next.y, Math.max(0, 1 - hFracOfStage))
  emit('update:modelValue', next)
}

const isDragging = ref(false)
let dragKind = null
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
  dragStart = { px: p.x, py: p.y, x0: props.modelValue.x, y0: props.modelValue.y }
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
  dragStart = { px: p.x, py: p.y, w0: props.modelValue.width }
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
    patchPip({
      x: dragStart.x0 + dx / stageW.value,
      y: dragStart.y0 + dy / stageH.value,
    })
  } else if (dragKind === 'resize') {
    patchPip({ width: dragStart.w0 + dx / stageW.value })
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
  pauseAll()
})
watch(() => [props.outputWidth, props.outputHeight], measure)
</script>
