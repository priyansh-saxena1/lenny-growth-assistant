"""Grounding gate.

These are the tests that matter most: the gate is the product claim. If it
labels an invented statistic as supported, the badge in the UI is a lie.
"""
from app.grounding.faithfulness import check, content_words, split_sentences
from app.rag.store import Hit

from conftest import CORPUS, fake_embed


def hits():
    return [
        Hit(cid, "doc", text, guest, title, ts, ts, None, 1.0)
        for cid, guest, title, ts, text in CORPUS
    ]


def test_paraphrase_counts_as_supported():
    answer = "Chesky cut 200 projects down to 20 and personally signs off on each one. [1]"
    r = check(answer, hits(), embed_fn=fake_embed)
    assert r.sentences[0].label == "supported"
    assert r.score == 1.0


def test_invented_statistic_is_not_supported():
    # Nothing in the corpus says anything about 47% or revenue.
    answer = "Airbnb grew revenue 47% after adopting founder mode. [1]"
    r = check(answer, hits(), embed_fn=fake_embed)
    assert r.sentences[0].label in ("unsupported", "partial")
    assert r.score < 1.0


def test_citation_marker_alone_does_not_confer_support():
    """The core failure this gate exists for."""
    answer = "Slack was founded as a gaming company called Tiny Speck. [2]"
    r = check(answer, hits(), embed_fn=fake_embed)
    assert r.sentences[0].label == "unsupported"
    assert r.sentences[0].cited == [2]  # the model did cite; it just cited wrongly


def test_connective_sentences_are_not_penalised():
    answer = "Here's what the transcripts say:\nRetention curves that flatten signal product market fit. [3]"
    r = check(answer, hits(), embed_fn=fake_embed)
    labels = {s.text[:20]: s.label for s in r.sentences}
    assert any(v == "not_a_claim" for v in labels.values())
    assert r.total_claims == 1


def test_no_evidence_means_zero_not_crash():
    r = check("Some confident claim about growth.", [], embed_fn=fake_embed)
    assert r.score == 0.0
    assert r.unsupported == 1


def test_evidence_quote_is_returned_for_ui():
    r = check("Growth loops compound where funnels leak. [4]", hits(), embed_fn=fake_embed)
    assert r.sentences[0].evidence_chunk_id == "lenny-1"
    assert r.sentences[0].evidence_quote


def test_bullets_are_scored_as_claims():
    answer = "- Retention curves that flatten are the clearest signal. [3]\n- Airbnb tripled headcount in 2019. [1]"
    r = check(answer, hits(), embed_fn=fake_embed)
    assert r.total_claims == 2


def test_content_words_drops_stopwords():
    assert content_words("the and of a") == set()
    assert "retention" in content_words("The retention curve")


def test_split_handles_markdown_headings():
    assert len(split_sentences("## Heading\n\nOne. Two.")) == 3


def test_citation_markers_do_not_swallow_sentence_boundaries():
    """Regression: `...product. [1] Leaders...` used to parse as ONE sentence.

    The splitter's lookahead expected a letter after the period and saw "[",
    so a whole multi-claim answer collapsed into a single claim and the
    grounding score stopped meaning anything. Caught by the smoke test, not by
    the unit tests, which is why this one exists.
    """
    answer = ("Founder mode means staying close to the product. [1] "
              "Leaders who delegate too early lose the thread. [2] "
              "Airbnb grew revenue 47 percent because of it. [3]")
    sents = split_sentences(answer)
    assert len(sents) == 3
    assert sents[0].endswith("[1]")

    r = check(answer, hits(), embed_fn=fake_embed)
    assert r.total_claims == 3
    # The invented revenue figure must be isolated, not averaged away.
    assert r.sentences[-1].label in ("unsupported", "partial")


def test_evidence_cache_returns_identical_scores():
    answer = "Growth loops compound where funnels leak. [1]"
    a = check(answer, hits(), embed_fn=fake_embed)
    b = check(answer, hits(), embed_fn=fake_embed)
    assert a.score == b.score
    assert a.sentences[0].score == b.sentences[0].score
