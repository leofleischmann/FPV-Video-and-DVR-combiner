<template>
  <div class="hires-list">
    <div v-for="(f, i) in files" :key="f.file_id" class="file-card">
      <div class="meta">
        <div class="name">{{ i + 1 }}. {{ f.filename }}</div>
        <div class="sub">
          {{ formatBytes(f.size) }}
          <span v-if="f.width">· {{ f.width }}×{{ f.height }}</span>
          <span v-if="f.duration">· {{ formatDuration(f.duration) }}</span>
          <span v-if="f.video_codec">· {{ f.video_codec }}</span>
          <span v-if="!f.browser_playable && !f.preview_ready" style="color:var(--accent-2)">
            · Building preview
          </span>
        </div>
      </div>
      <div class="order-controls">
        <button :disabled="i === 0" @click="move(i, -1)">↑</button>
        <button :disabled="i === files.length - 1" @click="move(i, 1)">↓</button>
        <button class="ghost danger" @click="$emit('remove', f)">×</button>
      </div>
    </div>
    <div v-if="!files.length" class="muted" style="margin-top:.5rem">
      No hi-res files yet.
    </div>
    <div v-if="files.length > 1" class="muted" style="margin-top:.5rem">
      Order is the playback order when clips are stitched.
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  files: { type: Array, required: true },
})
const emit = defineEmits(['reorder', 'remove'])

function move(i, dir) {
  const j = i + dir
  if (j < 0 || j >= props.files.length) return
  const next = [...props.files]
  const [it] = next.splice(i, 1)
  next.splice(j, 0, it)
  emit('reorder', next)
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
</script>
