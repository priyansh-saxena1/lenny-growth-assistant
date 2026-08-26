# PRD — The Lenny Growth Assistant

## Discovery brief

### Who this is for

A product and growth team of roughly 15–40 people at a Series A–C company. The
primary user is an IC PM or growth lead, three to eight years in, who treats
Lenny's Podcast as a reference library rather than entertainment. They already
know the archive is good; the problem is that it's 303 unsearchable hours.

Secondary user: the team lead who wants the answer turned into something
shareable — a doc for a strategy review, a post for the company blog.

### The job

> "I'm about to make a decision I know some guest has already talked through.
> Find me what they actually said, fast enough that it's cheaper than deciding
> from memory — and let me check it before I repeat it in a meeting."

Two halves, and the second is the one competing tools miss. A PM who repeats an
AI-generated claim in a strategy review and gets asked "where's that from?" will
not use the tool twice. **Verifiability is the product, not a feature of it.**

### The pain today

| What they do now | Why it fails |
|---|---|
| Search YouTube captions | No cross-episode synthesis, no ranking |
| Ask ChatGPT | Confidently invents plausible podcast content |
| Ctrl-F a transcript dump | Needs to already know the episode |
| Ask a colleague | Slow, and their recall has the same problem |

The AI failure mode is the dangerous one, because it's indistinguishable from
success until someone checks.

## Success metrics

**Primary — claim-support rate.** Share of factual sentences matched to a
retrieved passage by the grounding gate. Target **≥ 85%**. This is the product
thesis expressed as a number: if it falls, the assistant is confabulating,
whatever else looks fine. Measured on every turn, stored per message, aggregated
in `/api/admin/traces`, and regression-tested by `make eval`.

**Secondary:**

| Metric | Target | Why |
|---|---|---|
| Correct refusal on out-of-corpus questions | ≥ 80% | The failure users won't forgive |
| Retrieval recall@8 on the golden set | ≥ 85% | Isolates retrieval from generation |
| p95 end-to-end latency (local model) | ≤ 20s | Above this people go back to YouTube |
| Citation click-through rate | ≥ 15% of answers | Behavioural check that receipts are trusted |

That last one is the honest one. If nobody ever opens a citation, either the
answers are trusted blindly (bad) or the receipts aren't discoverable (also
bad). It's instrumented but has no baseline yet.

**Explicitly not a metric:** answers per session. Engagement rewards vagueness —
a good assistant should end the conversation faster.

## Assumptions

The brief left these open. Each is recorded with what would change if it's wrong.

1. **Internal tool, trusted users, no auth.** Sessions aren't owned by anyone.
   *If wrong:* add a `user_id` to `sessions` and filter — the column is already
   in the schema as `user_metadata`.
2. **Corpus refreshes weekly at most.** Ingest is a manual/cron job, not
   streaming. *If wrong:* the ingest endpoint is already idempotent and
   content-hashed, so a webhook can call it.
3. **English only.** No translation layer.
4. **Transcript speaker attribution is correct as published.** We propagate it
   rather than verify it. *If wrong:* citations misattribute, which is the worst
   plausible failure. Flagged as a risk below.
5. **~35 concurrent users.** Single API container is enough.
6. **The evaluator has no API key.** Drove the biggest design decision: local
   model, local embeddings, zero-secret startup.
7. **Answers are read on a laptop.** Mobile works and is tested, but the
   side-by-side artifact layout is designed for ≥1080px.

## Scope

### Built

- Session-scoped chat with independent context and full persistence
- Hybrid retrieval (dense + lexical, RRF-fused) with guest-name filtering
- Per-sentence grounding gate with UI surfacing
- Ship 30 essay skill with programmatic rubric scoring and one revision pass
- Markdown + HTML artifacts in a sandboxed side-by-side viewer
- Provider toggle across Ollama / Anthropic / OpenAI, switchable per request
- Health, traces, structured logs, idempotent ingest
- Golden-set eval harness with committed report

### Deliberately excluded

| Not built | Why |
|---|---|
| **Authentication** | Internal tool behind a VPN. Fake auth is worse than none — it implies a security property that doesn't exist. |
| **Token-by-token streaming** | The grounding gate needs the whole answer before it can label anything. Streaming tokens means rendering text that gets struck through a second later. Stage progress instead. |
| **Alembic migrations** | Schema has never shipped. Migrations before the first deploy are ceremony. `architecture.md` names the trigger for adding them. |
| **Reranker model** | Second model, second download, second latency budget. RRF gets recall@8 to 100% on the golden set — a reranker has nothing to fix yet. |
| **Multi-turn query rewriting via LLM** | Prepending the previous user turn fixed most follow-up misses for zero model calls. Upgrade when the golden set has follow-up chains. |
| **Artifact editing / version history** | Users can regenerate. Real editing is a document product, not this. |
| **Analytics dashboard** | `/api/admin/traces` is JSON. A team that wants charts has Grafana. |

## Flows

**Ask → verify.** Question → router (rule-based, no model call for the common
case) → hybrid retrieval → generation with numbered passages → grounding gate →
answer with badge, underlines and timecode chips → click a chip → receipts
drawer opens on that passage → optionally deep-link to the YouTube second.

**Ask → publish.** As above, then "write a Ship 30 essay on this" → essay skill
reuses the same evidence → scored against the rubric → weak dimensions trigger
one revision → essay renders with its scorecard.

