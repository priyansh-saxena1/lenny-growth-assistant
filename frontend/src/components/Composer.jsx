import { useEffect, useRef } from 'react'

export function Composer({ value, onChange, onSend, busy, stage }) {
  const ref = useRef(null)

  // Grow with the content, up to the CSS max-height.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`
  }, [value])

  function keyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !busy) onSend()
    }
  }

  return (
    <div className="composer">
      <div className="composer-inner">
        {busy && (
          <div className="thinking" style={{ marginBottom: 10 }}>
            <span className="dot-pulse" />
            {stage === 'retrieving' ? 'Searching transcripts…'
              : stage === 'routing' ? 'Working out what you need…'
              : 'Writing and checking the answer against sources…'}
          </div>
        )}
        <div className="composer-box">
          <label className="sr-only" htmlFor="composer">Message</label>
          <textarea
            id="composer"
            ref={ref}
            rows={1}
            value={value}
            placeholder="Ask about product, growth, hiring — or ask for an essay or a one-pager"
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={keyDown}
            disabled={busy}
          />
          <button className="send" onClick={onSend} disabled={busy || !value.trim()}>
            {busy ? 'Working' : 'Send'}
          </button>
        </div>
        <p className="composer-hint">
          Enter to send, Shift+Enter for a new line. Answers cite the episode and
          timecode they came from.
        </p>
      </div>
    </div>
  )
}
