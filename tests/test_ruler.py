"""Invariants of the effort ruler.

The ruler is what lets the output be a percentile against recorded human effort
instead of an invented score (D-002). These hold for both the provisional
log-normal and a measured empirical ruler, so they survive M5.
"""
from __future__ import annotations

import pytest

from humanbrowser.ruler import QUANTILES, Ruler, provisional


@pytest.fixture(params=["provisional", "measured"])
def any_ruler(request):
    if request.param == "provisional":
        return provisional()
    counts = sorted([1, 2, 2, 3, 3, 3, 4, 5, 5, 6, 7, 8, 9, 12, 15, 22] * 8)
    return Ruler(counts=counts, quantiles={}, mean=sum(counts) / len(counts),
                 n=len(counts), provenance="test", measured=True)


def test_budget_is_monotone_in_quantile(any_ruler):
    """A more patient visitor must never be given a smaller budget."""
    budgets = [any_ruler.budget_at(q) for q in QUANTILES]
    assert budgets == sorted(budgets)


def test_percentile_is_monotone_in_actions(any_ruler):
    pcts = [any_ruler.percentile_of(a) for a in range(1, 40)]
    assert pcts == sorted(pcts)


def test_percentile_stays_in_the_unit_interval(any_ruler):
    assert all(0.0 <= any_ruler.percentile_of(a) <= 1.0 for a in range(0, 200, 3))


def test_budget_and_percentile_round_trip(any_ruler):
    """percentile_of(budget_at(q)) should land back near q."""
    for q in (0.25, 0.50, 0.75, 0.90):
        assert any_ruler.percentile_of(any_ruler.budget_at(q)) == pytest.approx(q, abs=0.08)


def test_budgets_are_positive(any_ruler):
    assert all(any_ruler.budget_at(q) > 0 for q in QUANTILES)


def test_provisional_ruler_is_flagged_as_unmeasured():
    """Reports key off this to print `ruler: PROVISIONAL` (D-001). If it ever
    silently reports True, every percentile we publish becomes unlabelled."""
    r = provisional()
    assert r.measured is False
    assert "PROVISIONAL" in r.provenance


def test_shipped_ruler_declares_its_provenance():
    r = Ruler.load()
    assert r.provenance
    assert r.measured in (True, False)
    if not r.measured:
        assert "PROVISIONAL" in r.provenance.upper()
    else:
        assert r.counts and len(r.counts) == r.n
        assert "CC BY 4.0" in r.provenance and "Mind2Web" in r.provenance
        assert "2,350" in r.provenance          # says how much of the dataset it is not


def test_provisional_ruler_does_not_claim_a_sample():
    assert provisional().n == 0
    assert provisional().counts is None


def test_out_of_range_quantiles_are_rejected(any_ruler):
    if any_ruler.counts:
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError):
                any_ruler.budget_at(bad)


# -- ties and steps in a measured ruler of integer counts (D-031) --------------

def _tied():
    counts = sorted([2] * 37 + [3] * 115 + [4] * 145 + [5] * 118 + [6] * 107 + [9] * 60 + [14] * 19)
    return Ruler(counts=counts, quantiles={}, mean=sum(counts) / len(counts),
                 n=len(counts), provenance="test", measured=True)


QS = [i / 100 for i in range(1, 100)]


def test_budget_is_an_observed_count_never_an_interpolation():
    r = _tied()
    assert {r.budget_at(q) for q in QS} <= set(r.counts)


def test_budget_is_monotone_across_the_whole_quantile_range():
    r = _tied()
    b = [r.budget_at(q) for q in QS]
    assert b == sorted(b)


def test_percentile_of_a_budget_never_exceeds_its_quantile():
    """Ties count as "not fewer", so the percentile of the budget can fall short
    of q but never overshoot it."""
    r = _tied()
    assert all(r.percentile_of(r.budget_at(q)) <= q for q in QS)


def test_one_more_action_than_the_budget_reaches_the_quantile():
    """And the shortfall is exactly the tied mass: counting ties as fewer gets
    back to q, within one task."""
    r = _tied()
    assert all(r.percentile_of(r.budget_at(q) + 1) >= q - 1 / r.n for q in QS)


def test_percentile_is_zero_below_the_fastest_task_and_one_above_the_slowest():
    r = _tied()
    assert r.percentile_of(min(r.counts)) == 0.0
    assert r.percentile_of(0) == 0.0
    assert r.percentile_of(max(r.counts) + 1) == 1.0


def test_a_tied_value_counts_only_the_tasks_strictly_below_it():
    r = _tied()
    below = sum(1 for c in r.counts if c < 4)
    assert r.percentile_of(4) == pytest.approx(below / r.n)
    assert r.percentile_of(4) == r.percentile_of(3.5 + 0.4999)   # same step, not interpolated


# -- the build CLI ------------------------------------------------------------

def test_build_cli_writes_only_where_told(tmp_path, monkeypatch):
    import humanbrowser.ruler as ruler_mod
    fake = _tied()
    monkeypatch.setattr(ruler_mod, "build", lambda split="train": fake)
    monkeypatch.setattr(ruler_mod, "DEFAULT_PATH", str(tmp_path / "default.json"))
    out = tmp_path / "scratch" / "r.json"
    assert ruler_mod.main(["build", "--out", str(out)]) == 0
    assert Ruler.load(str(out)).counts == fake.counts
    assert not (tmp_path / "default.json").exists()
