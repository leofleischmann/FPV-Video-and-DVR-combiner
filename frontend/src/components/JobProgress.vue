<template>
  <div>
    <div v-if="!status">
      <div class="muted">Job wird gestartet …</div>
    </div>
    <div v-else>
      <div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.25rem">
        <strong>{{ stateLabel }}</strong>
        <span class="muted">{{ status.stage || '' }}</span>
        <span style="margin-left:auto;font-variant-numeric: tabular-nums">{{ Math.round((status.progress || 0) * 100) }} %</span>
      </div>
      <div class="progress"><div class="bar" :style="{ width: ((status.progress || 0) * 100) + '%' }" /></div>
      <div v-if="status.message" class="muted" style="margin-top:.25rem">{{ status.message }}</div>
      <div v-if="status.error" class="error">Fehler: {{ status.error }}</div>

      <div v-if="status.state === 'SUCCESS' && status.output_filename" style="margin-top:1rem">
        <h3 style="margin-bottom:.5rem">Vorschau des fertigen Videos</h3>

        <div ref="playerWrap" style="position:relative;background:#000;border-radius:8px;overflow:hidden">
          <video
            ref="resultVideoEl"
            :src="previewUrl"
            preload="metadata"
            playsinline
            style="width:100%;max-height:540px;display:block;background:#000"
            @loadedmetadata="onResultMeta"
            @durationchange="onResultMeta"
            @timeupdate="onResultTimeUpdate"
            @play="resultPlaying = true"
            @pause="resultPlaying = false"
            @volumechange="onVolumeChange"
            @click="togglePlay"
          />
        </div>

        <!-- Custom playback bar -->
        <div style="margin-top:.5rem;display:flex;flex-direction:column;gap:.4rem">
          <input
            type="range"
            min="0"
            :max="resultDuration || 0"
            step="0.05"
            :value="resultTime"
            @input="onSeek"
            style="width:100%"
            title="Position"
          />
          <div style="display:flex;gap:.4rem;align-items:center;flex-wrap:wrap">
            <button @click="togglePlay" :title="resultPlaying ? 'Pause (Space)' : 'Play (Space)'">
              {{ resultPlaying ? '⏸' : '▶' }}
            </button>
            <button @click="skip(-10)" title="−10 Sekunden">⏪ 10 s</button>
            <button @click="skip(-1)" title="−1 Sekunde">−1 s</button>
            <button @click="skip(1)" title="+1 Sekunde">+1 s</button>
            <button @click="skip(10)" title="+10 Sekunden">10 s ⏩</button>

            <span class="time" style="font-variant-numeric: tabular-nums;margin-left:.5rem">
              {{ formatTime(resultTime) }} / {{ formatTime(resultDuration) }}
            </span>

            <span style="margin-left:auto;display:flex;align-items:center;gap:.4rem">
              <label class="muted" style="margin:0;font-size:.8rem">Speed</label>
              <select v-model.number="playbackRate" @change="applyPlaybackRate" style="padding:.25rem .4rem">
                <option :value="0.25">0.25×</option>
                <option :value="0.5">0.5×</option>
                <option :value="1">1×</option>
                <option :value="1.5">1.5×</option>
                <option :value="2">2×</option>
                <option :value="4">4×</option>
              </select>
            </span>

            <span style="display:flex;align-items:center;gap:.4rem">
              <button @click="toggleMute" :title="muted ? 'Ton an' : 'Stumm'">
                {{ muted || volume === 0 ? '🔇' : volume < 0.5 ? '🔉' : '🔊' }}
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                :value="muted ? 0 : volume"
                @input="onVolumeInput"
                style="width:90px"
                title="Lautstärke"
              />
            </span>

            <button @click="toggleFullscreen" title="Vollbild (f)">⛶ Großbild</button>
          </div>
        </div>

        <div style="margin-top:.75rem;display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
          <a :href="downloadUrl" :download="`fpv_pip_${jobId.slice(0,8)}.mp4`">
            <button class="primary">Download MP4</button>
          </a>
          <button class="ghost" @click="$emit('reset')">Neuen Render starten</button>
        </div>

        <div
          style="margin-top:1rem;padding:.75rem 1rem;background:var(--panel-2);border-radius:8px;border:1px solid rgba(255,255,255,.06);font-size:.88rem;line-height:1.5"
        >
          <strong style="color:var(--text)">Schneller Zugriff (lokal / Docker)</strong>
          <p class="muted" style="margin:.35rem 0 .5rem">
            Der Browser lädt die Datei noch einmal über das Netzwerk — bei großen MP4 kann das dauern.
            Auf dem Rechner liegt dieselbe Datei oft schon im Projektordner:
          </p>
          <code style="display:block;padding:.4rem .55rem;background:rgba(0,0,0,.25);border-radius:4px;word-break:break-all;font-size:.82rem">
            {{ hostRelativeOutputPath }}
          </code>
          <div style="margin-top:.5rem;display:flex;gap:.4rem;flex-wrap:wrap;align-items:center">
            <button type="button" class="ghost" style="font-size:.85rem" @click="copyOutputPath">
              Pfad in Zwischenablage
            </button>
            <span v-if="copyFeedback" class="muted" style="font-size:.82rem">{{ copyFeedback }}</span>
          </div>
        </div>
      </div>
      <div v-else-if="status.state === 'FAILURE'" style="margin-top:.5rem">
        <button class="ghost" @click="$emit('reset')">Zurück</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  jobId: { type: String, required: true },
})
defineEmits(['reset', 'done'])

