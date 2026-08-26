// Grounding UI.
//
// The badge answers "should I trust this?" at a glance; the underlines answer
// "which part shouldn't I trust?". Both read from the same per-sentence
// verdicts the backend produced, so the UI can't disagree with the gate.

export function GroundingBadge({ grounding }) {
  if (!grounding || !grounding.total_claims) return null
  const { supported, total_claims: total, score } = grounding
  const tone = score >= 0.8 ? 'good' : score >= 0.5 ? 'mid' : 'poor'
  const label =
    tone === 'good' ? 'grounded' : tone === 'mid' ? 'partly grounded' : 'weakly grounded'
  return (
    <span
      className={`ground-badge ${tone}`}
      title={`${supported} of ${total} claims matched a retrieved passage. Checked against evidence, not against the citation markers.`}
    >
      <span className="frac">{supported}/{total}</span> {label}
    </span>
  )
}

// Rebuild the answer with each sentence wrapped according to its verdict.
// We match on the sentence text the gate returned rather than re-splitting
// here — two splitters would eventually disagree and mislabel something.
export function GroundedText({ text, grounding, children }) {
  const flagged = (grounding?.sentences || []).filter(
    (s) => s.label === 'partial' || s.label === 'unsupported'
  )
  if (!flagged.length) return children

  let out = [text]
  for (const s of flagged) {
    out = out.flatMap((part) => {
      if (typeof part !== 'string') return [part]
      const i = part.indexOf(s.text)
      if (i === -1) return [part]
      return [
        part.slice(0, i),
        <mark
          key={`${s.label}-${i}-${s.text.slice(0, 12)}`}
          className={`claim claim-${s.label}`}
          style={{ background: 'none' }}
          title={
            s.label === 'unsupported'
              ? `No retrieved passage supports this (score ${s.score}). Treat as unverified.`
              : `Only partly supported by the evidence (score ${s.score}).`
          }
        >
          {s.text}
        </mark>,
        part.slice(i + s.text.length),
      ]
    })
  }
  return <p>{out}</p>
}

export function GroundingLegend({ grounding }) {
  if (!grounding) return null
  const flagged = grounding.partial + grounding.unsupported
  if (!flagged) return null
  return (
    <div className="ground-legend">
      {grounding.unsupported > 0 && (
        <>
          <strong>{grounding.unsupported}</strong> sentence
          {grounding.unsupported === 1 ? '' : 's'} underlined in red couldn’t be matched
          to any retrieved passage.{' '}
        </>
      )}
      {grounding.partial > 0 && (
        <>
          <strong>{grounding.partial}</strong> shaded amber are only partly supported.{' '}
        </>
      )}
      Open the receipts to read the passage each claim was checked against.
    </div>
  )
}
