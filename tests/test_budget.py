"""Invariants of the quit rule.

These assert properties, not numbers. A test that pins "the found rate is 70%"
is satisfied by editing the 70; a test that says "cost must not depend on the
absolute scale of promise" can only be satisfied by the design still being what
we think it is.
"""
from __future__ import annotations

import math
import random

import pytest

from humanbrowser.budget import (EffortBudget, Outcome, FRUSTRATION_K,
                                 survival_curve, summarize, wilson)


def _run(ruler, promises, **kw):
    b = EffortBudget(ruler, 0.90, **kw)
    for p in promises:
        if not b.spend(p):
            break
    return b


def _sequences(n=40, seed=0):
    rng = random.Random(seed)
    for _ in range(n):
        yield [rng.random() for _ in range(rng.randint(1, 25))]


# -- D-006: cost is scale-invariant in promise --------------------------------

@pytest.mark.parametrize("scale", [0.05, 0.5, 2.0, 20.0])
def test_cost_trajectory_is_invariant_under_uniform_scaling(ruler, scale):
    """The property that makes gating `promise` safe.

    cost_of uses (aspiration - promise)/aspiration, and aspiration is the running
    mean of the same promises, so a constant factor cancels. If this ever fails,
    the visibility gate has started secretly changing the patience burn rate and
    the channel decomposition in M-002 is invalid.
    """
    for promises in _sequences():
        if max(promises) * scale > 1.0:
            continue                      # spend() clamps to [0,1]; not a uniform scale
        plain = _run(ruler, promises)
        scaled = _run(ruler, [p * scale for p in promises])
        assert len(plain.trace) == len(scaled.trace)
        for a, b in zip(plain.trace, scaled.trace):
            assert a.cost == pytest.approx(b.cost, rel=1e-9)


def test_scaling_promise_does_not_change_when_the_visitor_quits(ruler):
    for promises in _sequences(seed=7):
        if max(promises) * 0.5 > 1.0:
            continue
        assert _run(ruler, promises).actions == _run(ruler, [p * 0.5 for p in promises]).actions


# -- cost function bounds and shape -------------------------------------------

def test_cost_is_bounded_by_frustration_k(ruler):
    for promises in _sequences(seed=1):
        for step in _run(ruler, promises).trace:
            assert 1.0 <= step.cost <= 1.0 + FRUSTRATION_K + 1e-9


def test_first_action_costs_exactly_one(ruler):
    """Nothing has been seen yet, so there is no aspiration to fall short of."""
    for promises in _sequences(seed=2):
        assert _run(ruler, promises).trace[0].cost == 1.0


def test_a_page_at_or_above_aspiration_costs_the_minimum(ruler):
    b = EffortBudget(ruler, 0.90)
    b.spend(0.5)
    assert b.cost_of(0.5) == pytest.approx(1.0)
    assert b.cost_of(0.9) == pytest.approx(1.0)
    assert b.cost_of(0.1) > 1.0


def test_cost_is_monotone_decreasing_in_promise(ruler):
    b = EffortBudget(ruler, 0.90)
    for p in (0.8, 0.4, 0.6):
        b.spend(p)
    costs = [b.cost_of(p / 20) for p in range(21)]
    assert all(a >= b_ for a, b_ in zip(costs, costs[1:]))


def test_aspiration_reflects_only_pages_already_seen(ruler):
    """cost_of must be quoted before the current page joins the running mean.

    If the current promise leaked into its own aspiration, a dead end would
    partly excuse itself and the frustration term would be damped.
    """
    b = EffortBudget(ruler, 0.90)
    b.spend(1.0)
    quoted = b.cost_of(0.0)
    b.spend(0.0)
    assert b.trace[-1].cost == pytest.approx(quoted)
    assert b.trace[-1].cost == pytest.approx(1.0 + FRUSTRATION_K)


def test_promise_is_clamped_to_unit_interval(ruler):
    b = EffortBudget(ruler, 0.90)
    b.spend(5.0)
    b.spend(-3.0)
    assert all(0.0 <= s.promise <= 1.0 for s in b.trace)


# -- budget sizing -------------------------------------------------------------

