# Architecture

## Shape

```
React (Vite, nginx)
      │  JSON + SSE
      ▼
FastAPI ── middleware: trace id, structured log, error contract
      │
      ├── api/          thin routes, no turn logic
      ├── agent/        router → orchestrator → tools/loop
      ├── skills/       ship30 (rubric-scored), artifact (sanitised)
      ├── rag/          chunker, embedder, store, retriever, ingest
      ├── grounding/    faithfulness gate
      ├── security/     artifact sanitiser + policy
      └── llm/          ollama | anthropic | openai | echo
      │
      ▼
Postgres 16 + pgvector   (rows, vectors and full-text in one database)
```

Component rule: **routes never contain turn logic, and skills never retrieve on
their own.** All orchestration is in `agent/orchestrator.py`, so there is one
place to read to understand what a turn does. Skills receive evidence; they
don't go get it. That's what makes the essay reuse the exact passages the answer
cited instead of a subtly different set.

## Database schema

```
sessions ──┬─< messages ──< citations
           └─< artifacts

documents ──< chunks          (bookkeeping: what's ingested, content hashes)
chunk_vectors                 (the actual index: text + embedding + tsvector)
request_traces                (one row per turn — the ops table)
```

| Table | Purpose | Notes |
|---|---|---|
| `sessions` | chat container | `user_metadata` JSONB is the hook for auth later |
| `messages` | turns | carries `provider`, `model`, `latency_ms`, and the full `grounding` report as JSONB |
| `citations` | resolved sources per message | denormalised guest/title/timestamp so replaying a session needs no join to the index |
| `artifacts` | rendered docs | stores **post-sanitisation** content plus the sanitiser report |
| `documents` | one row per episode | `content_hash` drives idempotent re-ingest |
| `chunk_vectors` | the index | `vector(384)` + generated `tsvector`, HNSW + GIN |
| `request_traces` | per-turn telemetry | provider, retrieval count, grounding score, stage timings |

`citations` is denormalised on purpose. A session replay shouldn't break because
the index was rebuilt with different chunk boundaries — the citation is a
historical record of what the answer was actually based on.

**No Alembic.** The schema has never shipped. Add migrations the moment a second
team depends on the API, or on the first change that isn't additive — until
then, `create_all` plus `make clean` is a shorter path with the same outcome.

## API

| Method | Path | Notes |
|---|---|---|
| POST | `/api/sessions` | 201 with the session |
| GET | `/api/sessions` | with message counts |
| GET | `/api/sessions/{id}/messages` | full replay incl. grounding + citations |
| DELETE | `/api/sessions/{id}` | cascades messages, citations, artifacts |
| POST | `/api/chat` | one turn, complete JSON |
| POST | `/api/chat/stream` | SSE: `stage` events then one `result` |
| GET | `/api/artifacts/{id}` | |
| GET | `/api/artifacts?session_id=` | |
| GET | `/api/artifacts/policy` | permit/block table, generated from the enforcing code |
| GET | `/api/health` | database + index + every provider |
| GET | `/api/health/live` | liveness only — touches nothing |
| GET | `/api/config` | UI config; key *presence*, never keys |
| GET | `/api/admin/traces` | recent turns |
| POST | `/api/admin/ingest` | 202, poll `GET /api/admin/ingest` |

Two health endpoints on purpose: a liveness probe that depends on Postgres will
restart a healthy app during a database blip.

Errors are uniform — `{code, message, detail, trace_id}` — and `code` is stable
enough to branch on. Every response carries `x-trace-id`, which is on every log
line for that request.

### Streaming

`/api/chat/stream` sends progress stages, not tokens. The grounding gate has to
see the whole answer before it can label any sentence, so token streaming would
render text and then strike it through — worse than a short honest wait. If the
client wants token streaming, the shape is: stream into a buffer, run the gate
on completion, then patch the rendered sentences. That is a real UI cost for a
perceived-latency gain, and it should be a deliberate decision, not a default.

## Ingestion and retrieval

**Chunking is speaker-turn aware.** Transcripts are `Speaker (00:14:32):` blocks
with bare `(00:15:01):` continuations. Turns are parsed first, then packed to
~1400 chars with one turn of overlap. Fixed-width chunking would glue the tail
of Lenny's question to the head of a guest's answer, and the citation would then
attribute the answer to the wrong person — the exact failure that makes
timecoded citations worse than none.

**Ingest is idempotent.** `sha256` of each source file is stored on `documents`;
unchanged files are skipped. A weekly cron that adds one episode re-embeds one
episode. `--force` overrides.

**Retrieval is hybrid.** Dense (pgvector cosine, HNSW) and lexical (Postgres
`ts_rank_cd`) each return 30 candidates, fused with Reciprocal Rank Fusion
(k=60) down to 8. Dense alone misses exact terms like "11-star"; lexical alone
misses paraphrase. RRF needs no score normalisation between two arms whose
scores aren't comparable.

**Query planning is a dictionary, not a model.** Capitalised tokens matching a
known guest name become a filter. Requiring capitalisation stops "does the
design work" from filtering to a guest. If the filter starves the result set the
retriever drops it and re-runs — a name in a question is often someone the guest
*mentions*, not the guest.

