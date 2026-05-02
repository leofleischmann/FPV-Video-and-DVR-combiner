<template>
  <div class="app-shell">
    <header class="header">
      <div class="brand">FPV <span class="accent">PiP</span> Merger</div>
      <div class="muted">Hi-Res + DVR &rarr; Picture-in-Picture &rarr; MP4</div>
    </header>

    <div class="steps">
      <div class="step" :class="stepClass(1)">1 · Upload</div>
      <div class="step" :class="stepClass(2)">2 · Trim &amp; Sync</div>
      <div class="step" :class="stepClass(3)">3 · PiP &amp; Settings</div>
      <div class="step" :class="stepClass(4)">4 · Render</div>
    </div>

    <!-- STEP 1: UPLOAD -->
    <section v-if="!jobId">
      <div class="panel">
        <h2>1 · Hi-Res Drohnen-Aufnahme (.mp4)</h2>
        <p class="muted">
          Mehrere Chunks (max. 4 GB pro Datei) sind erlaubt — sie werden serverseitig
          per FFmpeg Concat Demuxer (verlustfrei wenn möglich) zusammengefügt.
        </p>
        <FileUploader
          label="Hi-Res MP4 hier ablegen"
          hint="Mehrere Dateien für gesplittete Aufnahmen"
          kind="hires"
          accept="video/mp4"
          :multiple="true"
          @uploaded="addHires"
        />
        <HiResList
          :files="hiresFiles"
          @reorder="hiresFiles = $event"
          @remove="removeHires"
        />
      </div>

      <div class="panel">
        <h2>2 · DVR / Brillen-Aufnahme (.mov)</h2>
        <FileUploader
          v-if="!dvrFile"
          label="DVR MOV hier ablegen"
          kind="dvr"
          accept="video/quicktime,.mov,video/*"
          @uploaded="setDvr"
        />
        <div v-else class="file-card">
          <div class="meta">
            <div class="name">{{ dvrFile.filename }}</div>
            <div class="sub">
              {{ formatBytes(dvrFile.size) }}
              <span v-if="dvrFile.width">· {{ dvrFile.width }}×{{ dvrFile.height }}</span>
              <span v-if="dvrFile.duration">· {{ formatDuration(dvrFile.duration) }}</span>
            </div>
          </div>
          <div class="actions">
            <button class="ghost danger" @click="removeDvr">×</button>
          </div>
        </div>
      </div>

      <div class="panel">
        <h2>3 · Audio (optional, .mp3)</h2>
        <p class="muted">
          Wird eine MP3 hochgeladen, werden beide Original-Tonspuren der Videos verworfen
          und ausschließlich die geschnittene MP3 gemuxt. Ohne MP3 bleibt der Hi-Res-Ton erhalten.
        </p>
        <FileUploader
          v-if="!audioFile"
          label="MP3 hier ablegen (optional)"
          kind="audio"
          accept="audio/mpeg,.mp3"
          @uploaded="setAudio"
        />
        <div v-else class="file-card">
          <div class="meta">
            <div class="name">{{ audioFile.filename }}</div>
            <div class="sub">
              {{ formatBytes(audioFile.size) }}
              <span v-if="audioFile.duration">· {{ formatDuration(audioFile.duration) }}</span>
            </div>
          </div>
          <div class="actions">
            <button class="ghost danger" @click="audioFile = null">×</button>
          </div>
        </div>
      </div>

      <!-- STEP 2: TRIM -->
      <div v-if="hiresFiles.length && dvrFile" class="panel">
        <h2>Trim &amp; Synchronisation</h2>
        <p class="muted">
          Hi-Res definiert die Render-Zeitachse. DVR-Trim wird unabhängig zugeschnitten und im Overlay
          ab Zeitpunkt 0 abgespielt — passe die DVR-Startzeit so an, dass sie mit dem Hi-Res-Frame übereinstimmt.
        </p>

        <div class="row">
          <div class="col">
            <h3>Hi-Res {{ hiresFiles.length > 1 ? '(erster Chunk als Vorschau)' : '' }}</h3>
            <VideoTrimmer
              :src="hiresPreviewSrc"
              v-model="hiresTrim"
              :duration="hiresDuration"
              @duration="d => hiresDuration = d"
            />
          </div>
          <div class="col">
            <h3>DVR</h3>
            <VideoTrimmer
              :src="dvrPreviewSrc"
              v-model="dvrTrim"
              :duration="dvrDuration"
              @duration="d => dvrDuration = d"
            />
          </div>
        </div>

        <div v-if="audioFile" class="row" style="margin-top:1rem">
          <div class="col">
            <h3>MP3 Trim</h3>
            <div>
              <audio :src="audioRawSrc" controls preload="metadata" style="width:100%"
                @loadedmetadata="onAudioMeta" />
              <VideoTrimmer
                :src="''"
                v-model="audioTrim"
                :duration="audioDuration"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- STEP 3: PIP + RENDER SETTINGS -->
      <div v-if="hiresFiles.length && dvrFile" class="panel">
        <h2>Layout &amp; Render-Einstellungen</h2>

        <div class="row" style="margin-bottom: 1rem">
          <div class="col" style="max-width:200px">
            <label>Auflösung Preset</label>
            <select v-model="resolutionPreset" @change="applyPreset">
              <option value="auto">Auto (Hi-Res Original)</option>
              <option value="2160p">3840×2160 (4K)</option>
              <option value="1440p">2560×1440 (1440p)</option>
              <option value="1080p">1920×1080 (1080p)</option>
              <option value="720p">1280×720 (720p)</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <div class="col" style="max-width:140px">
            <label>Breite</label>
            <input type="number" v-model.number="outputWidth" min="2" step="2" />
          </div>
          <div class="col" style="max-width:140px">
            <label>Höhe</label>
            <input type="number" v-model.number="outputHeight" min="2" step="2" />
          </div>
          <div class="col" style="max-width:160px">
            <label>Codec</label>
            <select v-model="codec">
              <option value="h264">H.264 (libx264)</option>
              <option value="h265">H.265 (libx265)</option>
            </select>
          </div>
        </div>

        <PipEditor
          :hires-src="hiresPreviewSrc"
          :dvr-src="dvrPreviewSrc"
          :output-width="outputWidth || 1920"
          :output-height="outputHeight || 1080"
          v-model="pip"
        />

        <div style="margin-top:1.25rem;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
          <button class="primary" :disabled="!canRender" @click="startRender">
            Rendern starten
          </button>
          <span v-if="!canRender" class="muted">
            Mindestens ein Hi-Res-Chunk und das DVR-Video sind nötig.
          </span>
          <span v-if="renderError" class="error">{{ renderError }}</span>
        </div>
      </div>
    </section>

    <!-- STEP 4: PROGRESS -->
    <section v-else>
      <div class="panel">
        <h2>Rendering</h2>
        <JobProgress :job-id="jobId" @reset="resetJob" />
      </div>
    </section>

    <footer class="muted" style="margin-top:2rem;text-align:center">
      Backend: FastAPI + Celery + FFmpeg · Frontend: Vue 3 · Container: Docker Compose
    </footer>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import FileUploader from './components/FileUploader.vue'
