"""Parse Lenny transcript markdown into timestamp-anchored chunks.

Source files look like:

    ---
    guest: Ada Chen Rekhi
    title: ...
    youtube_url: ...
    ---

    # Title

    Lenny (00:03:22):
    So I've heard great things...

    (00:05:54):
    ...continuation of the same speaker...

We chunk on *speaker turns* rather than a fixed character window because a
half-sentence of Lenny's question glued to the start of a guest's answer makes
the citation ("Ep X, Chesky @ 14:32") point at the wrong person. Turns are then
packed up to a target size so we're not embedding two-word interjections.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# "Brian Chesky (00:14:32):" or a bare "(00:14:32):" continuation line.
TURN_RE = re.compile(r"^(?P<speaker>[^\n(]{0,80}?)\s*\((?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\):\s*$")

# A handful of upstream files use "[00:14:32] Speaker: text" all on one line
# instead of the two-line "Speaker (ts):" / body format above.
BRACKET_TURN_RE = re.compile(
    r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<speaker>[^:\n]{0,80}?):\s*(?P<text>.*)$"
)

# A few files drop timestamps entirely: just "Speaker:" on its own line. We
# can't recover real timecodes for these, so start/end_ts fall back to 00:00 —
# citations lose the "jump to this second" precision but the episode is still
# retrievable and grounded to the right guest.
NO_TS_TURN_RE = re.compile(r"^(?P<speaker>[^\n(:]{0,80})\s*:\s*$")


@dataclass
class Turn:
    speaker: str
    ts: str
    text: str


@dataclass
class EpisodeMeta:
    slug: str
    guest: str
    title: str
    youtube_url: str | None = None
    publish_date: str | None = None
    keywords: list[str] = field(default_factory=list)
    content_hash: str = ""


@dataclass
class TranscriptChunk:
    id: str
    document_id: str
    ordinal: int
    text: str
    speakers: list[str]
    start_ts: str
    end_ts: str

    @property
    def n_tokens(self) -> int:
        # Rough. Only used for context budgeting, never for billing.
        return max(1, len(self.text) // 4)


def _front_matter(raw: str) -> tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw
    try:
        meta = yaml.safe_load(raw[3:end]) or {}
    except yaml.YAMLError:
        # A handful of upstream files have unescaped colons in `description`.
        # Losing metadata on those is better than dropping the episode.
        meta = {}
    return meta, raw[end + 4 :]


def parse_turns(body: str) -> list[Turn]:
    turns = _parse_turns_standard(body)
    if turns:
        return turns
    turns = _parse_turns_bracket(body)
    if turns:
        return turns
    return _parse_turns_no_timestamp(body)


def _parse_turns_standard(body: str) -> list[Turn]:
    turns: list[Turn] = []
    cur_speaker = ""
    pending: Turn | None = None
    buf: list[str] = []

    def flush():
        nonlocal pending, buf
        if pending is not None:
            pending.text = "\n".join(buf).strip()
            if pending.text:
                turns.append(pending)
        pending, buf = None, []

    for line in body.splitlines():
        m = TURN_RE.match(line.strip())
        if m:
            flush()
            spk = m.group("speaker").strip()
            if spk:
                cur_speaker = spk
            pending = Turn(speaker=cur_speaker or "Unknown", ts=_norm_ts(m.group("ts")), text="")
            continue
        if pending is not None:
            buf.append(line)
    flush()
    return turns


def _parse_turns_bracket(body: str) -> list[Turn]:
    turns: list[Turn] = []
    for line in body.splitlines():
        m = BRACKET_TURN_RE.match(line.strip())
        if not m:
            continue
        text = m.group("text").strip()
        if not text:
            continue
        ts = _norm_ts(m.group("ts"))
        turns.append(Turn(speaker=m.group("speaker").strip() or "Unknown", ts=ts, text=text))
    return turns


def _parse_turns_no_timestamp(body: str) -> list[Turn]:
    turns: list[Turn] = []
    cur_speaker = ""
    pending: Turn | None = None
    buf: list[str] = []

    def flush():
        nonlocal pending, buf
        if pending is not None:
            pending.text = "\n".join(buf).strip()
            if pending.text:
                turns.append(pending)
        pending, buf = None, []

    for line in body.splitlines():
        m = NO_TS_TURN_RE.match(line.strip())
        if m:
            flush()
            spk = m.group("speaker").strip()
            if spk:
                cur_speaker = spk
            pending = Turn(speaker=cur_speaker or "Unknown", ts="00:00", text="")
            continue
        if pending is not None:
            buf.append(line)
    flush()
    return turns


def _norm_ts(ts: str) -> str:
    parts = ts.split(":")
    if len(parts) == 2:
        parts = ["00", *parts]
    return ":".join(p.zfill(2) for p in parts)


def load_episode(path: Path) -> tuple[EpisodeMeta, list[Turn]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta, body = _front_matter(raw)
    slug = path.parent.name if path.name == "transcript.md" else path.stem
    em = EpisodeMeta(
        slug=slug,
        guest=str(meta.get("guest") or slug.replace("-", " ").title()),
        title=str(meta.get("title") or slug),
        youtube_url=meta.get("youtube_url"),
        publish_date=str(meta.get("publish_date")) if meta.get("publish_date") else None,
        keywords=[str(k) for k in (meta.get("keywords") or [])],
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
    return em, parse_turns(body)


def chunk_turns(
    meta: EpisodeMeta,
    turns: list[Turn],
    target_chars: int = 1400,
    overlap_turns: int = 1,
) -> list[TranscriptChunk]:
    chunks: list[TranscriptChunk] = []
    i = 0
    ordinal = 0
    while i < len(turns):
        window: list[Turn] = []
        size = 0
        j = i
        while j < len(turns) and (size < target_chars or not window):
            window.append(turns[j])
            size += len(turns[j].text)
            j += 1

        text = "\n\n".join(f"{t.speaker}: {t.text}" for t in window)
        cid = hashlib.sha1(f"{meta.slug}:{ordinal}".encode()).hexdigest()[:20]
        chunks.append(
            TranscriptChunk(
                id=cid,
                document_id=meta.slug,
                ordinal=ordinal,
                text=text,
                speakers=sorted({t.speaker for t in window}),
                start_ts=window[0].ts,
                end_ts=window[-1].ts,
            )
        )
        ordinal += 1
        # Step back a turn so an answer that straddles the boundary is retrievable
        # from either side. More overlap didn't help recall on the golden set.
        i = max(j - overlap_turns, i + 1)
    return chunks


def iter_transcript_files(root: Path):
    if not root.exists():
        return
    yield from sorted(root.glob("*/transcript.md"))
    yield from sorted(root.glob("*.md"))
