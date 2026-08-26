# Manual test plan

Automated coverage (`make test`, 65 tests) covers the API contract, retrieval,
routing, grounding and the sanitiser. This plan covers what can't be asserted
headlessly: rendering, interaction and failure states.

Estimated time: ~15 minutes.

## Setup

```bash
make transcripts && make up && make ingest-docker
make smoke        # should print "smoke passed"
```

## 1. First run

| # | Step | Expect |
|---|---|---|
| 1.1 | Open `localhost:5173` before ingesting | Amber banner naming `make ingest-docker` |
| 1.2 | Open after ingest | Empty state with four starters |
| 1.3 | Check the rail footer | Provider `ollama`, green dot, model in mono |
| 1.4 | Stop Ollama, reload | Red dot; banner with the backend's own detail text |

## 2. Grounded answer

| # | Step | Expect |
|---|---|---|
| 2.1 | Click "What is founder mode…" | Named progress stages, not a bare spinner |
| 2.2 | Read the answer header | Badge like `12/13 grounded`; route tag; model; elapsed |
| 2.3 | Look for flagged sentences | Any amber/red sentence has a legend below explaining it |
| 2.4 | Hover a flagged sentence | Tooltip with the score |
| 2.5 | Read the citation chips | Guest name + mono timecode |
| 2.6 | Click a chip | Panel opens, scrolls to that receipt |
| 2.7 | Click "Play from …" | YouTube opens at that second |
| 2.8 | Ask a follow-up ("what about for B2B?") | Stays on topic — the previous turn is folded into retrieval |

## 3. Refusal

| # | Step | Expect |
|---|---|---|
| 3.1 | Ask "What's the boiling point of liquid nitrogen?" | Declines, names what the archive covers |
| 3.2 | Check | No fabricated citation |

## 4. Ship 30 skill

| # | Step | Expect |
|---|---|---|
| 4.1 | "Write a Ship 30 essay on why growth loops beat funnels" | Route tag reads `ship 30 essay` |
| 4.2 | Check length | ~1,250 words, subheads, bullets, sparing bold |
| 4.3 | Expand the scorecard | Six dimensions with bars, scores, detail strings |
| 4.4 | If revised | Note reads e.g. `revised for hook: 0.71 → 0.83` |
| 4.5 | Check citations | `[n]` markers resolve to chips below |

## 5. Artifacts and the security demo

| # | Step | Expect |
|---|---|---|
| 5.1 | "Make me an HTML one-pager on running user interviews" | Renders in the right panel, styled |
| 5.2 | Click "What's blocked?" | Permit/block lists, live CSP, sandbox attribute |
| 5.3 | Inspect the iframe in devtools | `sandbox="allow-scripts"`, **no** `allow-same-origin` |
| 5.4 | Ask for markdown instead | Renders as prose, not raw source |
| 5.5 | **Exfil demo** — ask for an HTML page containing a tracking pixel, an external script, an iframe and a form posting to another domain | Renders inert; "N blocked" chip; rules listed; devtools Network shows no outbound request |

## 6. Sessions

| # | Step | Expect |
|---|---|---|
| 6.1 | New chat, ask something | Title backfills from the first message |
| 6.2 | Switch to the old session | Full history restores with grounding + citations |
| 6.3 | Ask in session B, return to A | A is unchanged — no context bleed |
| 6.4 | Delete a session | Disappears; reload confirms |

## 7. Provider toggle

| # | Step | Expect |
|---|---|---|
| 7.1 | Switch to `echo` | Amber "stub, not a model" warning |
| 7.2 | Ask something on echo | Answer is odd but the pipeline works; badge still renders |
| 7.3 | With a key set, switch to `anthropic`, re-ask 2.1 | Visibly better answer; model name updates on the message |
| 7.4 | Set `FALLBACK_PROVIDER=anthropic`, stop Ollama, ask | Answers via Claude with a "fell back" badge on the message |

## 8. Failure handling

| # | Step | Expect |
|---|---|---|
| 8.1 | `docker compose stop db`, reload | API stays up; `/api/health` reports the database down |
| 8.2 | Set `OLLAMA_MODEL` to something unpulled | Error names the exact `ollama pull` command |
| 8.3 | Send a blank message | Send button disabled |
| 8.4 | Ask something absurd ("qqqq zzzz") | Graceful "no material" answer, no crash |

## 9. Responsive and accessibility

| # | Step | Expect |
|---|---|---|
| 9.1 | Narrow to ~900px | Panel becomes an overlay drawer |
| 9.2 | Narrow to ~500px | Rail becomes a toggle; single column |
| 9.3 | Tab through the page | Visible focus ring everywhere; logical order |
| 9.4 | Enable reduced motion | Transitions collapse |
| 9.5 | Zoom to 200% | No clipped text or overlap |

Known gaps are listed honestly at the end of `design.md` — flagged sentences
aren't announced as a distinct region to screen readers, focus isn't trapped in
mobile drawers, and there's no skip link.

## 10. Operations

| # | Step | Expect |
|---|---|---|
| 10.1 | `make logs` | JSON lines with a `trace_id` per request |
| 10.2 | `curl localhost:8000/api/admin/traces` | One row per turn with stage timings |
| 10.3 | Re-run `make ingest-docker` | Everything skipped — nothing re-embedded |
| 10.4 | `docker compose exec api python -m app.cli ask "founder mode"` | Passages with scores, no generation |
| 10.5 | `make eval` | Regenerates `backend/eval/REPORT.md` with corpus size stated |
