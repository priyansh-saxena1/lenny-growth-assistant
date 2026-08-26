// Citation chips. The timecode is mono because it's data, and clicking opens
// the passage rather than jumping the user out to YouTube — checking a claim
// shouldn't cost you your place in the conversation.

export function Citations({ citations, onOpen }) {
  if (!citations?.length) return null
  return (
    <div className="cites">
      {citations.map((c) => (
        <button key={c.marker} className="cite" onClick={() => onOpen(c)}
                title={`${c.guest} — ${c.title}`}>
          <span className="cite-n">{c.marker}</span>
          <span className="cite-who">{c.guest}</span>
          <span className="timecode">{c.start_ts}</span>
        </button>
      ))}
    </div>
  )
}

export function Receipts({ citations }) {
  if (!citations?.length) {
    return <div className="panel-pad" style={{ color: 'var(--ink-faint)', fontSize: 13 }}>
      Ask something and the passages behind the answer show up here.
    </div>
  }
  return (
    <div>
      {citations.map((c) => (
        <div className="receipt" key={c.marker} id={`receipt-${c.marker}`}>
          <div className="receipt-head">
            <span className="cite-n">{c.marker}</span>
            <span className="receipt-who">{c.guest}</span>
            <span className="timecode">{c.start_ts}–{c.end_ts}</span>
          </div>
          <div className="receipt-title">{c.title}</div>
          <div className="receipt-text">{c.excerpt}</div>
          {c.youtube_url && (
            <a className="receipt-link" href={c.youtube_url}
               target="_blank" rel="noopener noreferrer">
              Play from {c.start_ts} →
            </a>
          )}
        </div>
      ))}
    </div>
  )
}
