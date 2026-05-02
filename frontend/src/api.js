// Lightweight HTTP client + chunked uploader.
//
// Uploads are split into ~8 MiB chunks and PUT one-at-a-time.  On a network
// error the uploader queries the server for `received` and resumes from there,
// so videos > 4 GB stop being a problem (no single browser request is >8 MiB).

const CHUNK_SIZE = 8 * 1024 * 1024
const MAX_RETRIES_PER_CHUNK = 5

async function jsonFetch(url, opts = {}) {
  const r = await fetch(url, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      ...(opts.headers || {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!r.ok) {
    let detail = ''
    try { detail = (await r.json()).detail } catch { /* noop */ }
    throw new Error(detail || `HTTP ${r.status}`)
  }
  return r.json()
}

export const api = {
  health: () => jsonFetch('/api/health'),

  encodingInfo() {
    return jsonFetch('/api/encoding')
  },

  resetWorkspace() {
    return jsonFetch('/api/reset-workspace', { method: 'POST' })
  },

  initUpload(filename, size, kind) {
    return jsonFetch('/api/uploads/init', {
      method: 'POST',
      body: { filename, size, kind },
    })
  },

  getUpload(uploadId) {
    return jsonFetch(`/api/uploads/${uploadId}`)
  },

  completeUpload(uploadId) {
    return jsonFetch(`/api/uploads/${uploadId}/complete`, { method: 'POST' })
  },

  cancelUpload(uploadId) {
    return fetch(`/api/uploads/${uploadId}`, { method: 'DELETE' })
  },

  getFile(fileId) {
    return jsonFetch(`/api/files/${fileId}`)
  },

  deleteFile(fileId) {
    return fetch(`/api/files/${fileId}`, { method: 'DELETE' })
  },

  previewUrl(fileId) {
    return `/api/files/${fileId}/preview`
  },

  rawUrl(fileId) {
    return `/api/files/${fileId}/raw`
  },

  createJob(payload) {
    return jsonFetch('/api/jobs', { method: 'POST', body: payload })
  },

  getJob(jobId) {
    return jsonFetch(`/api/jobs/${jobId}`)
  },

  downloadUrl(jobId) {
    return `/api/jobs/${jobId}/download`
  },

  jobPreviewUrl(jobId) {
    return `/api/jobs/${jobId}/preview`
  },

  startConcatPreview(hiresFileIds) {
    return jsonFetch('/api/concat-preview', {
      method: 'POST',
      body: { hires_file_ids: hiresFileIds },
    })
  },

  concatPreviewStatus(hash) {
    return jsonFetch(`/api/concat-preview/${hash}/status`)
  },

  concatPreviewUrl(hash) {
    return `/api/concat-preview/${hash}`
  },
}

/** Upload a File/Blob in chunks with progress. */
export async function uploadFile(file, kind, { onProgress, signal } = {}) {
  const init = await api.initUpload(file.name, file.size, kind)
  const uploadId = init.upload_id
  let received = init.received || 0

  while (received < file.size) {
    if (signal?.aborted) {
      api.cancelUpload(uploadId).catch(() => {})
      throw new Error('aborted')
    }

    const end = Math.min(received + CHUNK_SIZE, file.size)
    const chunk = file.slice(received, end)

    let attempt = 0
    while (true) {
      try {
        await putChunk(uploadId, received, chunk, signal)
        received = end
        onProgress?.(received / file.size)
        break
      } catch (err) {
        if (signal?.aborted) throw new Error('aborted')
        attempt++
        if (attempt > MAX_RETRIES_PER_CHUNK) {
          throw new Error(`upload failed after ${attempt} attempts: ${err.message}`)
        }
        // Re-sync with server in case the chunk partially landed.
        try {
          const state = await api.getUpload(uploadId)
          received = state.received
        } catch { /* keep `received` and retry */ }
        await new Promise(r => setTimeout(r, 500 * attempt))
      }
    }
  }

  const completed = await api.completeUpload(uploadId)
  return completed.file
}

function putChunk(uploadId, offset, blob, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', `/api/uploads/${uploadId}?offset=${offset}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve()
      else reject(new Error(`HTTP ${xhr.status}: ${xhr.responseText}`))
    }
    xhr.onerror = () => reject(new Error('network error'))
    xhr.onabort = () => reject(new Error('aborted'))
    if (signal) {
      const onAbort = () => xhr.abort()
      signal.addEventListener('abort', onAbort, { once: true })
    }
    xhr.send(blob)
  })
}
