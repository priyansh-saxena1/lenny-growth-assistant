// One place that knows how to talk to the API. Every call returns parsed JSON
// or throws an ApiError carrying the backend's error contract, so components
// can show the real reason instead of "something went wrong".

const BASE = import.meta.env.VITE_API_BASE || ''

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `HTTP ${status}`)
    this.status = status
    this.code = body?.code || 'unknown'
    this.traceId = body?.trace_id
  }
}

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'content-type': 'application/json' },
    ...options,
  })
  if (res.status === 204) return null
  let body = null
  try {
    body = await res.json()
  } catch {
    /* empty or non-JSON body — status still tells us what happened */
  }
  if (!res.ok) throw new ApiError(res.status, body)
  return body
}

export const api = {
  health: () => req('/api/health'),
  config: () => req('/api/config'),
  listSessions: () => req('/api/sessions'),
  createSession: (title) =>
    req('/api/sessions', { method: 'POST', body: JSON.stringify({ title }) }),
  deleteSession: (id) => req(`/api/sessions/${id}`, { method: 'DELETE' }),
  messages: (id) => req(`/api/sessions/${id}/messages`),
  chat: (sessionId, message, provider) =>
    req('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, message, provider }),
    }),
  artifactPolicy: () => req('/api/artifacts/policy'),
}

// Progress events then one result. See backend/app/api/chat.py for why this
// streams stages rather than tokens.
export function streamChat({ sessionId, message, provider, onStage, onResult, onError }) {
  const ctrl = new AbortController()
  ;(async () => {
    try {
      const res = await fetch(`${BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message, provider }),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) throw new ApiError(res.status, await res.json().catch(() => null))

      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const frames = buf.split('\n\n')
        buf = frames.pop() ?? ''
        for (const frame of frames) {
          const ev = /^event:\s*(.+)$/m.exec(frame)?.[1]?.trim()
          const data = /^data:\s*([\s\S]+)$/m.exec(frame)?.[1]
          if (!data) continue
          const parsed = JSON.parse(data)
          if (ev === 'stage') onStage?.(parsed.stage)
          else if (ev === 'result') onResult?.(parsed)
          else if (ev === 'error') onError?.(parsed)
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') onError?.({ code: err.code || 'network', message: err.message })
    }
  })()
  return () => ctrl.abort()
}
