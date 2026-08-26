// Ship 30 rubric scorecard. Shown next to the essay so the score is auditable
// rather than a number the model asserted about itself.

export function Scorecard({ card }) {
  if (!card) return null
  return (
    <details className="scorecard">
      <summary>
        <span>
          Ship 30 rubric · {card.word_count} words
          {card.revised && ' · revised once'}
        </span>
        <span className="score-total">{Math.round(card.total * 100)}/100</span>
      </summary>
      <div className="dims">
        {card.dimensions.map((d) => (
          <div className={`dim${d.below_floor ? ' low' : ''}`} key={d.name}>
            <span className="dim-name">{d.name.replace(/_/g, ' ')}</span>
            <span className="bar"><i style={{ width: `${Math.round(d.score * 100)}%` }} /></span>
            <span className="dim-val">{d.score.toFixed(2)}</span>
            <span className="dim-detail">{d.detail}</span>
          </div>
        ))}
        {card.notes?.map((n) => (
          <div className="dim-detail" key={n} style={{ gridColumn: '1 / -1' }}>{n}</div>
        ))}
      </div>
    </details>
  )
}
