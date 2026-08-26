"""Chunker tests.

Weighted toward the parsing cases that actually broke: bare continuation
timestamps (which silently reattributed a guest's words to Lenny), and the
two upstream files with no parseable turns at all.
"""
from pathlib import Path

from app.rag.chunker import chunk_turns, load_episode, parse_turns

SAMPLE = """---
guest: Ada Chen Rekhi
title: Knowing when to leave
youtube_url: https://www.youtube.com/watch?v=xyz
---

# Knowing when to leave

Lenny (00:03:22):
So tell me about curiosity loops.

Ada Chen Rekhi (00:04:08):
A curiosity loop is going to a bunch of people with a structured question.

(00:05:54):
The lightweight version is just asking the same question repeatedly.

Lenny (00:07:45):
What makes a question good?
"""


def test_continuation_timestamp_keeps_speaker():
    turns = parse_turns(SAMPLE)
    assert [t.speaker for t in turns] == [
        "Lenny", "Ada Chen Rekhi", "Ada Chen Rekhi", "Lenny"
    ]
    # This is the whole point of the parser: 00:05:54 is Ada, not Lenny.
    assert turns[2].ts == "00:05:54"


def test_mm_ss_timestamps_normalise():
    turns = parse_turns("Guest (4:08):\nhello there\n")
    assert turns[0].ts == "00:04:08"


def test_chunks_carry_span_and_speakers(tmp_path: Path):
    p = tmp_path / "transcript.md"
    p.write_text(SAMPLE, encoding="utf-8")
    meta, turns = load_episode(p)
    chunks = chunk_turns(meta, turns, target_chars=80, overlap_turns=1)

    assert meta.guest == "Ada Chen Rekhi"
    assert len(chunks) > 1
    for c in chunks:
        assert c.start_ts <= c.end_ts
        assert c.speakers
    assert chunks[0].id != chunks[1].id


def test_overlap_actually_overlaps(tmp_path: Path):
    p = tmp_path / "transcript.md"
    p.write_text(SAMPLE, encoding="utf-8")
    meta, turns = load_episode(p)
    chunks = chunk_turns(meta, turns, target_chars=60, overlap_turns=1)
    assert chunks[1].start_ts <= chunks[0].end_ts


def test_hash_is_stable(tmp_path: Path):
    p = tmp_path / "transcript.md"
    p.write_text(SAMPLE, encoding="utf-8")
    a, _ = load_episode(p)
    b, _ = load_episode(p)
    assert a.content_hash == b.content_hash


def test_unparseable_file_yields_no_turns():
    # Two upstream episodes look like this. Ingest must skip and report them,
    # not crash the run.
    assert parse_turns("just a wall of prose with no speaker markers") == []