**Ask → share.** "Make me an HTML one-pager" → artifact skill → sanitiser →
sandboxed viewer beside the chat, with a count of what was blocked.

## Acceptance criteria

- [x] A fresh clone runs with `make transcripts && make up && make ingest-docker`
- [x] No secret is required to reach a working answer
- [x] Two sessions never share context (tested)
- [x] Every factual sentence is labelled supported / partial / unsupported
- [x] Every citation resolves to a guest, episode and timecode
- [x] Out-of-corpus questions produce a refusal, not an invention
- [x] HTML artifacts cannot make network requests (tested against an exfil payload)
- [x] Provider switches without a code change or restart
- [x] Ollama down produces a clear message, not a stack trace
- [x] `make test` passes with no database, model or network
- [x] `make eval` regenerates a report with corpus size stated

## Risks and trade-offs

**Hallucination — the headline risk.** Mitigated by the grounding gate, but the
gate is an embedding-plus-overlap heuristic, not entailment. It reliably catches
invented specifics and topic drift; it can be fooled by a claim that reuses the
evidence's vocabulary while inverting its meaning. Calibrated at precision 0.75
on 14 labelled pairs — a small set, stated as such in `eval/REPORT.md`. Upgrade
path is a cross-encoder NLI model.

**Small-model quality.** The demo runs a 3B so it works on a laptop with no GPU.
3B models pick tools badly and drop citations. Mitigations: rule-first routing
avoids the tool-choice problem entirely for common queries; the context budget
drops to 5 passages because small models cite better with less; the grounding
gate catches what still slips. The honest statement is that answer quality on
Claude is meaningfully better, and the toggle exists so you can see the gap.

Measured on the full 303-episode corpus against `qwen2.5:7b-instruct` (GPU-run
`eval/REPORT.md`): retrieval is exact — recall@8 100%, all 15 in-corpus goldens
scored — but mean claim-support sits at 12%. Inspecting the worst-scoring claim
per question shows why: the model fuses two or three source passages into one
synthesized sentence (`"In [4], he discusses X, suggesting Y"`), which the
grounding gate — matching each claim sentence to its single closest evidence
sentence — correctly can't verify against either source alone. Tightening
`ANSWER_SYSTEM` to ask for one claim per sentence, closely paraphrasing its
citation, made no measurable difference; a quantized 7B model doesn't reliably
follow that level of stylistic instruction turn to turn. This isn't a scoring
bug — see `eval/REPORT.md`'s per-question table for the fusion pattern — it's
the actual quality ceiling of the required local-CPU-friendly model size. Two
real upgrade paths, both left for a follow-up: (1) chunk-level rather than
sentence-level evidence matching, which would credit a fused claim against the
union of its sources; (2) a model in the 8-14B range, which the 3B-recommended
hardware doesn't support but the toggle to Claude demonstrates working.

**Misattribution.** If an upstream transcript labels a speaker wrong, we cite it
confidently. Speaker-turn chunking makes this *more* visible, not less. Not
mitigated. Would need spot-checking against audio.

**Latency.** The gate adds real time — it scales with retrieved context, not
answer length. Uncapped over 8 full passages it measured 38s on a single core,
which dominated the turn; capping evidence sentences and caching them fixed it.
`FAITHFULNESS_ENABLED=false` exists to measure the trade-off rather than argue
about it.

**Development hardware has no GPU and 4 CPU cores.** Measured end-to-end turn
latency on it runs to the tens of seconds against `qwen2.5:3b-instruct`, which
is workable to use interactively but not something to record a live demo
against without narrating around the wait on every turn. Rather than silently
picking a smaller model to hide this or claiming a laptop capability that
doesn't exist, the demo and the full-corpus eval run (`colab_t4_demo.ipynb`,
see README) use a free Colab T4 GPU running the identical stack and code
against `qwen2.5:7b-instruct` — a real local `ollama serve` process, which
satisfies the brief's "local LLM mandatory for the demo" requirement literally,
just not on the laptop that wrote the code. This is a disclosed hardware
constraint, not a bait-and-switch: the Docker Compose path on a CPU-only
machine still works end to end, just slower than the recorded demo shows.

**Unsafe artifact rendering.** Model-authored HTML that has read
attacker-influenceable text. Contained by an opaque-origin sandbox plus
`default-src 'none'`, not by stripping scripts — see `SECURITY.md` for why
containment beats scrubbing.

**Cost.** Zero at rest: local model, local embeddings. Switching to Claude moves
cost to per-token, and the essay skill can make two generation calls. Token
counts are recorded per message so the client can price it before committing.

**Data leakage.** No user content leaves the machine on the default config. With
a cloud provider, retrieved passages and the user's question go to that vendor.
Stated in the provider dropdown, not buried here.

## Implementation plan

| Phase | Scope |
|---|---|
| 0 — done | Everything in "Built" above |
| 1 — first week with the client | Grow the calibration set to ~150 pairs from real traffic; re-sweep thresholds |
| 2 | Follow-up query rewriting; golden set extended with conversation chains |
| 3 | Cross-encoder NLI to replace the heuristic gate; A/B against the current one on the calibration set |
| 4 | Auth + per-user session ownership if it leaves the VPN |
| 5 | Alembic, once the schema has shipped and someone other than us depends on it |
