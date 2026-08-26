import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, streamChat } from './lib/api.js'
import { ArtifactViewer } from './components/ArtifactViewer.jsx'
import { Composer } from './components/Composer.jsx'
import { Message } from './components/Message.jsx'
import { Receipts } from './components/Citations.jsx'
import { Sidebar } from './components/Sidebar.jsx'

const STARTERS = [
  ['What is founder mode, and what does Chesky actually do differently?',
   'grounded answer with timecoded sources'],
  ['How do you know when you have product-market fit?',
   'synthesises across several guests'],
  ['Write a Ship 30 essay on why growth loops beat funnels',
   'runs the essay skill and shows its rubric score'],
  ['Make me an HTML one-pager on running user interviews',
   'renders in the artifact viewer'],
]

export default function App() {
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState(null)
  const [error, setError] = useState(null)

  const [health, setHealth] = useState(null)
  const [config, setConfig] = useState(null)
  const [provider, setProvider] = useState('ollama')

  const [panel, setPanel] = useState(null) // 'receipts' | 'artifact' | null
  const [artifact, setArtifact] = useState(null)
  const [receipts, setReceipts] = useState([])
  const [railOpen, setRailOpen] = useState(false)

  const threadRef = useRef(null)

  // ── boot ────────────────────────────────────────────────────────────────
  useEffect(() => {
    api.config().then((c) => {
      setConfig(c)
      setProvider(c.active_provider)
    }).catch(() => {})
    api.health().then(setHealth).catch(() => setHealth(null))
    api.listSessions().then(setSessions).catch(() => {})
  }, [])

  // Re-poll health after each turn so the pill reflects a provider that just
  // went down, rather than whatever was true at page load.
  const refreshHealth = useCallback(() => {
    api.health().then(setHealth).catch(() => {})
  }, [])

  useEffect(() => {
    const el = threadRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, busy])

  // ── sessions ────────────────────────────────────────────────────────────
  async function newChat() {
    const s = await api.createSession()
    setSessions((prev) => [s, ...prev])
    setActiveId(s.id)
    setMessages([])
    setArtifact(null)
    setReceipts([])
    setPanel(null)
    setRailOpen(false)
  }

  async function selectSession(id) {
    setActiveId(id)
    setRailOpen(false)
    setArtifact(null)
    setPanel(null)
    const rows = await api.messages(id)
    setMessages(rows.map((m) => ({
      role: m.role, content: m.content, route: m.skill, model: m.model,
      provider: m.provider, grounding: m.grounding, citations: m.citations,
      timings: m.latency_ms ? { total_ms: m.latency_ms } : null,
    })))
  }

  async function removeSession(id) {
    await api.deleteSession(id)
    setSessions((prev) => prev.filter((s) => s.id !== id))
    if (id === activeId) {
      setActiveId(null)
      setMessages([])
    }
  }

  // ── sending ─────────────────────────────────────────────────────────────
  async function send(text) {
    const content = (text ?? draft).trim()
    if (!content || busy) return

    let sid = activeId
    if (!sid) {
      const s = await api.createSession()
      setSessions((prev) => [s, ...prev])
      sid = s.id
      setActiveId(sid)
    }

    setError(null)
    setDraft('')
    setBusy(true)
    setStage('routing')
    setMessages((prev) => [...prev, { role: 'user', content }])

    streamChat({
      sessionId: sid,
      message: content,
      provider,
      onStage: setStage,
      onResult: (r) => {
        setMessages((prev) => [...prev, {
          role: 'assistant', content: r.text, route: r.route, model: r.model,
          provider: r.provider, used_fallback: r.used_fallback,
          grounding: r.grounding, citations: r.citations,
          scorecard: r.scorecard, timings: r.timings,
        }])
        if (r.citations?.length) setReceipts(r.citations)
        if (r.artifact) {
          setArtifact(r.artifact)
          setPanel('artifact')
        } else if (r.citations?.length && panel === null) {
          setPanel('receipts')
        }
        setBusy(false)
        setStage(null)
        refreshHealth()
        api.listSessions().then(setSessions).catch(() => {})
      },
      onError: (e) => {
        setError(e)
        setBusy(false)
        setStage(null)
        refreshHealth()
      },
    })
  }

  function openCitation(c) {
    setPanel('receipts')
    // Let the panel mount before scrolling to the row.
    requestAnimationFrame(() => {
      document.getElementById(`receipt-${c.marker}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const indexEmpty = health && health.index && health.index.chunks === 0
  const providerDown = health && !health.providers?.find((p) => p.provider === provider)?.ok

  return (
    <div className={`shell${panel ? ' with-panel' : ''}`}>
      <button className="rail-toggle" onClick={() => setRailOpen((v) => !v)}
              aria-label="Toggle chat list">☰</button>

      <Sidebar
        open={railOpen}
        sessions={sessions}
        activeId={activeId}
        health={health}
        config={config}
        provider={provider}
        onProvider={setProvider}
        onNew={newChat}
        onSelect={selectSession}
        onDelete={removeSession}
      />

      <main className="main">
        {indexEmpty && (
          <div className="banner">
            <strong>No transcripts indexed.</strong>
            <span>Run <code>make ingest-docker</code>, then reload.</span>
          </div>
        )}
        {providerDown && !indexEmpty && (
          <div className="banner bad">
            <strong>{provider} isn’t reachable.</strong>
            <span>
              {health?.providers?.find((p) => p.provider === provider)?.detail}
            </span>
          </div>
        )}
        {error && (
          <div className="banner bad">
            <strong>{error.code === 'provider_unavailable' ? 'Model unavailable.' : 'That didn’t go through.'}</strong>
            <span>{error.message}</span>
            {error.trace_id && <code>trace {error.trace_id}</code>}
          </div>
        )}

        <div className="thread" ref={threadRef}>
          {messages.length === 0 ? (
            <div className="empty">
              <h2>Ask the archive, get receipts.</h2>
              <p>
                Every answer is built from Lenny’s Podcast transcripts and shows
                which episode and timecode each claim came from — plus what
                couldn’t be verified.
              </p>
              <div className="starters">
                {STARTERS.map(([q, why]) => (
                  <button key={q} className="starter" onClick={() => send(q)}>
                    {q}
                    <em>{why}</em>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="thread-inner">
              {messages.map((m, i) => (
                <Message key={i} msg={m} onOpenCitation={openCitation} />
              ))}
            </div>
          )}
        </div>

        <Composer
          value={draft}
          onChange={setDraft}
          onSend={() => send()}
          busy={busy}
          stage={stage}
        />
      </main>

      {panel && (
        <aside className="panel">
          <div className="panel-head">
            <div className="panel-tabs">
              <button
                className={`panel-tab${panel === 'receipts' ? ' active' : ''}`}
                onClick={() => setPanel('receipts')}
              >
                Receipts{receipts.length ? ` (${receipts.length})` : ''}
              </button>
              <button
                className={`panel-tab${panel === 'artifact' ? ' active' : ''}`}
                onClick={() => setPanel('artifact')}
              >
                Artifact
              </button>
            </div>
            <button className="panel-close" onClick={() => setPanel(null)}
                    aria-label="Close panel">×</button>
          </div>
          <div className="panel-body">
            {panel === 'receipts'
              ? <Receipts citations={receipts} />
              : <ArtifactViewer artifact={artifact} />}
          </div>
        </aside>
      )}
    </div>
  )
}