import HiResList from './components/HiResList.vue'
import VideoTrimmer from './components/VideoTrimmer.vue'
import PipEditor from './components/PipEditor.vue'
import JobProgress from './components/JobProgress.vue'
import { api } from './api.js'

const hiresFiles = ref([])  // FileInfo[]
const dvrFile = ref(null)
const audioFile = ref(null)

const hiresTrim = ref({ start: 0, end: null })
const dvrTrim = ref({ start: 0, end: null })
const audioTrim = ref({ start: 0, end: null })

const hiresDuration = ref(0)
const dvrDuration = ref(0)
const audioDuration = ref(0)

const pip = ref({ x: 0.02, y: 0.02, width: 0.30 })

const resolutionPreset = ref('auto')
const outputWidth = ref(1920)
const outputHeight = ref(1080)
const codec = ref('h264')

const jobId = ref('')
const renderError = ref('')

const hiresPreviewSrc = computed(() => {
  const f = hiresFiles.value[0]
  if (!f) return ''
  return f.preview_ready ? api.previewUrl(f.file_id) : api.rawUrl(f.file_id)
})
const dvrPreviewSrc = computed(() => {
  const f = dvrFile.value
  if (!f) return ''
  return f.preview_ready ? api.previewUrl(f.file_id) : api.rawUrl(f.file_id)
})
const audioRawSrc = computed(() => {
  return audioFile.value ? api.rawUrl(audioFile.value.file_id) : ''
})

