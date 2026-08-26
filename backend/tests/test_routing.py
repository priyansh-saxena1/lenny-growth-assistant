import pytest

from app.agent.router import classify, rule_route
from app.llm.echo import EchoProvider


@pytest.mark.parametrize("q,expected", [
    ("What is founder mode?", "answer"),
    ("How do growth loops compound?", "answer"),
    ("Does retention flatten for good products?", "answer"),
    ("Write a Ship 30 essay about pricing", "essay"),
    ("write me a blog post on hiring PMs", "essay"),
    ("Make me an HTML landing page for our launch", "artifact"),
    ("give me a markdown checklist for user interviews", "artifact"),
])
def test_rules_cover_the_common_cases_without_a_model(q, expected):
    r = rule_route(q)
    assert r is not None and r.name == expected
    assert r.decided_by == "rule"


def test_html_intent_picks_html_kind():
    assert rule_route("build a styled web page about PMF").args["kind"] == "html"
    assert rule_route("make me a markdown doc about PMF").args["kind"] == "markdown"


def test_question_about_writing_is_not_an_essay_request():
    """The failure that motivated rule-first routing: a question that merely
    mentions writing must still route to `answer`."""
    r = rule_route("What do guests say about writing product specs?")
    assert r.name == "answer"


@pytest.mark.asyncio
async def test_ambiguous_input_falls_back_to_answer_on_bad_json():
    from app.llm.base import LLMResult

    class Garbage(EchoProvider):
        async def complete(self, *a, **k):
            return LLMResult("I think maybe essay?", "x", "echo")

    r = await classify("founder mode", Garbage())
    assert r.name == "answer"


@pytest.mark.asyncio
async def test_classifier_error_defaults_to_answer():
    class Broken(EchoProvider):
        async def complete(self, *a, **k):
            raise RuntimeError("model exploded")

    r = await classify("founder mode", Broken())
    assert r.name == "answer" and r.decided_by == "default"
