<template>
  <div class="app-shell">
    <header class="header">
      <div class="brand">FPV <span class="accent">Picture</span> Merger</div>
      <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
        <button
          class="ghost danger"
          :disabled="!hasAnyState"
          @click="resetAll"
          title="Remove all uploads and settings"
        >
          Reset
        </button>
      </div>
    </header>

    <div class="steps">
      <div class="step" :class="stepClass(1)">1 · Files</div>
      <div class="step" :class="stepClass(2)">2 · Sync</div>
      <div class="step" :class="stepClass(3)">3 · Layout</div>
      <div class="step" :class="stepClass(4)">4 · Export</div>
    </div>

    <!-- STEP 1: UPLOAD — only drone + goggles until both are set -->
    <section v-if="!jobId">
      <div class="upload-phase">
        <div class="panel upload-phase__card">
          <h2>Drone video</h2>
          <FileUploader
            label="Drop drone videos here"
            hint="Several files if your recording was split"
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

        <div class="panel upload-phase__card">
          <h2>Goggles recording</h2>
          <FileUploader
            v-if="!dvrFile"
            label="Drop goggles video here"
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
                <span v-if="!dvrFile.browser_playable && !dvrFile.preview_ready" style="color:var(--accent-2)">
                  · Loading preview…
                </span>
              </div>
            </div>
            <div class="actions">
              <button class="ghost danger" @click="removeDvr">×</button>
            </div>
          </div>
        </div>
      </div>

      <p v-if="!bothVideosReady" class="muted upload-phase__hint">
        Add both videos here first. Then you can sync clips, choose layout and preview, and optionally add music.
      </p>

      <div v-if="bothVideosReady" class="panel">
        <h2>Music (optional)</h2>
        <FileUploader
          v-if="!audioFile"
          label="Drop MP3 here"
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
      <div v-if="bothVideosReady" class="panel">
        <h2 style="display:flex;align-items:center;gap:.5rem;margin-bottom:.85rem">
          <span style="font-size:1.35rem;line-height:1" aria-hidden="true">⇄</span>
          <span>Sync</span>
        </h2>

        <div class="row sync-columns">
          <div class="col trim-col trim-col--drone">
            <div class="trim-col__head">
              <span class="trim-col__stripe trim-col__stripe--drone" aria-hidden="true" />
              <h3 style="margin:0;text-transform:none;letter-spacing:0;font-size:1rem;color:var(--text)">Drone</h3>
              <span v-if="hiresFiles.length > 1" class="trim-col__badge">{{ hiresFiles.length }}</span>
            </div>
            <VideoTrimmer
              :key="hiresPreviewKey"
              :src="hiresFullPreviewSrc"
              v-model="hiresTrim"
              :duration="hiresTrimTimelineDuration"
              :playback-max="hiresFiles.length > 1 ? hiresDuration : 0"
              @duration="d => hiresDuration = d"
            />
          </div>
          <div class="col trim-col trim-col--goggles">
            <div class="trim-col__head">
              <span class="trim-col__stripe trim-col__stripe--goggles" aria-hidden="true" />
              <h3 style="margin:0;text-transform:none;letter-spacing:0;font-size:1rem;color:var(--text)">Goggles</h3>
            </div>
            <VideoTrimmer
              :src="dvrPreviewSrc"
              v-model="dvrTrim"
              :duration="dvrDuration"
              @duration="d => dvrDuration = d"
            />
          </div>
        </div>

        <div class="sync-strip">
          <div class="sync-strip__cell">
            <span class="sync-strip__glyph" aria-hidden="true">📹</span>
            <div class="sync-strip__nums">
              {{ formatTimeFull(hiresTrim.start) }}→{{ formatTimeFull(effectiveHiresEnd) }}
              <span class="muted" style="display:block;font-size:.78rem;margin-top:.15rem">{{ formatTimeFull(effectiveHiresEnd - hiresTrim.start) }}</span>
            </div>
          </div>
          <div class="sync-strip__cell">
            <span class="sync-strip__glyph" aria-hidden="true">🥽</span>
            <div class="sync-strip__nums">
              {{ formatTimeFull(dvrTrim.start) }}→{{ formatTimeFull(effectiveDvrEnd) }}
              <span class="muted" style="display:block;font-size:.78rem;margin-top:.15rem">{{ formatTimeFull(effectiveDvrEnd - dvrTrim.start) }}</span>
            </div>
          </div>
          <div class="sync-strip__cell">
            <span class="sync-strip__glyph" aria-hidden="true">⇄</span>
            <div class="sync-strip__nums">
              {{ syncOffset >= 0 ? '+' : '' }}{{ syncOffset.toFixed(2) }}s
            </div>
          </div>
          <div class="sync-strip__cell">
            <span class="sync-strip__glyph" aria-hidden="true">⏱</span>
            <div class="sync-strip__nums sync-strip__nums--accent">
              {{ formatTimeFull(outputDuration) }}
            </div>
          </div>
        </div>

        <div v-if="audioFile" class="row" style="margin-top:1rem">
          <div class="col trim-col trim-col--audio">
            <div class="trim-col__head">
              <span class="trim-col__stripe trim-col__stripe--audio" aria-hidden="true" />
              <h3 style="margin:0;text-transform:none;letter-spacing:0;font-size:1rem;color:var(--text)">Audio</h3>
            </div>
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
      <div v-if="bothVideosReady" class="panel">
        <h2 style="display:flex;align-items:center;gap:.5rem">
          <span style="font-size:1.25rem;line-height:1" aria-hidden="true">▣</span>
          <span>Layout</span>
        </h2>

        <div class="row" style="margin-bottom: 1rem">
          <div class="col" style="max-width:200px">
            <label>Output size</label>
            <select v-model="resolutionPreset" @change="applyPreset">
              <option value="auto">Same as drone</option>
              <option value="2160p">3840×2160 (4K)</option>
              <option value="1440p">2560×1440 (1440p)</option>
              <option value="1080p">1920×1080 (1080p)</option>
              <option value="720p">1280×720 (720p)</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <div class="col" style="max-width:140px">
            <label>Width</label>
            <input type="number" v-model.number="outputWidth" min="2" step="2" />
          </div>
          <div class="col" style="max-width:140px">
            <label>Height</label>
            <input type="number" v-model.number="outputHeight" min="2" step="2" />
          </div>
          <div class="col" style="max-width:200px">
            <label>File format</label>
            <select v-model="codec">
              <option value="h264">Standard (recommended)</option>
              <option value="h265">Smaller file</option>
            </select>
          </div>
        </div>

        <PipEditor
          :hires-src="hiresPreviewSrc"
          :dvr-src="dvrPreviewSrc"
          :output-width="outputWidth || 1920"
          :output-height="outputHeight || 1080"
          :hires-trim="hiresTrim"
          :dvr-trim="dvrTrim"
          :hires-duration="hiresDuration"
          :dvr-duration="dvrDuration"
          :privacy-masks="dvrPrivacyMasks"
          v-model="pip"
        />

        <div class="panel" style="margin-top:1rem;background:var(--panel-2);border:1px solid var(--border)">
          <h3 style="margin-top:0;font-size:1rem">Hide parts of goggles image (optional)</h3>
          <button type="button" class="ghost" :disabled="dvrPrivacyMasks.length >= 16" @click="addPrivacyMask">
            Add cover box
          </button>
          <div
            v-for="(pm, pidx) in dvrPrivacyMasks"
            :key="'priv-' + pidx"
            style="margin-top:.75rem;padding:.65rem .85rem;border:1px solid var(--border);border-radius:8px;background:var(--panel)"
          >
            <div style="display:flex;flex-wrap:wrap;gap:.85rem;align-items:flex-end;margin-bottom:.5rem">
              <div>
                <label style="font-size:.78rem">Fill</label><br>
                <input v-model="pm.color" type="color" style="height:2rem;width:3rem;padding:0;border:none;background:transparent;cursor:pointer">
              </div>
              <button type="button" class="ghost danger" style="margin-left:auto;font-size:.82rem" @click="removePrivacyMask(pidx)">Remove</button>
            </div>
            <div class="row" style="gap:.5rem">
              <div class="col" style="min-width:140px">
                <label class="muted" style="font-size:.72rem">Left {{ (pm.x * 100).toFixed(0) }}%</label>
                <input type="range" min="0" max="100" step="0.5" :value="pm.x * 100" @input="onMaskX(pidx, +$event.target.value / 100)">
              </div>
              <div class="col" style="min-width:140px">
                <label class="muted" style="font-size:.72rem">Top {{ (pm.y * 100).toFixed(0) }}%</label>
                <input type="range" min="0" max="100" step="0.5" :value="pm.y * 100" @input="onMaskY(pidx, +$event.target.value / 100)">
              </div>
              <div class="col" style="min-width:140px">
                <label class="muted" style="font-size:.72rem">Width {{ (pm.width * 100).toFixed(0) }}%</label>
                <input type="range" min="1" max="100" step="0.5" :value="pm.width * 100" @input="onMaskWidth(pidx, +$event.target.value / 100)">
              </div>
              <div class="col" style="min-width:140px">
                <label class="muted" style="font-size:.72rem">Height {{ (pm.height * 100).toFixed(0) }}%</label>
                <input type="range" min="1" max="100" step="0.5" :value="pm.height * 100" @input="onMaskHeight(pidx, +$event.target.value / 100)">
              </div>
            </div>
          </div>
        </div>

        <div style="margin-top:1.25rem;display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
          <button class="primary" :disabled="!canRender" @click="startRender">
            Start export
          </button>
          <span v-if="renderError" class="error">{{ renderError }}</span>
        </div>
      </div>
    </section>

    <!-- STEP 4: PROGRESS -->
    <section v-else>
      <div class="panel">
        <h2>Creating your video</h2>
        <JobProgress :job-id="jobId" @reset="resetJob" />
      </div>
    </section>

  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import FileUploader from './components/FileUploader.vue'
