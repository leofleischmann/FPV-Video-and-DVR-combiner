<template>
  <div>
    <div v-if="src">
      <video
        ref="videoEl"
        class="base"
        :src="src"
        controls
        muted
        preload="metadata"
        @loadedmetadata="onMetadata"
        @timeupdate="onTimeUpdate"
        @durationchange="onMetadata"
        @play="playing = true"
        @pause="playing = false"
        style="width:100%; max-height: 360px; background:#000; border-radius: 8px;"
      />
    </div>
    <div
      v-else
      class="muted"
      style="background:#000;border-radius:8px;padding:2rem;text-align:center;border:1px dashed var(--border)"
    >
      Vorschau wird gerade generiert (Transcode läuft im Worker) …
    </div>

    <!-- Live position + nudge buttons (operate on the video's currentTime) -->
    <div v-if="src" style="margin-top:.6rem;display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
      <span class="muted" style="font-size:.8rem">Position:</span>
      <input
        type="text"
        :value="formatTime(currentTime)"
        @change="onCurrentTimeInput"
        style="width:7em;font-variant-numeric: tabular-nums;text-align:center"
        title="Direkt eingeben: m:ss.mmm oder Sekunden"
      />
      <button @click="nudge(-1)" title="−1 Sekunde">−1 s</button>
      <button @click="nudge(-0.1)" title="−100 ms">−0.1 s</button>
      <button @click="nudgeFrame(-1)" title="ein Frame zurück">◀ frame</button>
      <button @click="nudgeFrame(1)" title="ein Frame vor">frame ▶</button>
      <button @click="nudge(0.1)" title="+100 ms">+0.1 s</button>
      <button @click="nudge(1)" title="+1 Sekunde">+1 s</button>
      <span class="muted" style="font-size:.75rem;margin-left:auto">
        ~{{ fps.toFixed(2) }} fps
      </span>
    </div>

    <!-- Trim selection (dual range) -->
    <div style="margin-top: .75rem">
      <div class="dual-range">
        <div class="track" />
        <div
          class="selection"
          :style="{ left: pctStart + '%', right: (100 - pctEnd) + '%' }"
        />
        <input
          type="range"
          :min="0"
          :max="duration || 0"
          step="0.001"
          :value="modelValue.start"
          @input="onStartInput"
        />
        <input
          type="range"
          :min="0"
          :max="duration || 0"
          step="0.001"
          :value="effectiveEnd"
          @input="onEndInput"
        />
      </div>

      <div class="row" style="margin-top: .5rem;align-items:flex-end">
        <div class="col" style="min-width: 220px">
          <label>Start</label>
          <div style="display:flex;gap:.25rem;align-items:center;flex-wrap:wrap">
            <input
              type="text"
              :value="formatTime(modelValue.start)"
              @change="onStartTextInput"
              style="width:7em;font-variant-numeric: tabular-nums"
            />
            <button @click="setStartFromVideo" title="aktuelle Position als Start übernehmen">Start hier</button>
            <button @click="bumpStart(-1)" title="−1 Frame">◀</button>
            <button @click="bumpStart(1)" title="+1 Frame">▶</button>
          </div>
        </div>

        <div class="col" style="min-width: 220px">
          <label>Ende</label>
          <div style="display:flex;gap:.25rem;align-items:center;flex-wrap:wrap">
            <input
              type="text"
              :value="formatTime(effectiveEnd)"
              @change="onEndTextInput"
              style="width:7em;font-variant-numeric: tabular-nums"
            />
            <button @click="setEndFromVideo" title="aktuelle Position als Ende übernehmen">Ende hier</button>
            <button @click="bumpEnd(-1)" title="−1 Frame">◀</button>
            <button @click="bumpEnd(1)" title="+1 Frame">▶</button>
          </div>
        </div>

        <div class="col" style="min-width: 140px">
          <label>Dauer</label>
          <div style="display:flex;align-items:center;gap:.5rem">
            <span style="font-variant-numeric: tabular-nums">{{ formatTime(effectiveEnd - modelValue.start) }}</span>
            <button class="ghost" @click="reset">Reset</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  modelValue: { type: Object, required: true }, // { start, end | null }
  /** Timeline length for trim sliders (can span multiple source files). */
  duration: { type: Number, default: 0 },
  /**
   * If > 0, video seek/nudge/position is capped here (e.g. first chunk only)
   * while `duration` can be longer for trim end/start across a merged timeline.
   */
  playbackMax: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue', 'duration'])

const videoEl = ref(null)
const currentTime = ref(0)
const playing = ref(false)
const fps = ref(30) // Best guess until metadata yields a better number.

const effectiveEnd = computed(() => props.modelValue.end ?? props.duration ?? 0)
const pctStart = computed(() => props.duration ? (props.modelValue.start / props.duration) * 100 : 0)
const pctEnd = computed(() => props.duration ? (effectiveEnd.value / props.duration) * 100 : 100)

function emitUpdate(patch) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

/** Upper bound for <video>.currentTime (preview may be shorter than trim timeline). */
function videoSeekHi() {
  const v = videoEl.value
  const vd = v && isFinite(v.duration) && v.duration > 0 ? v.duration : Infinity
  if (props.playbackMax > 0) return Math.min(props.playbackMax, vd)
  return Math.min(props.duration || Infinity, vd)
}

// ----- range sliders -----
function onStartInput(e) {
  const v = parseFloat(e.target.value)
  emitUpdate({ start: clamp(v, 0, Math.max(0, effectiveEnd.value - 0.001)) })
}
function onEndInput(e) {
  const v = parseFloat(e.target.value)
  emitUpdate({ end: clamp(v, props.modelValue.start + 0.001, props.duration || v) })
}

// ----- "Start hier" / "Ende hier" -----
function setStartFromVideo() {
  if (!videoEl.value) return
  emitUpdate({ start: clamp(videoEl.value.currentTime, 0, effectiveEnd.value - 0.001) })
}
function setEndFromVideo() {
  if (!videoEl.value) return
  emitUpdate({ end: clamp(videoEl.value.currentTime, props.modelValue.start + 0.001, props.duration || Infinity) })
}
function reset() {
  emitUpdate({ start: 0, end: null })
}

// ----- frame-precise bumping for start/end -----
function bumpStart(frames) {
  const dt = frames / Math.max(1, fps.value)
  emitUpdate({ start: clamp(props.modelValue.start + dt, 0, effectiveEnd.value - 0.001) })
}
function bumpEnd(frames) {
  const dt = frames / Math.max(1, fps.value)
  emitUpdate({ end: clamp(effectiveEnd.value + dt, props.modelValue.start + 0.001, props.duration || Infinity) })
}

// ----- direct text entry of times -----
function parseTime(text) {
  if (text == null) return NaN
  const t = String(text).trim()
  if (/^\d+(\.\d+)?$/.test(t)) return parseFloat(t)
  const m = t.match(/^(\d+):(\d{1,2})(?:\.(\d{1,3}))?$/)
  if (m) {
    const min = parseInt(m[1], 10)
    const sec = parseInt(m[2], 10)
    const ms = m[3] ? parseFloat('0.' + m[3]) : 0
    return min * 60 + sec + ms
  }
  return NaN
}
function onStartTextInput(e) {
  const v = parseTime(e.target.value)
  if (!isFinite(v)) return
  emitUpdate({ start: clamp(v, 0, effectiveEnd.value - 0.001) })
}
function onEndTextInput(e) {
  const v = parseTime(e.target.value)
  if (!isFinite(v)) return
  emitUpdate({ end: clamp(v, props.modelValue.start + 0.001, props.duration || v) })
}

// ----- live playback position controls -----
function nudge(deltaSec) {
  const v = videoEl.value
  if (!v) return
  v.currentTime = clamp(v.currentTime + deltaSec, 0, videoSeekHi())
  currentTime.value = v.currentTime
}
function nudgeFrame(frames) {
  nudge(frames / Math.max(1, fps.value))
}
function onCurrentTimeInput(e) {
  const v = parseTime(e.target.value)
  if (!isFinite(v) || !videoEl.value) return
  videoEl.value.currentTime = clamp(v, 0, videoSeekHi())
  currentTime.value = videoEl.value.currentTime
}

// ----- metadata + playback events -----
function onMetadata() {
  const v = videoEl.value
  if (!v) return
  if (isFinite(v.duration) && v.duration > 0) {
    emit('duration', v.duration)
  }
  // Try to read fps from the WebKit-only API; otherwise leave the default.
  // (browsers don't generally expose fps; this is a best-effort hint.)
  // @ts-ignore
  if (v.getVideoPlaybackQuality && v.webkitVideoDecodedByteCount) {
    // no-op; just hinting where fps could be derived
  }
}
function onTimeUpdate() {
  if (videoEl.value) currentTime.value = videoEl.value.currentTime
}

function formatTime(s) {
  if (!isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(3)
  return `${m}:${sec.padStart(6, '0')}`
}

watch(() => props.src, () => { currentTime.value = 0 })
</script>
