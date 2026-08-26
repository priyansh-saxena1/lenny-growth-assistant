"""Ship 30 rubric scorer.

The scorer is what makes this a skill rather than a prompt, so it needs to
actually discriminate. Each test pins one dimension.
"""
from app.skills.ship30 import build_system_prompt, load_skill, score_essay

GOOD = """# Stop Shipping Roadmap Confetti

Brian Chesky cut 200 projects to 20 at Airbnb. [1] That is not a productivity
tip, it is a statement about what leadership costs.

## The confetti problem

Most teams ship 40 small things a quarter and call it momentum.

- Nobody remembers any of them
- None of them move retention
- Every one of them costs a review cycle
- The roadmap becomes a list, not an argument

**Volume is the enemy of coherence.** [1]

## What Chesky actually did

He reviews every detail weekly and personally signs off. [1] The 11 star
exercise pushes past incremental thinking on purpose. [2]

## Where the evidence points

Ravi Mehta argues flat week 8 retention is the clearest signal you have
something real. [3] Casey Winters makes the loop version of the same point:
loops compound where funnels leak. [4]

## The takeaway

Pick the 3 things on your roadmap that would still matter in 12 months. Cut
the other 37 this week.
"""

BAD = """In today's world, product management is very important and there are
many things to consider when thinking about strategy and growth in general.
Teams should try to be effective and efficient and focus on the right things
in order to achieve their goals over time and deliver value to customers."""


def test_good_essay_outscores_bad_one():
    assert score_essay(GOOD).total > score_essay(BAD).total + 0.3


def test_banned_opener_zeroes_the_hook():
    card = score_essay(BAD)
    hook = next(d for d in card.dimensions if d.name == "hook")
    assert hook.score == 0.0
    assert hook.below_floor


def test_hook_rewards_a_number_in_the_opening():
    hook = next(d for d in score_essay(GOOD).dimensions if d.name == "hook")
    assert hook.score > 0.6


def test_grounding_dimension_tracks_distinct_citations():
    g = next(d for d in score_essay(GOOD).dimensions if d.name == "grounded")
    assert g.score > 0.7
    stripped = GOOD.replace("[1]", "").replace("[2]", "").replace("[3]", "").replace("[4]", "")
    g2 = next(d for d in score_essay(stripped).dimensions if d.name == "grounded")
    assert g2.score == 0.0


def test_citation_markers_are_not_counted_as_numbers():
    # [1][2][3][4] must not inflate the specificity score.
    only_cites = "Some claim. [1] Another claim. [2] A third. [3] A fourth. [4]"
    spec = next(d for d in score_essay(only_cites).dimensions if d.name == "specificity")
    assert spec.score < 0.6


def test_word_count_tapers_outside_the_band():
    target = load_skill()["rubric"]["word_count"]["target"]
    on_target = " ".join(["word"] * target)
    way_short = " ".join(["word"] * 200)
    a = next(d for d in score_essay(on_target).dimensions if d.name == "word_count")
    b = next(d for d in score_essay(way_short).dimensions if d.name == "word_count")
    assert a.score == 1.0
    assert b.score < 0.3


def test_takeaway_detected_from_section_marker():
    t = next(d for d in score_essay(GOOD).dimensions if d.name == "takeaway")
    assert t.score == 1.0


def test_weights_sum_to_one():
    total = sum(d["weight"] for d in load_skill()["rubric"].values())
    assert abs(total - 1.0) < 1e-9


def test_system_prompt_is_generated_from_the_yaml():
    sk = load_skill()
    prompt = build_system_prompt()
    for p in sk["principles"]:
        assert p["label"] in prompt
    assert str(sk["rubric"]["word_count"]["target"]) in prompt
