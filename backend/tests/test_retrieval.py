import pytest

from app.rag.retriever import plan_guests, retrieve, rrf_fuse
from app.rag.store import Hit


def h(cid, score=1.0):
    return Hit(cid, "doc", "text", "Guest", "Title", "00:00:00", "00:01:00", None, score)


def test_rrf_rewards_agreement_across_arms():
    dense = [h("a"), h("b"), h("c")]
    lexical = [h("c"), h("d"), h("a")]
    fused = rrf_fuse([dense, lexical], k=4)
    ids = [x.chunk_id for x in fused]
    # a and c appear in both arms, so they must outrank single-arm hits.
    assert set(ids[:2]) == {"a", "c"}
    assert fused[0].score > fused[-1].score


def test_rrf_dedupes():
    fused = rrf_fuse([[h("a"), h("a")], [h("a")]], k=5)
    assert len(fused) == 1


@pytest.mark.asyncio
async def test_retrieval_finds_the_right_guest():
    res = await retrieve("eleven star experience")
    assert res.hits
    assert res.hits[0].guest == "Brian Chesky"
    assert res.hits[0].start_ts == "00:22:10"


@pytest.mark.asyncio
async def test_planner_only_fires_on_capitalised_names():
    assert "Brian Chesky" in await plan_guests("What does Chesky say about design?")
    # "casey" lowercase is a word here, not a name — must not filter.
    assert await plan_guests("what is a casey style growth loop") == []


@pytest.mark.asyncio
async def test_planner_backs_off_when_filter_starves_results():
    # Ravi is a guest, but nothing he said mentions growth loops. The planner
    # must drop the filter rather than return an empty answer.
    res = await retrieve("Ravi growth loops compound channels")
    assert res.hits
    assert res.guests_filter == []


@pytest.mark.asyncio
async def test_empty_query_returns_something_not_an_exception():
    res = await retrieve("zzzz nonexistent topic qqqq")
    assert isinstance(res.hits, list)
