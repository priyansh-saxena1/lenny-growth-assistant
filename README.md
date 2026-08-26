# The Lenny Growth Assistant

A grounded product-and-growth assistant over Lenny's Podcast transcripts. Ask a
question, get an answer built from the archive with the episode and timecode
behind every claim — and an explicit mark on anything the transcripts don't
actually support.

Built as a forward-deployment exercise: it should be something another team can
run, trust, and extend, not just a demo that works once.

```
┌──────────┐   ┌───────────────────────────────────────────────┐   ┌──────────┐
│  React   │──▶│  FastAPI                                      │──▶│ Postgres │
│  chat +  │   │  router → retrieval → skill → grounding gate  │   │ +pgvector│
│ artifact │◀──│                                               │◀──│          │
└──────────┘   └───────────┬───────────────────┬───────────────┘   └──────────┘
                           │                   │
                    ┌──────▼──────┐     ┌──────▼───────┐
                    │   Ollama    │     │  Claude /    │
                    │  (default)  │     │  OpenAI      │
                    └─────────────┘     └──────────────┘
```

## What's actually interesting here

**Citations are verified, not asserted.** A model writing `[3]` after a sentence
is generating a token, not proving anything. After every answer, each sentence
is scored against the passages that were actually retrieved. Unsupported
sentences get underlined in the UI and the header reads *"14/15 claims
grounded"*. The check is deterministic, so the same answer always scores the
same — which is what makes it usable as a regression signal. See
[`grounding/faithfulness.py`](backend/app/grounding/faithfulness.py).

**The Ship 30 skill is data, not a prompt.** Writing principles live in
[`skill.yaml`](backend/app/skills/ship30/skill.yaml) as a rubric with weights and
floors. Essays are scored against it programmatically, and dimensions below
their floor trigger one targeted revision — which is discarded if it doesn't
improve the score. The scorecard renders next to the essay.

**`make eval` produces a number you can regress against.** 20 golden questions
(5 deliberately unanswerable), retrieval recall, refusal correctness, latency,
plus a threshold sweep for the grounding gate. Output:
[`backend/eval/REPORT.md`](backend/eval/REPORT.md). It runs with no model and no
database.

**Artifacts are contained, not scrubbed.** HTML renders in a sandboxed iframe
with no `allow-same-origin` and a CSP of `default-src 'none'`, so scripts run
but can't reach the network, the parent DOM, or cookies. The viewer reports what
it blocked. See [SECURITY.md](docs/SECURITY.md).

**It runs with zero secrets.** Default provider is local Ollama, embeddings are
local, Postgres is in the compose file. No API key is needed to see it work.

## Prerequisites

