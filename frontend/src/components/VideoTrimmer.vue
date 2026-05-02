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
        style="width:100%; max-height: 360px; background:#000; border-radius: 8px;"
      />
    </div>
    <div
      v-else-if="duration > 0"
      class="trim-audio-only"
      aria-hidden="true"
    >
      ♪
    </div>
    <div
      v-else
      class="muted"
      style="background:#000;border-radius:8px;padding:2rem;text-align:center;border:1px dashed var(--border)"
    >
      …
    </div>

    <div v-if="src" class="trim-scrub">
      <span class="trim-scrub__playhead-icon" aria-hidden="true" />
      <input
        type="text"
        class="trim-scrub__time"
        :value="formatTime(currentTime)"
        @change="onCurrentTimeInput"
      />
      <div class="trim-scrub__nudges">
        <button type="button" class="btn-nudge" @click="nudge(-1)">−1</button>
        <button type="button" class="btn-nudge" @click="nudge(-0.1)">−0.1</button>
        <button type="button" class="btn-nudge" @click="nudgeFrame(-1)">◀</button>
        <button type="button" class="btn-nudge" @click="nudgeFrame(1)">▶</button>
        <button type="button" class="btn-nudge" @click="nudge(0.1)">+0.1</button>
        <button type="button" class="btn-nudge" @click="nudge(1)">+1</button>
      </div>
      <span class="trim-scrub__fps muted" style="font-size:.72rem;margin-left:auto">{{ fps.toFixed(0) }} fps</span>
    </div>

    <div v-if="duration > 0" style="margin-top: .75rem">
      <div class="dual-range dual-range--trim">
        <div class="track" />
        <div
          class="selection"
          :style="{ left: pctStart + '%', right: (100 - pctEnd) + '%' }"
        />
        <div
          v-if="duration > 0"
          class="playhead"
          :style="{ left: playheadPct + '%' }"
        />
        <input
          type="range"
          class="range-start"
          :min="0"
          :max="duration || 0"
          step="0.001"
          :value="modelValue.start"
          @input="onStartInput"
        />
        <input
          type="range"
          class="range-end"
          :min="0"
          :max="duration || 0"
          step="0.001"
          :value="effectiveEnd"
          @input="onEndInput"
        />
      </div>

      <div class="trim-marks-grid">
        <div class="trim-mark-col trim-mark-col--in">
          <div class="trim-mark-head">
            <span class="trim-dot trim-dot--in" />
          </div>
          <input
            type="text"
            class="trim-mark-time"
            :value="formatTime(modelValue.start)"
            @change="onStartTextInput"
          />
          <button type="button" class="btn-mark-in" @click="setStartFromVideo">[</button>
          <button type="button" class="btn-nudge" @click="bumpStart(-1)">◀</button>
          <button type="button" class="btn-nudge" @click="bumpStart(1)">▶</button>
        </div>

        <div class="trim-mark-col trim-mark-col--out">
          <div class="trim-mark-head">
            <span class="trim-dot trim-dot--out" />
          </div>
          <input
            type="text"
            class="trim-mark-time"
            :value="formatTime(effectiveEnd)"
            @change="onEndTextInput"
          />
          <button type="button" class="btn-mark-out" @click="setEndFromVideo">]</button>
          <button type="button" class="btn-nudge" @click="bumpEnd(-1)">◀</button>
          <button type="button" class="btn-nudge" @click="bumpEnd(1)">▶</button>
        </div>

        <div class="trim-mark-col trim-mark-col--dur">
          <span class="trim-duration-icon" aria-hidden="true">⏱</span>
          <span class="trim-duration-val">{{ formatTime(effectiveEnd - modelValue.start) }}</span>
          <button type="button" class="ghost btn-icon-reset" @click="reset">↺</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  modelValue: { type: Object, required: true },
  duration: { type: Number, default: 0 },
  playbackMax: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue', 'duration'])