import HiResList from './components/HiResList.vue'
import VideoTrimmer from './components/VideoTrimmer.vue'
import PipEditor from './components/PipEditor.vue'
import JobProgress from './components/JobProgress.vue'
import { api } from './api.js'

const STORAGE_KEY = 'fpv-merger-session-v1'

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

/** { x, y, width, height } as 0..1 fractions of goggles frame; color #RRGGBB */
const dvrPrivacyMasks = ref([])

const resolutionPreset = ref('auto')
const outputWidth = ref(1920)
const outputHeight = ref(1080)
const codec = ref('h264')

const jobId = ref('')
const renderError = ref('')

const hasAnyState = computed(() =>
  hiresFiles.value.length > 0 || !!dvrFile.value || !!audioFile.value || !!jobId.value
)

/** Drone + goggles present — unlocks sync, layout preview, and optional music. */
const bothVideosReady = computed(
  () => hiresFiles.value.length > 0 && !!dvrFile.value,
)

/** First Hi-Res chunk (list order) for instant Trim-preview; export still uses all chunks. */
const hiresFullPreviewSrc = computed(() => {
  const files = hiresFiles.value
  if (!files.length) return ''
  return bestSrc(files[0])
})

/** Remount when order/first file/src changes. */
const hiresPreviewKey = computed(
  () => `${hiresFiles.value.map((f) => f.file_id).join(',')}|${hiresFullPreviewSrc.value}`,
)

