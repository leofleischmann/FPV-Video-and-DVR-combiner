<template>
  <div>
    <div
      class="dropzone"
      :class="{ over: isOver }"
      @click="pickFiles"
      @dragenter.prevent="isOver = true"
      @dragover.prevent="isOver = true"
      @dragleave.prevent="isOver = false"
      @drop.prevent="onDrop"
    >
      <div><strong>{{ label }}</strong></div>
      <div class="hint">{{ hint }}</div>
      <div class="hint">Klicken oder Datei{{ multiple ? '(en)' : '' }} hierher ziehen</div>
    </div>
    <input
      ref="inputEl"
      type="file"
      :accept="accept"
      :multiple="multiple"
      style="display:none"
      @change="onPick"
    />
    <div v-if="active.length" style="margin-top:.5rem">
      <div v-for="u in active" :key="u.key" class="file-card">
        <div class="meta">
          <div class="name">{{ u.file.name }}</div>
          <div class="sub">{{ formatBytes(u.file.size) }} · {{ Math.round(u.progress * 100) }} %</div>
          <div class="progress"><div class="bar" :style="{ width: (u.progress * 100) + '%' }" /></div>
        </div>
        <div class="actions">
          <button class="ghost danger" @click="cancel(u)">Abbrechen</button>
        </div>
      </div>
    </div>
    <div v-if="error" class="error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { uploadFile } from '../api.js'

const props = defineProps({
  label: { type: String, required: true },
  hint: { type: String, default: '' },
  kind: { type: String, required: true }, // 'hires' | 'dvr' | 'audio'
  accept: { type: String, default: '' },
  multiple: { type: Boolean, default: false },
})
const emit = defineEmits(['uploaded'])

const inputEl = ref(null)
const isOver = ref(false)
const active = ref([])
const error = ref('')

function pickFiles() {
  inputEl.value?.click()
}

function onPick(e) {
  const files = Array.from(e.target.files || [])
  e.target.value = ''
  files.forEach(handleFile)
}

function onDrop(e) {
  isOver.value = false
  const files = Array.from(e.dataTransfer.files || [])
  files.forEach(handleFile)
}

let nextKey = 1
async function handleFile(file) {
  error.value = ''
  const ctrl = new AbortController()
  const entry = {
    key: nextKey++,
    file,
    progress: 0,
    abort: ctrl,
  }
  active.value.push(entry)
  try {
    const fileInfo = await uploadFile(file, props.kind, {
      signal: ctrl.signal,
      onProgress: (p) => { entry.progress = p },
    })
    emit('uploaded', fileInfo)
  } catch (e) {
    if (e.message !== 'aborted') {
      error.value = `Upload-Fehler bei ${file.name}: ${e.message}`
    }
  } finally {
    // NB: Vue 3 wraps pushed objects in a reactive Proxy on access, so
    // `x !== entry` is always true. Compare by the stable key instead.
    active.value = active.value.filter(x => x.key !== entry.key)
  }
}

function cancel(u) {
  u.abort.abort()
}

function formatBytes(n) {
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  if (n < 1024 ** 3) return (n / 1024 / 1024).toFixed(1) + ' MB'
  return (n / 1024 ** 3).toFixed(2) + ' GB'
}
</script>
