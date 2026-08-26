import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../lib/api.js'

// HTML artifacts render in a sandboxed iframe with no allow-same-origin, so the
// frame sits on an opaque origin: no parent DOM, no cookies, no storage. The
// backend also injects a CSP of default-src 'none', which kills every outbound
// request. Scripts are allowed on purpose — see backend/app/security/sanitize.py
// for why containing them beats stripping them.
const SANDBOX = 'allow-scripts'

export function ArtifactViewer({ artifact }) {
  const [showPolicy, setShowPolicy] = useState(false)
  const [policy, setPolicy] = useState(null)

  useEffect(() => {
    if (showPolicy && !policy) api.artifactPolicy().then(setPolicy).catch(() => {})
  }, [showPolicy, policy])

  if (!artifact) {
    return <div className="panel-pad" style={{ color: 'var(--ink-faint)', fontSize: 13 }}>
      Ask for a document, one-pager or web page and it renders here.
    </div>
  }

  const blocked = artifact.sanitizer_report?.blocked_count || 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div className="artifact-bar">
        <strong style={{ color: 'var(--ink)' }}>{artifact.title}</strong>
        <span className="timecode">{artifact.kind}</span>
        {blocked > 0 && (
          <span className="blocked-tag" title={
            artifact.sanitizer_report.blocked.map((b) => `${b.rule}: ${b.detail}`).join('\n')
          }>
            {blocked} blocked
          </span>
        )}
        <button
          className="panel-tab"
          style={{ marginLeft: 'auto', fontSize: 11.5 }}
          onClick={() => setShowPolicy((v) => !v)}
          aria-expanded={showPolicy}
        >
          {showPolicy ? 'Hide' : 'What’s blocked?'}
        </button>
      </div>

      {showPolicy && policy && (
        <div className="panel-pad policy" style={{ borderBottom: '1px solid var(--rule)' }}>
          <p style={{ marginTop: 0, color: 'var(--ink-soft)' }}>{policy.rationale}</p>
          <h4>Allowed</h4>
          <ul>{policy.permitted.map((p) => <li key={p}>{p}</li>)}</ul>
          <h4>Blocked</h4>
          <ul>{policy.blocked.map((p) => <li key={p}>{p}</li>)}</ul>
          <h4>Enforced by</h4>
          <code>sandbox="{policy.sandbox}"</code>
          <code>{policy.csp}</code>
        </div>
      )}

      {blocked > 0 && (
        <div className="artifact-bar" style={{ background: 'var(--partial-wash)', color: '#7a5010' }}>
          Removed before rendering:{' '}
          {[...new Set(artifact.sanitizer_report.blocked.map((b) => b.rule))].join(', ')}
        </div>
      )}

      <div className="panel-body">
        {artifact.kind === 'html' ? (
          <iframe
            className="artifact-frame"
            title={artifact.title}
            sandbox={SANDBOX}
            srcDoc={artifact.content}
          />
        ) : (
          <div className="panel-pad prose">
            {/* Raw HTML is deliberately not enabled here; the backend already
                stripped it, and enabling it would undo that. */}
            <Markdown remarkPlugins={[remarkGfm]}>{artifact.content}</Markdown>
          </div>
        )}
      </div>
    </div>
  )
}