/**
 * Trim slider timeline = one merged Hi-Res (sum of ffprobe durations from API).
 * Playback uses only the first chunk (`hiresDuration` + playbackMax on VideoTrimmer).
 */
const hiresTrimTimelineDuration = computed(() => {
  const files = hiresFiles.value
  if (!files.length) return 0
  if (files.length === 1) {
    return hiresDuration.value || files[0].duration || 0
  }
  let s = 0
  for (const f of files) s += f.duration || 0
  return s > 0 ? s : hiresDuration.value || 0
})

const effectiveHiresEnd = computed(
  () => hiresTrim.value.end ?? hiresTrimTimelineDuration.value ?? 0,
)
const effectiveDvrEnd = computed(
  () => dvrTrim.value.end ?? dvrDuration.value ?? 0,
)
const syncOffset = computed(() => dvrTrim.value.start - hiresTrim.value.start)
/** Matches export: length follows the drone (hi-res) trim — see render_pip in backend. */
const outputDuration = computed(() => {
  const hi = effectiveHiresEnd.value - hiresTrim.value.start
  return Math.max(0, hi)
})

function formatTimeFull(s) {
  if (!Number.isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(3)
  return `${m}:${sec.padStart(6, '0')}`
}

function bestSrc(f) {
  if (!f) return ''
  if (f.browser_playable) return api.rawUrl(f.file_id)  // codec the browser can decode
  if (f.preview_ready) return api.previewUrl(f.file_id) // worker-transcoded preview
  return ''                                             // still being generated
}
const hiresPreviewSrc = computed(() => bestSrc(hiresFiles.value[0]))
const dvrPreviewSrc = computed(() => bestSrc(dvrFile.value))
const audioRawSrc = computed(() => {
  return audioFile.value ? api.rawUrl(audioFile.value.file_id) : ''
})

const canRender = computed(() => hiresFiles.value.length > 0 && !!dvrFile.value)

/** Sort by filename (numeric-aware: part2 before part10). */
function sortHiresFilesByFilename(files) {
  return [...files].sort((a, b) =>
    (a.filename || '').localeCompare(b.filename || '', undefined, { numeric: true, sensitivity: 'base' }),
  )
}

function addHires(f) {
  hiresFiles.value.push(f)
  hiresFiles.value = sortHiresFilesByFilename(hiresFiles.value)
  pollPreview(f)
  // First chunk after sort sets resolution when only one file.
  const first = hiresFiles.value[0]
  if (hiresFiles.value.length === 1 && first?.width && first?.height) {
    outputWidth.value = first.width
    outputHeight.value = first.height
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
// Skipped entirely for files the browser can already play (H.264 source).
async function pollPreview(f) {
  if (f.browser_playable || f.preview_ready) return
  // No upper iteration cap — preview generation can legitimately take a while
  // for HEVC sources on a busy worker.  We only stop on success or unmount.
  while (true) {
    await new Promise(r => setTimeout(r, 2000))
    try {
      const info = await api.getFile(f.file_id)
      if (info.preview_ready || info.browser_playable) {
        Object.assign(f, info)
        if (hiresFiles.value.includes(f)) hiresFiles.value = [...hiresFiles.value]
        if (dvrFile.value && dvrFile.value.file_id === f.file_id) {
          dvrFile.value = { ...dvrFile.value, ...info }
        }
        return
      }
    } catch { /* keep polling */ }
  }
}

watch(
  () => hiresFiles.value[0]?.file_id ?? '',
  (id) => {
    if (!id) return
    const f = hiresFiles.value[0]
    if (f) pollPreview(f)
  },
)

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
      dvr_privacy_masks: dvrPrivacyMasks.value.map((m) => ({
        x: m.x,
        y: m.y,
        width: m.width,
        height: m.height,
        color: m.color,
      })),
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
  if (jobId.value) {
    return {
      active: n === 4,
      done: n < 4,
      pending: false,
    }
  }
  if (!bothVideosReady.value) {
    return {
      active: n === 1,
      done: false,
      pending: n > 1,
    }
  }
  return {
    active: n === 2,
    done: n === 1,
    pending: n > 2,
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

function clamp01(v) {
  return Math.max(0, Math.min(1, v))
}

function addPrivacyMask() {
  if (dvrPrivacyMasks.value.length >= 16) return
  dvrPrivacyMasks.value.push({
    x: 0.05,
    y: 0.72,
    width: 0.9,
    height: 0.14,
    color: '#000000',
  })
}

function removePrivacyMask(i) {
  dvrPrivacyMasks.value.splice(i, 1)
}

function onMaskX(i, x) {
  const pm = dvrPrivacyMasks.value[i]
  if (!pm) return
  pm.x = clamp01(x)
  if (pm.x + pm.width > 1) pm.width = Math.max(0.001, 1 - pm.x)
}

function onMaskY(i, y) {
  const pm = dvrPrivacyMasks.value[i]
  if (!pm) return
  pm.y = clamp01(y)
  if (pm.y + pm.height > 1) pm.height = Math.max(0.001, 1 - pm.y)
}

function onMaskWidth(i, w) {
  const pm = dvrPrivacyMasks.value[i]
  if (!pm) return
  const nw = clamp01(w)
  pm.width = Math.max(0.001, Math.min(nw, 1 - pm.x))
}

function onMaskHeight(i, h) {
  const pm = dvrPrivacyMasks.value[i]
  if (!pm) return
  const nh = clamp01(h)
  pm.height = Math.max(0.001, Math.min(nh, 1 - pm.y))
}

watch(hiresFiles, () => {
  if (resolutionPreset.value === 'auto') applyPreset()
}, { deep: true })

// ---------------------------------------------------------------------------
// Session persistence: keep uploaded files + UI settings across reloads.
// On mount we re-fetch each FileInfo from the backend so we don't reference
// files that the user (or a Reset) deleted on the server side.
// ---------------------------------------------------------------------------
function snapshot() {
  return {
    hires: hiresFiles.value.map(f => f.file_id),
    dvr: dvrFile.value ? dvrFile.value.file_id : null,
    audio: audioFile.value ? audioFile.value.file_id : null,
    hiresTrim: hiresTrim.value,
    dvrTrim: dvrTrim.value,
    audioTrim: audioTrim.value,
    pip: pip.value,
    resolutionPreset: resolutionPreset.value,
    outputWidth: outputWidth.value,
    outputHeight: outputHeight.value,
    codec: codec.value,
    jobId: jobId.value || null,
    dvrPrivacyMasks: dvrPrivacyMasks.value,
  }
}

let restoring = true
function persist() {
  if (restoring) return
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot()))
  } catch { /* quota exceeded etc — non-fatal */ }
}

watch(
  [
    hiresFiles, dvrFile, audioFile,
    hiresTrim, dvrTrim, audioTrim,
    pip,
    dvrPrivacyMasks,
    resolutionPreset, outputWidth, outputHeight, codec,
    jobId,
  ],
  persist,
  { deep: true },
)

async function restoreSession() {
  let saved
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
  } catch { saved = null }
  if (!saved) { restoring = false; return }

  // Verify each file still exists on the backend; drop dead references.
  const verify = async (fid) => {
    if (!fid) return null
    try { return await api.getFile(fid) } catch { return null }
  }

  const hiresInfos = (await Promise.all((saved.hires || []).map(verify))).filter(Boolean)
  const dvrInfo = await verify(saved.dvr)
  const audioInfo = await verify(saved.audio)

  hiresFiles.value = sortHiresFilesByFilename(hiresInfos)
  dvrFile.value = dvrInfo
  audioFile.value = audioInfo

  if (saved.hiresTrim) hiresTrim.value = saved.hiresTrim
  if (saved.dvrTrim) dvrTrim.value = saved.dvrTrim
  if (saved.audioTrim) audioTrim.value = saved.audioTrim
  if (saved.pip) pip.value = saved.pip
  if (saved.resolutionPreset) resolutionPreset.value = saved.resolutionPreset
  if (saved.outputWidth) outputWidth.value = saved.outputWidth
  if (saved.outputHeight) outputHeight.value = saved.outputHeight
  if (saved.codec) codec.value = saved.codec
  if (Array.isArray(saved.dvrPrivacyMasks)) dvrPrivacyMasks.value = saved.dvrPrivacyMasks

  // Re-attach to an in-flight render job if it's still around.
  if (saved.jobId) {
    try {
      const status = await api.getJob(saved.jobId)
      // Only resume PENDING/STARTED/PROGRESS — terminal jobs drop back to upload.
      if (['PENDING', 'STARTED', 'PROGRESS'].includes(status.state)) {
        jobId.value = saved.jobId
      }
    } catch { /* job gone — ignore */ }
  }

  // Resume preview-polling for files that aren't yet browser-playable.
  hiresFiles.value.forEach(pollPreview)
  if (dvrFile.value) pollPreview(dvrFile.value)

  restoring = false
}

async function resetAll() {
  if (!confirm(
    'Reset everything? This deletes uploads, files, previews, rendered outputs, '
    + 'and temp work on the server, and clears browser storage. Continue?',
  )) {
    return
  }
  try {
    await api.resetWorkspace()
  } catch (e) {
    renderError.value = e.message || String(e)
    alert(`Server reset failed: ${renderError.value}`)
    return
  }

  hiresFiles.value = []
  dvrFile.value = null
  audioFile.value = null
  hiresTrim.value = { start: 0, end: null }
  dvrTrim.value = { start: 0, end: null }
  audioTrim.value = { start: 0, end: null }
  hiresDuration.value = 0
  dvrDuration.value = 0
  audioDuration.value = 0
  pip.value = { x: 0.02, y: 0.02, width: 0.30 }
  resolutionPreset.value = 'auto'
  outputWidth.value = 1920
  outputHeight.value = 1080
  codec.value = 'h264'
  dvrPrivacyMasks.value = []
  jobId.value = ''
  renderError.value = ''

  try { localStorage.removeItem(STORAGE_KEY) } catch { /* ignore */ }
}

onMounted(() => {
  restoreSession()
})
</script>
