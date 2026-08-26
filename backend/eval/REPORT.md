# Evaluation report

Generated 2026-08-24 15:26 UTC · commit `local`

Regenerate with `make eval`. Every number below comes from that command; nothing here is hand-written.

## Corpus this run scored against

- Episodes indexed: **20** of 303 available
- Chunks indexed: **1426**
- Embedding model: `BAAI/bge-small-en-v1.5` (384d)
- Retrieval k: 8

> Partial index. 2 of 15 golden questions are not answerable from these episodes and were marked `not_in_index` rather than counted as misses. Run a full `make ingest` to score all 20.

## Retrieval

| metric | value |
|---|---|
| recall@8 | **100%** (13 scored, 2 not in index) |
| retrieval p50 | 67 ms |
| retrieval p95 | 10373 ms |

<details><summary>Per-question</summary>

| id | status | recall | ms | top guest |
|---|---|---|---|---|
| g01 | not_in_index | — | — | — |
| g02 | scored | yes | 10373 | Adam Fishman |
| g03 | not_in_index | — | — | — |
| g04 | scored | yes | 59 | Adam Grenier |
| g05 | scored | yes | 67 | Anuj Rathi |
| g06 | scored | yes | 56 | Albert Cheng |
| g07 | scored | yes | 74 | Anuj Rathi |
| g08 | scored | yes | 61 | Anneka Gupta |
| g09 | scored | yes | 70 | Anuj Rathi |
| g10 | scored | yes | 59 | Albert Cheng |
| g11 | scored | yes | 80 | Ami Vora |
| g12 | scored | yes | 67 | Adam Fishman |
| g13 | scored | yes | 71 | Anneka Gupta |
| g14 | scored | yes | 66 | Amjad Masad |
| g15 | scored | yes | 71 | Anneka Gupta |

</details>

## Faithfulness gate calibration

14 hand-labelled claim/evidence pairs (`backend/eval/calibration.yaml`). Mean score for supported claims **0.67**, for unsupported **0.481**.

| threshold | TP | FP | TN | FN | precision | recall | F1 | F0.5 |
|---|---|---|---|---|---|---|---|---|
| 0.35 | 6 | 6 | 2 | 0 | 0.5 | 1.0 | 0.667 | **0.556** |
| 0.4 | 6 | 5 | 3 | 0 | 0.545 | 1.0 | 0.706 | **0.6** |
| 0.45 | 6 | 4 | 4 | 0 | 0.6 | 1.0 | 0.75 | **0.652** |
| 0.5 | 6 | 3 | 5 | 0 | 0.667 | 1.0 | 0.8 | **0.714** |
| 0.55 | 5 | 3 | 5 | 1 | 0.625 | 0.833 | 0.714 | **0.658** |
| 0.6 | 5 | 3 | 5 | 1 | 0.625 | 0.833 | 0.714 | **0.658** |
| 0.65 ←configured | 3 | 1 | 7 | 3 | 0.75 | 0.5 | 0.6 | **0.682** |
| 0.7 | 2 | 0 | 8 | 4 | 1.0 | 0.333 | 0.5 | **0.714** |
| 0.75 | 2 | 0 | 8 | 4 | 1.0 | 0.333 | 0.5 | **0.714** |
| 0.8 | 0 | 0 | 8 | 6 | 0.0 | 0.0 | 0.0 | **0.0** |
| 0.85 | 0 | 0 | 8 | 6 | 0.0 | 0.0 | 0.0 | **0.0** |

Configured threshold **0.65** (precision 0.75, recall 0.5, F0.5 0.682). Best F0.5 on this sweep: 0.75.

Selection is on **F0.5, not F1**. The two disagree here, and the disagreement is the point: F1 picks 0.50, which admits three unsupported claims to gain one supported one. A false *unsupported* label costs an amber underline the reader can check and dismiss; a false *supported* label is the exact failure the gate exists to prevent, and it is invisible.

**Caveat worth stating plainly:** 14 labelled pairs is a small calibration set. It is enough to show the gate separates the two classes (supported mean 0.67 vs unsupported 0.481) and enough to rule out the badly wrong thresholds, but the plateau between 0.65 and 0.75 is inside the noise. First thing to do with real usage data is grow this set to ~150 pairs and re-run the sweep.

## End-to-end answer quality

Not run. This section needs a real model:

```bash
EVAL_PROVIDER=ollama make eval
```

---

### What to watch

- **recall@k dropping** — chunking or the embedding model changed.
- **claim-support rate dropping** — the answer prompt or the model changed.
- **refusal rate dropping** — the biggest one. It means the assistant started answering things the archive doesn't cover.