| | |
|---|---|
| Docker + Compose | for the one-command path |
| [Ollama](https://ollama.com) on the host | the demo model |
| Python 3.12 + Node 22 | only for the no-Docker path |

```bash
ollama pull qwen2.5:3b-instruct   # ~2GB, tool-calling capable
```

3B is the default so this runs on a laptop with no GPU and 8GB of RAM. With
16GB or a GPU, `qwen2.5:7b-instruct` follows citation instructions noticeably
better — set `OLLAMA_MODEL` to match whatever you pulled. Any tool-calling model
works; `llama3.1:8b`, `llama3.2:3b` and `mistral-nemo` are all fine.

## Run it

```bash
git clone https://github.com/priyansh-saxena1/lenny-growth-assistant.git
cd lenny-growth-assistant

make transcripts     # downloads 303 episodes (~9MB)
make up              # Postgres + API + web
make ingest-docker   # index the corpus (~5 min on 8 cores)
```

Then open **http://localhost:5173**.

```bash
make smoke           # end-to-end check, prints grounding + sanitiser results
```

`make up` works before ingest — the UI tells you the index is empty rather than
failing mysteriously.

### Without Docker

```bash
make install
make ingest          # in-memory index, no Postgres needed
make test
cd backend && PYTHONPATH=. VECTOR_BACKEND=memory \
  DATABASE_URL=sqlite+aiosqlite:///./local.sqlite3 \
  ../.venv/bin/uvicorn app.main:app --port 8000
make web             # separate terminal
```

## Switching models

Nothing in the application code changes. Either edit `.env`:

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

…or pick a provider from the dropdown in the sidebar, which overrides per
request so you can compare local and cloud on the same question.

`FALLBACK_PROVIDER` controls what happens when the active provider is
unreachable. It defaults to `none` on purpose: a broken local setup should fail
loudly, not quietly start spending money on a cloud key. Set it to `anthropic`
and a dead Ollama degrades to Claude with a visible badge on the message.

## Commands

```
make help            list everything
make up / down       start / stop the stack
make transcripts     download the corpus
make ingest-docker   index into the running stack
make test            65 tests, no infra required (~2s)
make eval            retrieval + calibration → backend/eval/REPORT.md
make eval-ollama     adds answer quality, refusal rate, end-to-end latency
make smoke           end-to-end check against a running API
make logs            tail structured API logs
make clean           stop and delete all data
```

## Environment

Everything is in [.env.example](.env.example) with working defaults. The ones
worth knowing:

| Variable | Default | Notes |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` / `anthropic` / `openai` / `echo` |
| `OLLAMA_MODEL` | `qwen2.5:3b-instruct` | must be pulled first |
| `FALLBACK_PROVIDER` | `none` | see above |
| `VECTOR_BACKEND` | `pgvector` | `memory` for tests and laptop runs |
| `RETRIEVAL_TOP_K` | `8` | passages per answer |
| `FAITHFULNESS_SUPPORTED_AT` | `0.65` | calibrated in `eval/REPORT.md` |
| `FAITHFULNESS_ENABLED` | `true` | set false to A/B the gate's latency cost |
| `SERVE_FRONTEND` | `false` | see below |

`echo` is a deterministic stub, not a model. It exists so tests and eval run
with no infrastructure. The UI shows a warning when it's selected.

## Cloud GPU demo (Colab)

The laptop this was built on has no GPU and 4 CPU cores; measured end-to-end
turn latency on it is documented honestly in [PRD.md](docs/PRD.md) and
[eval/REPORT.md](backend/eval/REPORT.md) rather than hidden. [colab_t4_demo.ipynb](colab_t4_demo.ipynb)
runs the identical stack — same FastAPI backend, same ingest and eval code —
against `qwen2.5:7b-instruct` on a free T4 GPU, for recording the demo and for
regenerating eval numbers against the full 303-episode corpus in minutes
instead of hours.

Colab hands the API and a separately-served frontend two different public
origins, which turns an ordinary local setup into a cross-origin (CORS)
problem for no benefit. Setting `SERVE_FRONTEND=true` makes the API process
also serve the built frontend (`frontend/dist`) from the same origin, so
there's one address and no cross-origin request to configure around. It's off
by default and irrelevant to the normal Docker Compose path, where the
frontend and API already run on separate, same-machine ports. See
[architecture.md](docs/architecture.md#single-port-mode) for the mechanism.

## API

Interactive docs at `/docs`. The shape:

| Endpoint | Purpose |
|---|---|
| `POST /api/sessions` | start a chat |
| `POST /api/chat` | one turn, full JSON response |
| `POST /api/chat/stream` | same, with SSE progress stages |
| `GET /api/sessions/{id}/messages` | replay a session |
| `GET /api/artifacts/{id}` | fetch a rendered artifact |
| `GET /api/artifacts/policy` | what the viewer permits and blocks |
| `GET /api/health` | database, index and every provider |
| `GET /api/admin/traces` | per-turn provider, retrieval, grounding, timings |
| `POST /api/admin/ingest` | re-index (idempotent) |

Errors share one shape — `{code, message, detail, trace_id}` — and every
response carries `x-trace-id`, which is also on every log line for that request.

## Troubleshooting

**"model not pulled"** — `ollama pull qwen2.5:3b-instruct`. The error names the
exact command.

**Ollama unreachable from Docker** — on Linux the container needs
`host.docker.internal`, which the compose file maps via `host-gateway`. Confirm
Ollama is listening beyond loopback: `OLLAMA_HOST=0.0.0.0 ollama serve`.

**Index is empty** — `make ingest-docker`. Check with
`curl localhost:8000/api/health | jq .index`.

**Answers are vague or uncited** — check retrieval separately before blaming the
model: `docker compose exec api python -m app.cli ask "your question"`. That
prints the passages with scores and no generation in the way.

**Everything is slow** — `GET /api/admin/traces` breaks each turn into
retrieval / generation / grounding milliseconds. On a 7B local model generation
dominates; if grounding does, your `RETRIEVAL_TOP_K` is too high.

**Postgres slow to start** — the API boots degraded rather than crash-looping,
and `/api/health` says which subsystem is down.

## Docs

| | |
|---|---|
| [PRD.md](docs/PRD.md) | user, problem, success metrics, scope, risks |
| [architecture.md](docs/architecture.md) | schema, endpoints, retrieval, agent layer, deployment |
| [design.md](docs/design.md) | UI principles, states, responsive, accessibility |
| [SECURITY.md](docs/SECURITY.md) | artifact threat model and isolation |
| [TESTPLAN.md](docs/TESTPLAN.md) | manual UI test plan |
| [eval/REPORT.md](backend/eval/REPORT.md) | generated by `make eval` |
| [agent-transcripts/](agent-transcripts/) | how this was built, including what broke |

## Attribution

Transcripts are the property of Lenny Rachitsky and the podcast's guests, shared
publicly for exactly this kind of use. They are **not committed to this repo** —
`make transcripts` fetches them at setup. The corpus used here is the
[ChatPRD archive](https://github.com/ChatPRD/lennys-podcast-transcripts).

## AI assistance

Built with Claude as a coding agent, which the brief encourages. Session logs,
including the bugs it introduced and how they were caught, are in
[agent-transcripts/](agent-transcripts/). Notable: the smoke test caught a
sentence-splitting bug that collapsed multi-claim answers into one claim and
silently broke the grounding score — the unit tests missed it because their
fixtures didn't put citation markers mid-answer.
