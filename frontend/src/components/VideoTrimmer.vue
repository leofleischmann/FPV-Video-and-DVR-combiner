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
        style="width:100%; max-height: 360px; background:#000; border-radius: 8px;"
      />
    </div>
    <div v-else class="muted">Keine Vorschau verfügbar.</div>

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
          step="0.01"
          :value="modelValue.start"
          @input="onStartInput"
        />
        <input
          type="range"
          :min="0"
          :max="duration || 0"
          step="0.01"
          :value="effectiveEnd"
          @input="onEndInput"
        />
      </div>
      <div class="range-row" style="margin-top: .25rem">
        <span class="time">{{ formatTime(modelValue.start) }}</span>
        <button @click="setStartFromVideo">Start hier</button>
        <button @click="setEndFromVideo">Ende hier</button>
        <button class="ghost" @click="reset">Reset</button>
        <span class="time" style="margin-left:auto">{{ formatTime(effectiveEnd) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, default: '' },
  modelValue: { type: Object, required: true }, // { start, end | null }
  duration: { type: Number, default: 0 },
})
const emit = defineEmits(['update:modelValue', 'duration'])

const videoEl = ref(null)
const currentTime = ref(0)

const effectiveEnd = computed(() => props.modelValue.end ?? props.duration ?? 0)
const pctStart = computed(() => props.duration ? (props.modelValue.start / props.duration) * 100 : 0)
const pctEnd = computed(() => props.duration ? (effectiveEnd.value / props.duration) * 100 : 100)

function emitUpdate(patch) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function onStartInput(e) {
  const v = parseFloat(e.target.value)
  const end = effectiveEnd.value
  emitUpdate({ start: Math.min(v, Math.max(0, end - 0.05)) })
}

function onEndInput(e) {
  const v = parseFloat(e.target.value)
  const minEnd = props.modelValue.start + 0.05
  emitUpdate({ end: Math.max(v, minEnd) })
}

function setStartFromVideo() {
  if (!videoEl.value) return
  emitUpdate({ start: Math.min(videoEl.value.currentTime, effectiveEnd.value - 0.05) })
}
function setEndFromVideo() {
  if (!videoEl.value) return
  emitUpdate({ end: Math.max(videoEl.value.currentTime, props.modelValue.start + 0.05) })
}
function reset() {
  emitUpdate({ start: 0, end: null })
}

function onMetadata() {
  if (videoEl.value && !isNaN(videoEl.value.duration)) {
    emit('duration', videoEl.value.duration)
  }
}
function onTimeUpdate() {
  if (videoEl.value) currentTime.value = videoEl.value.currentTime
}

function formatTime(s) {
  if (!isFinite(s)) return '0:00.0'
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1)
  return `${m}:${sec.padStart(4, '0')}`
}

watch(() => props.src, () => { currentTime.value = 0 })
</script>
