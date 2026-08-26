"""Ship 30 for 30 essay skill.

The brief asks for the writing principles to be *encoded in the skill* rather
than stuffed into a prompt. So the prompt is generated from skill.yaml, and —
more importantly — the output is scored against the same YAML programmatically.
The score is not decoration: dimensions that fall below their floor generate a
specific revision instruction, and the essay goes back through the model once.

Scoring in code rather than with an LLM judge is the same call as in the
faithfulness gate: word count, heading cadence, bold density and citation
coverage are all *measurable*, and a measurable check gives the same answer
twice. Reserving the model for the parts that need judgment is the whole point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from ..llm.base import LLMProvider
from ..logging_setup import get_logger
from ..rag.store import Hit

log = get_logger(__name__)

SKILL_PATH = Path(__file__).parent / "ship30" / "skill.yaml"


@lru_cache
def load_skill() -> dict:
    return yaml.safe_load(SKILL_PATH.read_text(encoding="utf-8"))


@dataclass
class DimensionScore:
    name: str
    score: float
    weight: float
    detail: str
    below_floor: bool


@dataclass
class Scorecard:
    total: float
    dimensions: list[DimensionScore]
    word_count: int
    skill_version: int
    revised: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total": round(self.total, 3),
            "word_count": self.word_count,
            "skill_version": self.skill_version,
            "revised": self.revised,
            "notes": self.notes,
            "dimensions": [
                {"name": d.name, "score": round(d.score, 3), "weight": d.weight,
                 "detail": d.detail, "below_floor": d.below_floor}
                for d in self.dimensions
            ],
        }


# --------------------------------------------------------------------------
# text measurements
# --------------------------------------------------------------------------

BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
HEADING_RE = re.compile(r"^#{2,4}\s+(.+)$", re.M)
BULLET_RE = re.compile(r"^\s*([*\-]|\d+\.)\s+\S", re.M)
CITE_RE = re.compile(r"\[(\d+)\]")
NUMBER_RE = re.compile(r"(?<![\w\[])\d+(?:[.,]\d+)?%?(?![\w\]])")
PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})?\b")


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9'\-]+", text)


def _body_paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", text):
        b = block.strip()
        if not b or b.startswith("#") or BULLET_RE.match(b):
            continue
        out.append(b)
    return out


def _taper(value: float, target: float, tolerance: float) -> float:
    """1.0 inside the band, decaying linearly to 0 at 2x the tolerance."""
    lo, hi = target * (1 - tolerance), target * (1 + tolerance)
    if lo <= value <= hi:
        return 1.0
    dist = (lo - value) if value < lo else (value - hi)
    return max(0.0, 1.0 - dist / (target * tolerance))


def score_essay(text: str) -> Scorecard:
    sk = load_skill()
    r = sk["rubric"]
    words = _words(text)
    wc = len(words)
    dims: list[DimensionScore] = []

    def add(name, score, detail):
        cfg = r[name]
        score = max(0.0, min(1.0, score))
        dims.append(DimensionScore(name, score, cfg["weight"], detail,
                                   score < cfg["floor"]))

    # word count -----------------------------------------------------------
    cfg = r["word_count"]
    add("word_count", _taper(wc, cfg["target"], cfg["tolerance"]),
        f"{wc} words (target {cfg['target']} ±{int(cfg['tolerance']*100)}%)")

    # hook -----------------------------------------------------------------
    cfg = r["hook"]
    # Drop heading lines *before* joining — joining first turns the whole
    # opening into one line and `^#.*` then eats all of it.
    body_lines = [ln for ln in text.strip().split("\n")[:8] if not ln.lstrip().startswith("#")]
    opening = " ".join(ln.strip() for ln in body_lines if ln.strip())
    first_two = " ".join(re.split(r"(?<=[.!?])\s+", opening)[:2])
    low = first_two.lower()
    banned = next((b for b in cfg["banned_openers"] if low.startswith(b)), None)
    signals = 0
    if NUMBER_RE.search(first_two):
        signals += 1
    if '"' in first_two or "\u201c" in first_two:
        signals += 1
    if any(m in low for m in cfg["contrarian_markers"]):
        signals += 1
    hook_score = 0.0 if banned else min(1.0, 0.45 + 0.28 * signals)
    add("hook", hook_score,
        f"banned opener '{banned}'" if banned else f"{signals} hook signal(s) in first two sentences")

    # skimmability ---------------------------------------------------------
    cfg = r["skimmable"]
    headings = HEADING_RE.findall(text)
    bullets = len(BULLET_RE.findall(text))
    bolded = sum(len(_words(b)) for b in BOLD_RE.findall(text))
    density = bolded / wc if wc else 0.0
    paras = _body_paragraphs(text)
    mean_para = sum(len(_words(p)) for p in paras) / len(paras) if paras else 0
    lo, hi = cfg["bold_density_range"]
    parts = [
        min(1.0, len(headings) / cfg["min_headings"]),
        min(1.0, bullets / cfg["min_bullet_lines"]),
        1.0 if lo <= density <= hi else 0.35,
        1.0 if mean_para <= cfg["max_mean_paragraph_words"] else
        max(0.0, 1 - (mean_para - cfg["max_mean_paragraph_words"]) / 60),
    ]
    add("skimmable", sum(parts) / len(parts),
        f"{len(headings)} headings, {bullets} bullets, bold density {density:.3f}, "
        f"mean paragraph {mean_para:.0f}w")

    # specificity ----------------------------------------------------------
    cfg = r["specificity"]
    # Strip citation markers first or every [3] counts as a number.
    plain = CITE_RE.sub(" ", text)
    nums = len(NUMBER_RE.findall(plain))
    propers = len(set(PROPER_RE.findall(plain)))
    per100 = propers / (wc / 100) if wc else 0
    add("specificity",
        0.5 * min(1.0, per100 / cfg["min_proper_nouns_per_100w"])
        + 0.5 * min(1.0, nums / cfg["min_numbers"]),
        f"{propers} distinct proper nouns ({per100:.1f}/100w), {nums} numbers")

    # takeaway -------------------------------------------------------------
    cfg = r["takeaway"]
    tail = text[-1400:].lower()
    marker = next((m for m in cfg["required_section_markers"] if m in tail), None)
    # An imperative in the closing paragraph counts even without a labelled section.
    imperative = bool(re.search(r"\n\s*(pick|start|write|run|ask|block|ship|cut|try|do)\b",
                                text[-700:], re.I))
    add("takeaway", 1.0 if marker else (0.6 if imperative else 0.0),
        f"closing marker '{marker}'" if marker else
        ("imperative close, no labelled takeaway" if imperative else "no takeaway found"))

    # grounding ------------------------------------------------------------
    cfg = r["grounded"]
    distinct = len(set(CITE_RE.findall(text)))
    cited_paras = sum(1 for p in paras if CITE_RE.search(p))
    ratio = cited_paras / len(paras) if paras else 0.0
    add("grounded",
        0.5 * min(1.0, distinct / cfg["min_distinct_citations"])
        + 0.5 * min(1.0, ratio / cfg["min_cited_paragraph_ratio"]),
        f"{distinct} distinct sources, {ratio:.0%} of paragraphs cited")

    total = sum(d.score * d.weight for d in dims)
    return Scorecard(total=total, dimensions=dims, word_count=wc,
                     skill_version=sk["version"])


# --------------------------------------------------------------------------
# prompting
# --------------------------------------------------------------------------

def build_system_prompt() -> str:
    sk = load_skill()
    lines = [
        "You write atomic essays in the Ship 30 for 30 style, grounded strictly in "
        "the transcript passages provided.",
        "",
        "Principles:",
    ]
    for p in sk["principles"]:
        g = " ".join(p["guidance"].split())
        lines.append(f"- {p['label']}: {g}")
    r = sk["rubric"]
    lines += [
        "",
        f"Length: about {r['word_count']['target']} words.",
        f"Structure: at least {r['skimmable']['min_headings']} '##' subheads and "
        f"{r['skimmable']['min_bullet_lines']} bullet lines. Bold sparingly.",
        f"Cite at least {r['grounded']['min_distinct_citations']} distinct sources "
        "using [n] markers matching the numbered passages.",
        "",
        "Never invent a statistic, company or quote. If the passages don't support "
        "a point, leave the point out. Output Markdown only — no preamble, no "
        "explanation of what you wrote.",
    ]
    return "\n".join(lines)


REVISION_HINTS = {
    "word_count": "Adjust the length to about {target} words — currently {wc}. "
                  "Expand thin sections with material from the passages, or cut repetition.",
    "hook": "Rewrite the opening two sentences. Lead with a specific number, a "
            "direct quote from a passage, or a claim that contradicts common advice. "
            "Do not open with a definition or a rhetorical question.",
    "skimmable": "Restructure for skimming: add '##' subheads roughly every 200 words, "
                 "break paragraphs to 1-3 sentences, and convert any list of three or "
                 "more things into bullets.",
    "specificity": "Replace generic phrasing with specifics from the passages — name the "
                   "person, the company and the number every time one is available.",
    "takeaway": "Add a short closing section that tells the reader exactly what to do "
                "next, phrased as an action rather than a summary.",
    "grounded": "Add [n] citations to the uncited paragraphs and draw on at least three "
                "different passages. Delete any claim you cannot attribute.",
}


async def write_essay(
    topic: str,
    hits: list[Hit],
    provider: LLMProvider,
    angle: str | None = None,
) -> tuple[str, Scorecard]:
    from ..agent.tools import format_sources

    sk = load_skill()
    sources = format_sources(hits)
    ask = f"Topic: {topic}"
    if angle:
        ask += f"\nAngle to take: {angle}"

    user = f"{ask}\n\nTranscript passages:\n\n{sources}"
    res = await provider.complete(
        [{"role": "user", "content": user}],
        system=build_system_prompt(),
        max_tokens=4096,
        temperature=0.6,
    )
    essay = _strip_fences(res.text)
    card = score_essay(essay)

    rev = sk["revision"]
    weak = [d for d in card.dimensions if d.below_floor]
    if weak and card.total < rev["min_total_to_skip"] and rev["max_passes"] > 0:
        hints = []
        for d in sorted(weak, key=lambda x: x.score)[:3]:
            h = REVISION_HINTS.get(d.name, "")
            hints.append("- " + h.format(target=sk["rubric"]["word_count"]["target"],
                                         wc=card.word_count))
        log.info("ship30.revising", total=round(card.total, 3),
                 weak=[d.name for d in weak])
        res2 = await provider.complete(
            [{"role": "user", "content": user},
             {"role": "assistant", "content": essay},
             {"role": "user", "content":
              "Revise the essay. Fix only these, keep everything else intact:\n"
              + "\n".join(hints) + "\n\nOutput the full revised Markdown essay only."}],
            system=build_system_prompt(),
            max_tokens=4096,
            temperature=0.5,
        )
        revised = _strip_fences(res2.text)
        card2 = score_essay(revised)
        # Keep the revision only if it actually helped — a local model sometimes
        # "fixes" the hook by deleting half the essay.
        if card2.total > card.total:
            card2.revised = True
            card2.notes.append(
                f"revised for {', '.join(d.name for d in weak)}: "
                f"{card.total:.2f} -> {card2.total:.2f}"
            )
            return revised, card2
        card.notes.append(f"revision discarded ({card2.total:.2f} <= {card.total:.2f})")

    return essay, card


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", t, re.S)
    return m.group(1).strip() if m else t
