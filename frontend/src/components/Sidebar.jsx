export function Sidebar({
  open, sessions, activeId, health, config, provider, onProvider,
  onNew, onSelect, onDelete,
}) {
  const active = health?.providers?.find((p) => p.provider === provider)
  const dot = !health ? 'warn' : active?.ok ? 'ok' : 'bad'
  const model = config?.models?.[provider] || active?.model || '—'

  return (
    <aside className={`rail${open ? ' open' : ''}`}>
      <div className="rail-head">
        <h1 className="wordmark">Lenny <span>Growth</span> Assistant</h1>
        <p className="rail-sub">Grounded in 303 episodes</p>
      </div>

      <button className="new-chat" onClick={onNew}>New chat</button>

      <div className="rail-list">
        <div className="rail-label">Chats</div>
        {sessions.length === 0 && (
          <div style={{ padding: '4px 10px', fontSize: 12.5, color: 'var(--ink-faint)' }}>
            Nothing yet.
          </div>
        )}
        {sessions.map((s) => (
          <div key={s.id} className={`session${s.id === activeId ? ' active' : ''}`}>
            <button
              className="session-title"
              style={{ border: 'none', background: 'none', padding: 0, textAlign: 'left', color: 'inherit', font: 'inherit' }}
              onClick={() => onSelect(s.id)}
            >
              {s.title}
            </button>
            <button
              className="session-kill"
              aria-label={`Delete chat ${s.title}`}
              onClick={() => onDelete(s.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <div className="rail-foot">
        <div className="pill">
          <span className={`dot ${dot}`} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 500 }}>{provider}</div>
            <div className="pill-model">{model}</div>
          </div>
        </div>

        <label className="sr-only" htmlFor="provider">Model provider</label>
        <div className="pill" style={{ display: 'block', marginTop: 8, border: 'none', padding: 0 }}>
          <select id="provider" value={provider} onChange={(e) => onProvider(e.target.value)}>
            {(health?.providers || []).map((p) => (
              <option key={p.provider} value={p.provider}>
                {p.provider}{p.ok ? '' : ' — unavailable'}
              </option>
            ))}
          </select>
        </div>

        {provider === 'echo' && (
          <div className="stub-warn">
            Echo is a deterministic stub for tests, not a language model. Answers
            will look odd. Switch to ollama for the real thing.
          </div>
        )}
        {active && !active.ok && (
          <div className="stub-warn">{active.detail}</div>
        )}
      </div>
    </aside>
  )
}