const videoEl = ref(null)
const currentTime = ref(0)
const fps = ref(30)

const effectiveEnd = computed(() => props.modelValue.end ?? props.duration ?? 0)
const pctStart = computed(() => props.duration ? (props.modelValue.start / props.duration) * 100 : 0)
const pctEnd = computed(() => props.duration ? (effectiveEnd.value / props.duration) * 100 : 100)
const playheadPct = computed(() => {
  if (!props.duration || props.duration <= 0) return 0
  return Math.min(100, Math.max(0, (currentTime.value / props.duration) * 100))
})

function emitUpdate(patch) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

function videoSeekHi() {
  const v = videoEl.value
  const vd = v && isFinite(v.duration) && v.duration > 0 ? v.duration : Infinity
  if (props.playbackMax > 0) return Math.min(props.playbackMax, vd)
  return Math.min(props.duration || Infinity, vd)
}

function onStartInput(e) {
  const v = parseFloat(e.target.value)
  emitUpdate({ start: clamp(v, 0, Math.max(0, effectiveEnd.value - 0.001)) })
}
function onEndInput(e) {
  const v = parseFloat(e.target.value)
  emitUpdate({ end: clamp(v, props.modelValue.start + 0.001, props.duration || v) })
}

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

function bumpStart(frames) {
  const dt = frames / Math.max(1, fps.value)
  emitUpdate({ start: clamp(props.modelValue.start + dt, 0, effectiveEnd.value - 0.001) })
}
function bumpEnd(frames) {
  const dt = frames / Math.max(1, fps.value)
  emitUpdate({ end: clamp(effectiveEnd.value + dt, props.modelValue.start + 0.001, props.duration || Infinity) })
}

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

function onMetadata() {
  const v = videoEl.value
  if (!v) return
  if (isFinite(v.duration) && v.duration > 0) {
    emit('duration', v.duration)
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

<style scoped>
.trim-audio-only {
  background: var(--panel-2);
  border-radius: 8px;
  border: 1px dashed var(--border);
  padding: 1.25rem;
  text-align: center;
  font-size: 2rem;
  line-height: 1;
  opacity: 0.85;
}
.trim-scrub {
  margin-top: 0.6rem;
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}
.trim-scrub__playhead-icon {
  width: 3px;
  height: 1rem;
  background: var(--mark-playhead);
  border-radius: 1px;
  flex-shrink: 0;
}
.trim-scrub__time {
  width: 7em;
  font-variant-numeric: tabular-nums;
  text-align: center;
  padding: 0.35rem 0.4rem;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 0.88rem;
}
.trim-scrub__nudges {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
}
.trim-marks-grid {
  margin-top: 0.65rem;
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 0.5rem 0.75rem;
  align-items: end;
}
@media (max-width: 720px) {
  .trim-marks-grid {
    grid-template-columns: 1fr;
  }
}
.trim-mark-col {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}
.trim-mark-col--dur {
  flex-direction: row;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  flex-wrap: nowrap;
}
.trim-mark-head {
  width: 100%;
  flex-basis: 100%;
  display: flex;
  align-items: center;
  min-height: 1rem;
}
.trim-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.trim-dot--in {
  background: var(--mark-in);
  box-shadow: 0 0 0 2px rgba(63, 185, 80, 0.25);
}
.trim-dot--out {
  background: var(--mark-out);
  box-shadow: 0 0 0 2px rgba(240, 136, 62, 0.25);
}
.trim-mark-time {
  width: 6.5em;
  font-variant-numeric: tabular-nums;
  padding: 0.35rem 0.35rem;
  background: var(--panel-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-size: 0.85rem;
}
.trim-duration-val {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--accent-2);
}
.trim-duration-icon {
  font-size: 1rem;
  opacity: 0.85;
}
.btn-icon-reset {
  padding: 0.4rem 0.55rem;
  font-size: 1.1rem;
  line-height: 1;
}
</style>