**Embeddings are local** (`bge-small-en-v1.5`, 384d, ONNX on CPU). An API
embedder would mean the evaluator needs a paid key before anything works.

### Vector store is pluggable

`pgvector` for deployment, `memory` (numpy + BM25) for tests and eval, behind
one Protocol. This is why `make test` needs no database and `make eval` produces
numbers anyone can reproduce in under a minute. Both are exercised by the same
retrieval tests.

## Agent layer

The agent is defined by its **tool contract** (`agent/tools.py`), with two
runners against it:

| Runner | Used when | Why |
|---|---|---|
| `agent/loop.py` | Ollama, and by default everywhere | Portable tool-calling loop, capped at 3 steps |
| `agent/sdk_runner.py` | `USE_AGENT_SDK=true` + Anthropic | Claude Agent SDK |

**Why both.** The brief asks for the Claude Agent SDK *and* for the demo to run
on local Ollama. Those can't be the same code path — the SDK talks to
Anthropic's models and has no Ollama adapter. Rather than silently drop one
requirement, the tool contract is the interface and there are two
implementations. Same tools, same system prompt, same grounding gate downstream.
Cost: ~60 lines of loop we'd otherwise get free.

**Routing is rule-first.** A 3B model asked "what is founder mode" will call
`write_ship30_essay` a meaningful fraction of the time, because "write" appears
in the tool description. Deterministic rules catch the unambiguous cases — which
is most traffic — and only genuinely ambiguous queries cost a classification
call. The classifier defaults to `answer` on any parse failure, because
answering when an essay was wanted is a far smaller failure than the reverse.

Three tools only. Every extra tool is another thing a small model picks wrong.

## Grounding gate

Runs after generation, before persistence. Splits the answer into sentences,
splits retrieved passages into *sentences* (not chunks — a 1400-char chunk
embedded whole washes out the one line that matters), and scores each claim:

```
score = 0.65 · cosine(claim, best evidence sentence)
      + 0.35 · content-word overlap(claim, that sentence)
```

Cosine catches paraphrase, which is most of a good answer. Overlap is the veto
for invented specifics — a sentence can be topically perfect and still contain a
number nobody said. Thresholds are calibrated in `eval/REPORT.md` and selected
on **F0.5, not F1**, because a false *supported* label is invisible while a
false *unsupported* label is an underline the reader can check.

**Why not an LLM judge:** a second full generation, non-deterministic, so the
same answer scores differently across runs — useless as a regression signal.
**Why not NLI:** right answer, second model, second download. The upgrade path
is a cross-encoder; the calibration set is already the harness for A/B-ing it.

Cost scales with retrieved context, not answer length. Evidence sentences are
capped and cached per process.

## Model configuration

One `Settings` object; no provider name appears in application code. Providers
implement `complete()` and `health()`. `ProviderUnavailable` is distinct from a
model error — only the former triggers fallback, because retrying a bad prompt
on a different model usually yields a second bad answer more slowly.

`FALLBACK_PROVIDER` defaults to `none` so a broken local setup fails loudly
instead of quietly spending money on a cloud key. When it does fire, the message
carries a visible badge.

Per-request `provider` override on `/api/chat` lets an evaluator compare local
and cloud on the same question with no restart.

## Security

Full threat model in [SECURITY.md](SECURITY.md). Short version: artifacts render
in `<iframe sandbox="allow-scripts">` with no `allow-same-origin` (opaque origin
→ no parent DOM, no cookies, no storage) plus an injected CSP of
`default-src 'none'` (no network). Scripts are *contained*, not stripped,
because regex script-stripping is bypassable and would break interactive
artifacts. The server strips what is dangerous *and* useless — external loads,
forms, frames, `javascript:` URLs — and reports everything it removed.

Secrets: never logged, never returned; `/api/config` exposes presence only.

## Deployment

Three containers: `db` (pgvector/pg16, healthchecked), `api`, `web` (nginx
serving a static build). Ollama runs on the host, reached via
`host.docker.internal` mapped to `host-gateway` for Linux. The HuggingFace cache
is a named volume so the embedding model downloads once.

The API boots **degraded rather than crash-looping** if Postgres is slow —
`/api/health` names the broken subsystem. Crash-looping hides the reason.

### Where this stops scaling

| Limit | Symptom | Fix |
|---|---|---|
| ~50 concurrent users | CPU-bound on embeddings | Replicas behind a load balancer; move embedding to a sidecar |
| ~1M chunks | HNSW build time and memory | Partition by episode date, or a dedicated vector DB |
| Multi-tenant | No isolation | Row-level security on `session_id`, real auth |
| Multiple API replicas | The `memory` backend and the evidence cache are per-process | Already fine: prod uses pgvector; the cache is an optimisation, not state |

## Observability

Structured JSON logs with a request-scoped `trace_id`. `request_traces` gives
one row per turn with stage timings, so "it was slow yesterday" is answerable
with a query rather than a guess. Health endpoints separate database, index and
each provider so a failure names itself.

The debugging entry point is `python -m app.cli ask "question"` — retrieval only,
no model. It answers "is the model wrong or is retrieval wrong?" in one command,
which is the first question in almost every RAG bug report.
