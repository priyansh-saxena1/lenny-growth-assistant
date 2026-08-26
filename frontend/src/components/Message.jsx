import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Citations } from './Citations.jsx'
import { GroundedText, GroundingBadge, GroundingLegend } from './Grounding.jsx'
import { Scorecard } from './Scorecard.jsx'

const ROUTE_LABEL = { answer: 'grounded answer', essay: 'ship 30 essay', artifact: 'artifact' }

export function Message({ msg, onOpenCitation }) {
  if (msg.role === 'user') {
    return (
      <div className="msg msg-user">
        <div className="bubble">{msg.content}</div>
      </div>
    )
  }

  const g = msg.grounding
  const flagged = g && (g.partial || g.unsupported)

  return (
    <div className="msg">
      <div className="msg-meta">
        <span className="route-tag">{ROUTE_LABEL[msg.route] || msg.route || 'answer'}</span>
        <GroundingBadge grounding={g} />
        {msg.model && <span className="pill-model">{msg.model}</span>}
        {msg.timings?.total_ms != null && <span>{(msg.timings.total_ms / 1000).toFixed(1)}s</span>}
        {msg.used_fallback && (
          <span className="blocked-tag" title="The configured provider was unreachable.">
            fell back to {msg.provider}
          </span>
        )}
      </div>

      <div className="prose">
        {/* When nothing is flagged we render markdown properly. When something
            is, we switch to the annotated plain-text view — highlighting inside
            a markdown AST would mean re-implementing the renderer. */}
        {flagged
          ? <GroundedText text={msg.content} grounding={g}>{msg.content}</GroundedText>
          : <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>}
      </div>

      <GroundingLegend grounding={g} />
      <Scorecard card={msg.scorecard} />
      <Citations citations={msg.citations} onOpen={onOpenCitation} />
    </div>
  )
}
