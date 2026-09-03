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


def test_out_of_range_quantiles_are_rejected(any_ruler):
    if any_ruler.counts:
        for bad in (0.0, 1.0, -0.1, 1.5):
            with pytest.raises(ValueError):
                any_ruler.budget_at(bad)
