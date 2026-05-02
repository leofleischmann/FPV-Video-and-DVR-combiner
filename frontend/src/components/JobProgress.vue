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
        <video
          :src="previewUrl"
          controls
          preload="metadata"
          style="width:100%;max-height:540px;background:#000;border-radius:8px"
        />
        <div style="margin-top:.75rem;display:flex;gap:.5rem;flex-wrap:wrap">
          <a :href="downloadUrl" :download="`fpv_pip_${jobId.slice(0,8)}.mp4`">
            <button class="primary">Download MP4</button>
          </a>
          <button class="ghost" @click="$emit('reset')">Neuen Render starten</button>
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
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>