const status = ref(null)
let timer = null

const stateLabel = computed(() => {
  const s = status.value?.state
  const stage = status.value?.stage
  switch (s) {
    case 'PENDING': return 'In Warteschlange (Worker noch belegt) …'
    case 'STARTED': return 'Job startet …'
    case 'PROGRESS':
      if (stage === 'preparing') return 'Hi-Res wird vorbereitet (Concat) …'
      if (stage === 'rendering') return 'Rendere PiP …'
      return `Arbeite … (${stage || ''})`
    case 'SUCCESS': return 'Fertig!'
    case 'FAILURE': return 'Fehlgeschlagen'
    default: return s || ''
  }
})

const downloadUrl = computed(() => api.downloadUrl(props.jobId))
const previewUrl = computed(() => api.jobPreviewUrl(props.jobId))
/** Relativ zum Projektroot — gleicher Bind-Mount wie im Docker-`data`-Volume. */
const hostRelativeOutputPath = computed(
  () => `data/outputs/${props.jobId}.mp4`,
)

const copyFeedback = ref('')

async function copyOutputPath() {
  copyFeedback.value = ''
  try {
    await navigator.clipboard.writeText(hostRelativeOutputPath.value)
    copyFeedback.value = 'Kopiert.'
    window.setTimeout(() => {
      copyFeedback.value = ''
    }, 2500)
  } catch {
    copyFeedback.value = 'Kopieren nicht möglich (Browser).'
    window.setTimeout(() => {
      copyFeedback.value = ''
    }, 3500)
  }
}

const resultVideoEl = ref(null)
const playerWrap = ref(null)
const resultDuration = ref(0)
const resultTime = ref(0)
const resultPlaying = ref(false)
const volume = ref(1)
const muted = ref(false)
const playbackRate = ref(1)

function onResultMeta() {
  const v = resultVideoEl.value
  if (!v) return
  if (isFinite(v.duration) && v.duration > 0) resultDuration.value = v.duration
}
function onResultTimeUpdate() {
  const v = resultVideoEl.value
  if (!v) return
  resultTime.value = v.currentTime
  resultPlaying.value = !v.paused
}
function onSeek(e) {
  const v = resultVideoEl.value
  if (!v) return
  v.currentTime = parseFloat(e.target.value)
  resultTime.value = v.currentTime
}
function skip(delta) {
  const v = resultVideoEl.value
  if (!v) return
  v.currentTime = Math.max(0, Math.min((resultDuration.value || v.duration || 0), v.currentTime + delta))
  resultTime.value = v.currentTime
}
function togglePlay() {
  const v = resultVideoEl.value
  if (!v) return
  if (v.paused) v.play().catch(() => {})
  else v.pause()
  resultPlaying.value = !v.paused
}
function onVolumeInput(e) {
  const val = parseFloat(e.target.value)
  const v = resultVideoEl.value
  volume.value = val
  if (v) {
    v.volume = val
    v.muted = val === 0
  }
  muted.value = val === 0
}
function onVolumeChange() {
  const v = resultVideoEl.value
  if (!v) return
  volume.value = v.volume
  muted.value = v.muted
}
function toggleMute() {
  const v = resultVideoEl.value
  if (!v) return
  v.muted = !v.muted
  muted.value = v.muted
}
function applyPlaybackRate() {
  const v = resultVideoEl.value
  if (v) v.playbackRate = playbackRate.value
}
function toggleFullscreen() {
  const target = playerWrap.value || resultVideoEl.value
  if (!target) return
  const doc = document
  if (doc.fullscreenElement) {
    doc.exitFullscreen?.()
  } else if (target.requestFullscreen) {
    target.requestFullscreen().catch(() => {})
  } else if (target.webkitRequestFullscreen) {
    target.webkitRequestFullscreen()
  } else if (resultVideoEl.value?.webkitEnterFullscreen) {
    resultVideoEl.value.webkitEnterFullscreen() // iOS Safari
  }
}

function onKeyDown(e) {
  if (status.value?.state !== 'SUCCESS') return
  // Don't hijack keys while typing in form fields.
  const tag = (e.target?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return
  switch (e.key) {
    case ' ': e.preventDefault(); togglePlay(); break
    case 'ArrowLeft': skip(e.shiftKey ? -10 : -1); break
    case 'ArrowRight': skip(e.shiftKey ? 10 : 1); break
    case 'f': case 'F': toggleFullscreen(); break
    case 'm': case 'M': toggleMute(); break
  }
}

function formatTime(s) {
  if (!isFinite(s) || s < 0) s = 0
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = (s % 60).toFixed(1)
  const mm = m.toString().padStart(h > 0 ? 2 : 1, '0')
  const ss = sec.padStart(4, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

async function poll() {
  try {
    status.value = await api.getJob(props.jobId)
    if (['SUCCESS', 'FAILURE'].includes(status.value.state)) {
      clearInterval(timer)
      timer = null
    }
  } catch (e) {
    // keep polling; transient errors will resolve
  }
}

onMounted(() => {
  poll()
  timer = setInterval(poll, 1000)
  window.addEventListener('keydown', onKeyDown)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('keydown', onKeyDown)
})
</script>