const canRender = computed(() => hiresFiles.value.length > 0 && !!dvrFile.value)

function addHires(f) {
  hiresFiles.value.push(f)
  pollPreview(f)
  // First chunk seeds default output resolution.
  if (hiresFiles.value.length === 1 && f.width && f.height) {
    outputWidth.value = f.width
    outputHeight.value = f.height
    resolutionPreset.value = 'auto'
  }
}
function removeHires(f) {
  hiresFiles.value = hiresFiles.value.filter(x => x.file_id !== f.file_id)
  api.deleteFile(f.file_id).catch(() => {})
}
function setDvr(f) {
  dvrFile.value = f
  pollPreview(f)
}
function removeDvr() {
  if (dvrFile.value) api.deleteFile(dvrFile.value.file_id).catch(() => {})
  dvrFile.value = null
}
function setAudio(f) {
  audioFile.value = f
}

// Poll until the worker has produced a browser-friendly preview MP4.
async function pollPreview(f) {
  if (f.preview_ready) return
  for (let i = 0; i < 120; i++) {
    await new Promise(r => setTimeout(r, 1500))
    try {
      const info = await api.getFile(f.file_id)
      if (info.preview_ready) {
        f.preview_ready = true
        // Touch the array to trigger reactivity for hires preview.
        if (hiresFiles.value.includes(f)) hiresFiles.value = [...hiresFiles.value]
        if (dvrFile.value && dvrFile.value.file_id === f.file_id) dvrFile.value = { ...info }
        return
      }
    } catch { /* keep polling */ }
  }
}

function applyPreset() {
  const presets = {
    '2160p': [3840, 2160],
    '1440p': [2560, 1440],
    '1080p': [1920, 1080],
    '720p': [1280, 720],
  }
  if (resolutionPreset.value === 'auto') {
    const f = hiresFiles.value[0]
    if (f && f.width && f.height) {
      outputWidth.value = f.width
      outputHeight.value = f.height
    }
  } else if (presets[resolutionPreset.value]) {
    [outputWidth.value, outputHeight.value] = presets[resolutionPreset.value]
  }
}

function onAudioMeta(e) {
  if (e?.target?.duration && isFinite(e.target.duration)) {
    audioDuration.value = e.target.duration
  }
}

async function startRender() {
  renderError.value = ''
  try {
    const res = await api.createJob({
      hires_file_ids: hiresFiles.value.map(f => f.file_id),
      dvr_file_id: dvrFile.value.file_id,
      audio_file_id: audioFile.value ? audioFile.value.file_id : null,
      hires_trim: hiresTrim.value,
      dvr_trim: dvrTrim.value,
      audio_trim: audioTrim.value,
      pip: pip.value,
      output_width: outputWidth.value,
      output_height: outputHeight.value,
      codec: codec.value,
    })
    jobId.value = res.job_id
  } catch (e) {
    renderError.value = e.message
  }
}

function resetJob() {
  jobId.value = ''
}

function stepClass(n) {
  let active = 1
  if (jobId.value) active = 4
  else if (hiresFiles.value.length && dvrFile.value) active = 3
  else if (hiresFiles.value.length || dvrFile.value) active = 2
  return {
    active: n === active,
    done: n < active,
  }
}

function formatBytes(n) {
  if (n < 1024 ** 2) return (n / 1024).toFixed(1) + ' KB'
  if (n < 1024 ** 3) return (n / 1024 ** 2).toFixed(1) + ' MB'
  return (n / 1024 ** 3).toFixed(2) + ' GB'
}
function formatDuration(s) {
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

watch(hiresFiles, () => {
  if (resolutionPreset.value === 'auto') applyPreset()
}, { deep: true })
</script>