def test_budget_scales_with_persistence(ruler):
    a = EffortBudget(ruler, 0.90, persistence=0.5).budget
    b = EffortBudget(ruler, 0.90, persistence=2.0).budget
    assert b == pytest.approx(4 * a)


def test_more_persistence_never_buys_fewer_actions(ruler):
    """Monotonicity: patience must not be able to hurt."""
    for promises in _sequences(seed=3):
        acts = [_run(ruler, promises, persistence=p).actions for p in (0.5, 1.0, 2.0, 4.0)]
        assert acts == sorted(acts)


def test_unlimited_budget_never_exhausts(ruler):
    b = EffortBudget(ruler, 0.90, unlimited=True)
    assert math.isinf(b.budget)
    for _ in range(500):
        assert b.spend(0.0) is True
    assert not b.exhausted


def test_limited_budget_does_exhaust_on_dead_ends(ruler):
    b = EffortBudget(ruler, 0.90)
    b.spend(1.0)
    steps = 0
    while b.spend(0.0) and steps < 1000:
        steps += 1
    assert b.exhausted


# -- reporting -----------------------------------------------------------------

def test_survival_curve_is_monotone(ruler):
    outs = [Outcome(i % 3 == 0, 2 + i % 7, 0.0, 10.0, 1.0, 0.5,
                    "found" if i % 3 == 0 else "quit") for i in range(30)]
    rows = survival_curve(outs, max_actions=12)
    found_by = [r[2] for r in rows]
    assert found_by == sorted(found_by)                 # cumulative, never decreases
    assert all(0.0 <= r[1] <= 1.0 for r in rows)


# -- confidence intervals (D-021) ---------------------------------------------
#
# These exist because a bare found rate was read as an effect when it was noise
# (M-006). The interval is the thing that stops that, so it has to be right.

@pytest.mark.parametrize("k,n", [(0, 10), (1, 10), (5, 10), (9, 10), (10, 10),
                                 (0, 1), (1, 1), (52, 100), (300, 1000)])
def test_the_interval_lies_within_the_unit_interval(k, n):
    lo, hi = wilson(k, n)
    assert 0.0 <= lo <= hi <= 1.0


@pytest.mark.parametrize("k,n", [(1, 10), (5, 10), (9, 10), (52, 100), (41, 100)])
def test_the_interval_contains_the_observed_proportion(k, n):
    lo, hi = wilson(k, n)
    assert lo <= k / n <= hi


def test_the_interval_narrows_as_the_sample_grows():
    """The whole point: n=20 is +-22 points near p=0.5, n=300 is far tighter."""
    widths = [hi - lo for hi, lo in
              ((w[1], w[0]) for w in (wilson(n // 2, n) for n in (20, 100, 300, 1000)))]
    assert widths == sorted(widths, reverse=True)


def test_a_twenty_visitor_run_near_half_is_about_twenty_points_wide():
    """Pins the number that made M-006's phantom +35% look like a finding."""
    lo, hi = wilson(10, 20)
    assert 0.38 < hi - lo < 0.46


def test_unanimous_outcomes_do_not_produce_a_degenerate_interval():
    """0/n and n/n must still express uncertainty; a point estimate there would
    claim certainty from a small sample."""
    lo, hi = wilson(0, 10)
    assert lo == 0.0 and 0.0 < hi < 0.5
    lo, hi = wilson(10, 10)
    assert hi == 1.0 and 0.5 < lo < 1.0


def test_the_interval_is_monotone_in_successes():
    los = [wilson(k, 50)[0] for k in range(0, 51, 5)]
    his = [wilson(k, 50)[1] for k in range(0, 51, 5)]
    assert los == sorted(los) and his == sorted(his)


def test_an_empty_population_is_not_a_crash():
    assert wilson(0, 0) == (0.0, 0.0)


def test_summarize_reasons_partition_the_population(ruler):
    outs = [Outcome(True, 3, 1.0, 9.0, 1.0, 0.4, "found"),
            Outcome(False, 5, 9.0, 9.0, 1.0, 0.1, "quit"),
            Outcome(False, 40, 4.0, 9.0, 1.0, 0.1, "capped")]
    s = summarize(outs, ruler)
    assert sum(s["reasons"].values()) == s["n"]
    assert s["reasons"]["found"] == sum(o.found for o in outs)
