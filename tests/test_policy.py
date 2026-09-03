"""Invariants of link choice — the channel that carries the entire gate effect.

M-002 showed `choose` accounts for all of the gate's measured damage, so these
are the properties that decide whether the headline number means anything.
"""
from __future__ import annotations

import random

import pytest

from humanbrowser import policy
from humanbrowser.policy import FLOOR, REVISIT_PENALTY

from conftest import element


def _freq(els, goal, *, gate, n=4000, seed=0):
    """Empirical selection frequency per element, via the real choose()."""
    rng = random.Random(seed)
    counts = [0] * len(els)
    for _ in range(n):
        picked, _, _ = policy.choose(els, goal, gate=gate, rng=rng)
        counts[els.index(picked)] += 1
    return [c / n for c in counts]


# -- the gate must be soft, never a filter (D-003) ----------------------------

def test_an_invisible_element_is_still_reachable():
    """A hard cutoff would make a buried element unfindable rather than hard to
    find, collapsing the survival curve to 0% or 100% and destroying the metric.
    Some people do read footers."""
    els = [element("Provisioning", "/prov"), element("Home", "/")]
    els[0]["visibility"] = 0.0
    els[1]["visibility"] = 1.0
    scores = policy.score_elements(els, "provisioning", gate=True)
    assert scores[0] >= FLOOR
    assert _freq(els, "provisioning", gate=True, n=3000)[0] > 0.0


def test_no_score_is_ever_zero():
    els = [element("a", "/a"), element("b", "/b")]
    for e in els:
        e["visibility"] = 0.0
    assert all(s >= FLOOR for s in policy.score_elements(els, "nothing matches", gate=True))


# -- visibility must only ever hurt -------------------------------------------

@pytest.mark.parametrize("seed", range(8))
def test_lowering_visibility_never_raises_a_score(seed):
    rng = random.Random(seed)
    els = [element(f"link {i}", f"/{i}") for i in range(6)]
    for e in els:
        e["visibility"] = rng.random()
    before = policy.score_elements(els, "link 3", gate=True)
    i = rng.randrange(len(els))
    els[i]["visibility"] *= 0.5
    after = policy.score_elements(els, "link 3", gate=True)
    assert after[i] <= before[i] + 1e-12
    assert [a for j, a in enumerate(after) if j != i] == \
           [b for j, b in enumerate(before) if j != i]


def test_a_less_visible_element_is_chosen_less_often():
    """The behavioural form of the same claim, through the real sampler."""
    els = [element("Save this search", "/save"), element("Save this search too", "/save2")]
    els[0]["visibility"] = 1.0
    els[1]["visibility"] = 0.05
    f = _freq(els, "save this search", gate=True)
    assert f[0] > f[1] * 3


# -- D-007: with no scent to weight, the gate can do nothing ------------------

def test_flat_scent_makes_the_gate_a_noop():
    """Recorded so the finding cannot be quietly lost.

    score = scent x visibility. If every scent is 0 the scores are all FLOOR,
    softmax over a flat vector is uniform, and visibility has nothing to
    modulate. This is why embedding scent (M4) blocks the M2 product case:
    do NOT try to fix that case by tuning the gate.
    """
    els = [element("Alpha", "/a"), element("Beta", "/b"), element("Gamma", "/c")]
    for e, v in zip(els, (1.0, 0.5, 0.01)):
        e["visibility"] = v
    goal = "something with no overlapping words whatsoever"
    assert all(policy.scent(goal, e) == 0.0 for e in els)
    on = _freq(els, goal, gate=True, seed=11)
    off = _freq(els, goal, gate=False, seed=11)
    assert on == pytest.approx(off, abs=1e-9)


def test_the_gate_does_bite_once_scent_varies():
    """The contrapositive, so the test above cannot be passed by breaking the gate."""
    els = [element("Shop the collection", "/shop"), element("Legal", "/legal")]
    els[0]["visibility"] = 0.02
    els[1]["visibility"] = 1.0
    off = _freq(els, "shop the collection", gate=False, seed=5)
    on = _freq(els, "shop the collection", gate=True, seed=5)
    assert on[0] < off[0] - 0.1


# -- choice is stochastic, and reproducible per visitor (D-003) ---------------

def test_same_seed_gives_the_same_choice():
    els = [element(f"link {i}", f"/{i}") for i in range(5)]
    a = policy.choose(els, "link 2", gate=False, rng=random.Random(42))[0]
    b = policy.choose(els, "link 2", gate=False, rng=random.Random(42))[0]
    assert a is b


def test_visitors_do_not_all_click_the_same_thing():
    """Deterministic choice would make the survival curve degenerate."""
    els = [element(f"link {i}", f"/{i}") for i in range(5)]
    picked = {policy.choose(els, "link", gate=False, rng=random.Random(s))[0]["name"]
              for s in range(60)}
    assert len(picked) > 1


# -- scent -------------------------------------------------------------------

def test_scent_is_bounded():
    els = [element("Shop the collection", "/shop"), element("", None)]
    for e in els:
        assert 0.0 <= policy.scent("shop the collection", e) <= 1.0


def test_scent_ignores_stopwords():
    assert policy.scent("the a of", element("the a of", "/x")) == 0.0


def test_empty_goal_has_no_scent():
    assert policy.scent("", element("anything", "/x")) == 0.0


# -- revisiting ---------------------------------------------------------------

def test_revisiting_something_is_penalised():
    els = [element("Shop", "/shop")]
    els[0]["visibility"] = 1.0
    fresh = policy.score_elements(els, "shop", gate=True)[0]
    seen = policy.score_elements(els, "shop", gate=True,
                                 visited={policy._key(els[0])})[0]
    assert seen == pytest.approx(fresh * REVISIT_PENALTY)


def test_unnoticed_reports_below_threshold_elements():
    els = [element("Loud", "/a"), element("Quiet", "/b")]
    els[0]["visibility"] = 0.9
    els[1]["visibility"] = 0.01
    assert [e["name"] for e in policy.unnoticed(els, 0.22)] == ["Quiet"]
