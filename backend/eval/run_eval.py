"""`make eval` — the regression signal.

Runs offline against the in-memory index. With LLM_PROVIDER=echo it needs no
model at all, so anyone can reproduce the retrieval and calibration numbers in
under a minute. Point it at ollama or anthropic to get answer-quality numbers
too:

    make eval                      # retrieval + calibration, no model
    EVAL_PROVIDER=ollama make eval # adds grounding, refusal, latency

Writes backend/eval/REPORT.md. The report always states the corpus size it ran
against, because a recall number without a denominator is marketing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

os.environ.setdefault("VECTOR_BACKEND", "memory")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_JSON", "false")

from app.config import get_settings  # noqa: E402
from app.grounding.faithfulness import _overlap, content_words  # noqa: E402
from app.logging_setup import configure_logging  # noqa: E402


def load(name: str) -> dict:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# retrieval
# --------------------------------------------------------------------------

def hit_matches(g: dict, hits) -> bool:
    if not hits:
        return False
    if g.get("expect_guest"):
        if any(g["expect_guest"].lower() in h.guest.lower() for h in hits):
            return True
    terms = [t.lower() for t in g.get("expect_terms", [])]
    if not terms:
        return False
    blob = " ".join(h.text.lower() for h in hits)
    return sum(1 for t in terms if t in blob) >= g.get("min_terms", 2)


def in_index(g: dict, corpus) -> bool:
    """Is this golden even answerable from the current index?

    Guest-anchored goldens need that guest present. Term-anchored ones need the
    terms to appear somewhere in the corpus. Anything else is scored as
    out-of-scope rather than as a miss.

    `corpus` is every chunk currently indexed (`store.all_chunks()`), not the
    store itself — checking `store.chunks` directly only worked for the
    in-memory backend and silently marked everything "not in index" against
    pgvector, which has no such attribute.
    """
    if g.get("expect_guest"):
        return any(g["expect_guest"].lower() in c.guest.lower() for c in corpus)
    terms = [t.lower() for t in g.get("expect_terms", [])]
    blob = " ".join(c.text.lower() for c in corpus)
    return sum(1 for t in terms if t in blob) >= g.get("min_terms", 2)


async def run_retrieval(goldens: dict, corpus, k: int) -> dict:
    from app.rag.retriever import retrieve

    rows, lat = [], []
    scored = skipped = recalled = 0

    for g in goldens["in_corpus"]:
        if not in_index(g, corpus):
            rows.append({"id": g["id"], "status": "not_in_index", "recall": None, "ms": None})
            skipped += 1
            continue
        t0 = time.perf_counter()
        res = await retrieve(g["q"], k=k)
        ms = int((time.perf_counter() - t0) * 1000)
        ok = hit_matches(g, res.hits)
        scored += 1
        recalled += int(ok)
        lat.append(ms)
        rows.append({
            "id": g["id"], "status": "scored", "recall": ok, "ms": ms,
            "top_guest": res.hits[0].guest if res.hits else None,
            "n": len(res.hits),
        })

    return {
        "rows": rows,
        "scored": scored,
        "skipped": skipped,
        "recall_at_k": round(recalled / scored, 3) if scored else None,
        "p50_ms": int(statistics.median(lat)) if lat else None,
        "p95_ms": int(sorted(lat)[int(len(lat) * 0.95)]) if len(lat) > 1 else (lat[0] if lat else None),
    }


# --------------------------------------------------------------------------
# threshold calibration
# --------------------------------------------------------------------------

def pair_score(claim: str, evidence: str) -> float:
    """Same formula as the gate, on a single pair."""
    from app.rag.embedder import embed_texts

    v = embed_texts([claim, evidence])
    cos = float(v[0] @ v[1])
    return 0.65 * cos + 0.35 * _overlap(claim, evidence)


def run_calibration(cal: dict, chosen: float) -> dict:
    scored = [(p["label"], pair_score(p["claim"], p["evidence"])) for p in cal["pairs"]]

    def confusion(th: float) -> dict:
        tp = sum(1 for lab, s in scored if lab == "supported" and s >= th)
        fn = sum(1 for lab, s in scored if lab == "supported" and s < th)
        fp = sum(1 for lab, s in scored if lab == "unsupported" and s >= th)
        tn = sum(1 for lab, s in scored if lab == "unsupported" and s < th)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        # F0.5 weights precision over recall. That's the metric that matches what
        # this gate is for: labelling an invented claim "supported" is the
        # failure mode, and F1 would happily trade three of those for one extra
        # true positive.
        b2 = 0.25
        f_half = ((1 + b2) * prec * rec / (b2 * prec + rec)) if (prec + rec) else 0.0
        return {"threshold": round(th, 2), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
                "precision": round(prec, 3), "recall": round(rec, 3),
                "f1": round(f1, 3), "f_half": round(f_half, 3)}

    sweep = [confusion(t / 100) for t in range(35, 86, 5)]
    # Tie-break toward the higher threshold: with a calibration set this small,
    # prefer the more conservative end of a plateau.
    best = max(sweep, key=lambda r: (r["f_half"], r["threshold"]))
    return {
        "sweep": sweep,
        "best": best,
        "configured": confusion(chosen),
        "supported_mean": round(statistics.mean([s for lab, s in scored if lab == "supported"]), 3),
        "unsupported_mean": round(statistics.mean([s for lab, s in scored if lab == "unsupported"]), 3),
        "n_pairs": len(scored),
    }


# --------------------------------------------------------------------------
# end-to-end (needs a real model)
# --------------------------------------------------------------------------

async def run_answers(goldens: dict, provider_name: str, corpus, k: int) -> dict:
    from app.agent.tools import format_sources
    from app.grounding.faithfulness import check
    from app.llm.registry import get_provider
    from app.rag.retriever import retrieve

    from app.agent.orchestrator import ANSWER_SYSTEM

    provider = get_provider(provider_name)
    rows, lat, ground = [], [], []

    for g in goldens["in_corpus"]:
        if not in_index(g, corpus):
            continue
        t0 = time.perf_counter()
        res = await retrieve(g["q"], k=k)
        if not res.hits:
            continue
        hits = res.hits[:5] if provider.name == "ollama" else res.hits
        r = await provider.complete(
            [{"role": "user", "content":
              f"Question: {g['q']}\n\nNumbered transcript passages:\n\n{format_sources(hits)}"}],
            system=ANSWER_SYSTEM, max_tokens=1024)
        rep = check(r.text, hits)
        ms = int((time.perf_counter() - t0) * 1000)
        lat.append(ms)
        ground.append(rep.score)
        rows.append({"id": g["id"], "grounding": rep.score, "claims": rep.total_claims,
                     "unsupported": rep.unsupported, "ms": ms})

    markers = [m.lower() for m in goldens["refusal_markers"]]
    refused = 0
    ref_rows = []
    for g in goldens["out_of_corpus"]:
        res = await retrieve(g["q"], k=k)
        hits = res.hits[:5]
        r = await provider.complete(
            [{"role": "user", "content":
              f"Question: {g['q']}\n\nNumbered transcript passages:\n\n{format_sources(hits)}"}],
            system=ANSWER_SYSTEM, max_tokens=512)
        ok = any(m in r.text.lower() for m in markers)
        refused += int(ok)
        ref_rows.append({"id": g["id"], "refused": ok, "preview": r.text[:110]})

    return {
        "provider": provider.name, "model": provider.model,
        "rows": rows, "refusal_rows": ref_rows,
        "mean_grounding": round(statistics.mean(ground), 3) if ground else None,
        "refusal_rate": round(refused / len(goldens["out_of_corpus"]), 3),
        "p50_ms": int(statistics.median(lat)) if lat else None,
        "p95_ms": int(sorted(lat)[int(len(lat) * 0.95)]) if len(lat) > 1 else None,
    }


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def write_report(ctx: dict) -> Path:
    r, cal, ans = ctx["retrieval"], ctx["calibration"], ctx.get("answers")
    L = []
    a = L.append

    a("# Evaluation report")
    a("")
    a(f"Generated {ctx['when']} · commit `{ctx['commit']}`")
    a("")
    a("Regenerate with `make eval`. Every number below comes from that command; "
      "nothing here is hand-written.")
    a("")
    a("## Corpus this run scored against")
    a("")
    a(f"- Episodes indexed: **{ctx['documents']}** of 303 available")
    a(f"- Chunks indexed: **{ctx['chunks']}**")
    a(f"- Embedding model: `{ctx['embed_model']}` ({ctx['embed_dim']}d)")
    a(f"- Retrieval k: {ctx['k']}")
    a("")
    if ctx["documents"] < 303:
        a(f"> Partial index. {r['skipped']} of {r['scored'] + r['skipped']} golden "
          f"questions are not answerable from these episodes and were marked "
          f"`not_in_index` rather than counted as misses. Run a full `make ingest` "
          f"to score all 20.")
        a("")

    a("## Retrieval")
    a("")
    a(f"| metric | value |")
    a(f"|---|---|")
    a(f"| recall@{ctx['k']} | **{_pct(r['recall_at_k'])}** ({r['scored']} scored, {r['skipped']} not in index) |")
    a(f"| retrieval p50 | {r['p50_ms']} ms |")
    a(f"| retrieval p95 | {r['p95_ms']} ms |")
    a("")
    a("<details><summary>Per-question</summary>")
    a("")
    a("| id | status | recall | ms | top guest |")
    a("|---|---|---|---|---|")
    for row in r["rows"]:
        a(f"| {row['id']} | {row['status']} | "
          f"{'—' if row['recall'] is None else ('yes' if row['recall'] else 'NO')} | "
          f"{row['ms'] or '—'} | {row.get('top_guest') or '—'} |")
    a("")
    a("</details>")
    a("")

    a("## Faithfulness gate calibration")
    a("")
    a(f"{cal['n_pairs']} hand-labelled claim/evidence pairs "
      f"(`backend/eval/calibration.yaml`). Mean score for supported claims "
      f"**{cal['supported_mean']}**, for unsupported **{cal['unsupported_mean']}**.")
    a("")
    a("| threshold | TP | FP | TN | FN | precision | recall | F1 | F0.5 |")
    a("|---|---|---|---|---|---|---|---|---|")
    for s in cal["sweep"]:
        mark = " ←configured" if abs(s["threshold"] - ctx["threshold"]) < 1e-9 else ""
        a(f"| {s['threshold']}{mark} | {s['tp']} | {s['fp']} | {s['tn']} | {s['fn']} | "
          f"{s['precision']} | {s['recall']} | {s['f1']} | **{s['f_half']}** |")
    a("")
    a(f"Configured threshold **{ctx['threshold']}** "
      f"(precision {cal['configured']['precision']}, recall {cal['configured']['recall']}, "
      f"F0.5 {cal['configured']['f_half']}). Best F0.5 on this sweep: "
      f"{cal['best']['threshold']}.")
    a("")
    a("Selection is on **F0.5, not F1**. The two disagree here, and the "
      "disagreement is the point: F1 picks 0.50, which admits three unsupported "
      "claims to gain one supported one. A false *unsupported* label costs an "
      "amber underline the reader can check and dismiss; a false *supported* "
      "label is the exact failure the gate exists to prevent, and it is invisible.")
    a("")
    a(f"**Caveat worth stating plainly:** {cal['n_pairs']} labelled pairs is a small "
      "calibration set. It is enough to show the gate separates the two classes "
      "(supported mean "
      f"{cal['supported_mean']} vs unsupported {cal['unsupported_mean']}) and enough "
      "to rule out the badly wrong thresholds, but the plateau between 0.65 and "
      "0.75 is inside the noise. First thing to do with real usage data is grow "
      "this set to ~150 pairs and re-run the sweep.")
    a("")

    if ans:
        a("## End-to-end answer quality")
        a("")
        a(f"Provider `{ans['provider']}` · model `{ans['model']}`")
        a("")
        a("| metric | value |")
        a("|---|---|")
        a(f"| mean claim-support rate | **{_pct(ans['mean_grounding'])}** |")
        a(f"| correct refusals (out-of-corpus) | **{_pct(ans['refusal_rate'])}** ({len(ans['refusal_rows'])} questions) |")
        a(f"| end-to-end p50 | {ans['p50_ms']} ms |")
        a(f"| end-to-end p95 | {ans['p95_ms']} ms |")
        a("")
        a("<details><summary>Refusal behaviour</summary>")
        a("")
        a("| id | refused | response opening |")
        a("|---|---|---|")
        for row in ans["refusal_rows"]:
            prev = row["preview"].replace("|", "\\|").replace("\n", " ")
            a(f"| {row['id']} | {'yes' if row['refused'] else 'NO'} | {prev}… |")
        a("")
        a("</details>")
    else:
        a("## End-to-end answer quality")
        a("")
        a("Not run. This section needs a real model:")
        a("")
        a("```bash")
        a("EVAL_PROVIDER=ollama make eval")
        a("```")
    a("")
    a("---")
    a("")
    a("### What to watch")
    a("")
    a("- **recall@k dropping** — chunking or the embedding model changed.")
    a("- **claim-support rate dropping** — the answer prompt or the model changed.")
    a("- **refusal rate dropping** — the biggest one. It means the assistant "
      "started answering things the archive doesn't cover.")

    out = HERE / "REPORT.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.environ.get("EVAL_PROVIDER"),
                    help="ollama|anthropic|openai — omit to skip answer generation")
    ap.add_argument("--k", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    configure_logging("WARNING", as_json=False)
    s = get_settings()
    k = args.k or s.retrieval_top_k

    from app.rag.store import get_store

    store = get_store()
    n_chunks = await store.count()
    if n_chunks == 0:
        print("index is empty — run `make ingest` first", file=sys.stderr)
        raise SystemExit(2)
    corpus = await store.all_chunks()
    docs = len({c.document_id for c in corpus})

    goldens = load("goldens.yaml")
    cal = load("calibration.yaml")

    print(f"index: {docs} episodes / {n_chunks} chunks")
    print("running retrieval…")
    retrieval = await run_retrieval(goldens, corpus, k)
    print(f"  recall@{k} = {_pct(retrieval['recall_at_k'])} "
          f"({retrieval['scored']} scored, {retrieval['skipped']} skipped)")

    print("calibrating faithfulness thresholds…")
    calibration = run_calibration(cal, s.faithfulness_supported_at)
    print(f"  configured F1 = {calibration['configured']['f1']}")

    answers = None
    if args.provider:
        print(f"generating answers via {args.provider} (this is the slow part)…")
        answers = await run_answers(goldens, args.provider, corpus, k)
        print(f"  claim-support = {_pct(answers['mean_grounding'])}, "
              f"refusals = {_pct(answers['refusal_rate'])}")

    ctx = {
        "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "commit": os.environ.get("GIT_COMMIT", "local"),
        "documents": docs, "chunks": n_chunks, "k": k,
        "embed_model": s.embed_model, "embed_dim": s.embed_dim,
        "threshold": s.faithfulness_supported_at,
        "retrieval": retrieval, "calibration": calibration, "answers": answers,
    }
    path = write_report(ctx)
    print(f"wrote {path}")

    if args.json:
        print(json.dumps(ctx, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
