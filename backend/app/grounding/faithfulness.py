"""Claim-level grounding check.

The problem this solves: a model will happily write "Chesky says founder mode
means reviewing every design [3]" when chunk 3 says nothing of the sort. The
citation marker is generated text like any other token, so citations alone are
not evidence — they're a claim *about* evidence.

So after generation we split the answer into sentences and score each one
against the chunks that were actually retrieved. Two signals, combined:

  * embedding cosine against the best-matching evidence sentence — catches
    paraphrase, which is most of what a good answer is;
  * content-word overlap (precision of the claim's content words against the
    evidence) — catches the failure embeddings miss, where a sentence is
    topically on-point but has invented a specific number, name or claim.

Why not an NLI model or a second LLM pass: an LLM judge costs a second full
generation (roughly doubling latency on a 7B local model, which is the demo
path) and is itself non-deterministic, so the same answer can score differently
on two runs. That makes the number useless as a regression signal. This is
deterministic instead, which is what you want from something you're going to put
a threshold on. A cross-encoder NLI model is the right upgrade when there's
budget for it — see architecture.md.

Cost: the work is embedding every evidence sentence, so it scales with retrieved
context, not with answer length. Uncapped over k=8 full chunks that measured
~38s on a single core — bad enough to dominate the whole turn. MAX_EVIDENCE_SENTS
caps it; the cap costs nothing in practice because the sentences that support a
claim are almost always in the top few hits, which we keep in rank order.

Thresholds are calibrated against backend/eval/goldens.yaml; eval/REPORT.md
shows the confusion matrix they were picked from.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass

import numpy as np

from ..config import get_settings
from ..rag.store import Hit

# Words that carry no claim. Overlap is measured on content words only,
# otherwise "the" and "is" float every sentence over the line.
STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "so", "of", "to", "in",
    "on", "at", "for", "with", "as", "by", "from", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that", "these", "those", "you",
    "your", "i", "we", "they", "he", "she", "them", "his", "her", "their", "our",
    "do", "does", "did", "have", "has", "had", "can", "could", "will", "would",
    "should", "may", "might", "must", "not", "no", "there", "here", "what",
    "which", "who", "when", "where", "how", "why", "about", "into", "than",
    "very", "just", "really", "like", "get", "got", "one", "also", "more",
}

# Tuned against the golden set: raising this past 60 changed no verdict, and
# lowering it to 30 started dropping evidence for multi-part answers.
MAX_EVIDENCE_SENTS = 48

# Sentences keep their trailing citation markers. Splitting on `[.!?]\s+` alone
# fails on "…the product. [1] Leaders who…" because the lookahead sees "[",
# which collapsed entire answers into a single claim and made the grounding
# score meaningless. Match whole sentences instead of splitting between them.
SENTENCE_RE = re.compile(r"[^.!?\n]*[.!?]+(?:\s*\[\d+\])*|[^.!?\n]+")
CITE_RE = re.compile(r"\[(\d+)\]")

# Sentences that make no factual claim shouldn't be penalised — "Here's what the
# transcripts say:" is not a hallucination.
NON_CLAIM = re.compile(
    r"^\s*(here'?s|below|the following|in summary|to summari[sz]e|that said|"
    r"hope this helps|let me know|source[s]?:|\W*)\s*[:\-—]?\s*$",
    re.I,
)


@dataclass
class SentenceVerdict:
    text: str
    label: str  # supported | partial | unsupported | not_a_claim
    score: float
    cited: list[int]
    evidence_chunk_id: str | None
    evidence_quote: str | None


@dataclass
class GroundingReport:
    score: float           # supported / claim-bearing sentences
    supported: int
    partial: int
    unsupported: int
    total_claims: int
    took_ms: int
    sentences: list[SentenceVerdict]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["sentences"] = [asdict(s) for s in self.sentences]
        return d


def _is_claim(sent: str) -> bool:
    if NON_CLAIM.match(sent):
        return False
    if len(content_words(sent)) < 3:
        return False
    # "Here's what the transcripts say:" — a lead-in ending in a colon that
    # carries no citation is introducing evidence, not asserting anything.
    if sent.rstrip().endswith(":") and not CITE_RE.search(sent):
        return False
    return True


def split_sentences(text: str) -> list[str]:
    # Markdown bullets and headings are their own units — a bullet is a claim.
    lines = [ln.strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln:
            continue
        ln = re.sub(r"^([*\-•]|\d+\.)\s+", "", ln)
        ln = re.sub(r"^#{1,6}\s+", "", ln)
        out.extend(m.group(0).strip() for m in SENTENCE_RE.finditer(ln) if m.group(0).strip())
    return out


def content_words(s: str) -> set[str]:
    toks = re.findall(r"[a-z0-9][a-z0-9'\-]*", s.lower())
    return {t for t in toks if t not in STOP and len(t) > 2}


def _overlap(claim: str, evidence: str) -> float:
    """Fraction of the claim's content words present in the evidence.

    Precision-style rather than F1: we care whether the claim invented
    something, not whether it covered the whole chunk.
    """
    c = content_words(claim)
    if not c:
        return 1.0
    return len(c & content_words(evidence)) / len(c)


_EV_CACHE: "OrderedDict[str, np.ndarray]" = OrderedDict()
_EV_CACHE_MAX = 4096


def _embed_cached(texts: list[str], embed_fn) -> np.ndarray:
    """Evidence sentences repeat across turns because the same chunks keep
    getting retrieved. Embedding them once per process is the difference
    between the gate being free and the gate dominating the turn."""
    missing = [t for t in texts if t not in _EV_CACHE]
    if missing:
        vecs = embed_fn(missing)
        for t, v in zip(missing, vecs):
            _EV_CACHE[t] = v
            if len(_EV_CACHE) > _EV_CACHE_MAX:
                _EV_CACHE.popitem(last=False)
    return np.asarray([_EV_CACHE[t] for t in texts], dtype=np.float32)


def check(answer: str, hits: list[Hit], embed_fn=None) -> GroundingReport:
    from ..rag.embedder import embed_texts

    embed_fn = embed_fn or embed_texts
    s = get_settings()
    t0 = time.perf_counter()

    sents = split_sentences(answer)
    claims = [x for x in sents if _is_claim(x)]

    if not hits or not claims:
        return GroundingReport(
            score=0.0 if claims else 1.0,
            supported=0, partial=0, unsupported=len(claims),
            total_claims=len(claims),
            took_ms=int((time.perf_counter() - t0) * 1000),
            sentences=[
                SentenceVerdict(x, "unsupported" if _is_claim(x) else "not_a_claim", 0.0,
                                _cited(x), None, None)
                for x in sents
            ],
        )

    # Evidence granularity is the sentence, not the chunk: a 1400-char chunk
    # embedded whole washes out the one line that actually supports the claim.
    ev_texts: list[str] = []
    ev_owner: list[str] = []
    for h in hits:  # hits arrive in rank order, so truncation drops the weakest
        for e in split_sentences(h.text):
            if len(content_words(e)) >= 3:
                ev_texts.append(e)
                ev_owner.append(h.chunk_id)
        if len(ev_texts) >= MAX_EVIDENCE_SENTS:
            break
    ev_texts, ev_owner = ev_texts[:MAX_EVIDENCE_SENTS], ev_owner[:MAX_EVIDENCE_SENTS]
    if not ev_texts:
        ev_texts, ev_owner = [h.text for h in hits], [h.chunk_id for h in hits]

    ev_vecs = _embed_cached(ev_texts, embed_fn)
    cl_vecs = embed_fn(claims)
    sim = cl_vecs @ ev_vecs.T  # both L2-normalised by the embedder

    verdicts: list[SentenceVerdict] = []
    ci = 0
    supported = partial = unsupported = 0

    for sent in sents:
        if not _is_claim(sent):
            verdicts.append(SentenceVerdict(sent, "not_a_claim", 1.0, _cited(sent), None, None))
            continue

        row = sim[ci]
        ci += 1
        best = int(np.argmax(row))
        cos = float(row[best])
        ov = _overlap(sent, ev_texts[best])

        # Weighted toward cosine because paraphrase is the norm; overlap acts as
        # the veto for invented specifics.
        score = 0.65 * cos + 0.35 * ov

        if score >= s.faithfulness_supported_at:
            label = "supported"
            supported += 1
        elif score >= s.faithfulness_partial_at:
            label = "partial"
            partial += 1
        else:
            label = "unsupported"
            unsupported += 1

        verdicts.append(
            SentenceVerdict(sent, label, round(score, 3), _cited(sent),
                            ev_owner[best], ev_texts[best][:280])
        )

    n = len(claims)
    return GroundingReport(
        score=round(supported / n, 3) if n else 1.0,
        supported=supported, partial=partial, unsupported=unsupported,
        total_claims=n,
        took_ms=int((time.perf_counter() - t0) * 1000),
        sentences=verdicts,
    )


def _cited(sent: str) -> list[int]:
    return [int(x) for x in CITE_RE.findall(sent)]
