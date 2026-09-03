"""Invariants of the visit loop, driven by the fake site in conftest.

The important one is channel independence: `detect` must change only the
verdict, never the path. If it steers the visitor, the M-002 decomposition is
measuring a mixture and the attribution is meaningless.
"""
from __future__ import annotations

import random

import pytest

from humanbrowser.budget import EffortBudget
from humanbrowser.run import Gate, MAX_STEPS, visit

from conftest import FakePage, element


def _visit(page, ruler, goal="shop the collection", target="#collection",
           gate=None, seed=0, **budget_kw):
    b = EffortBudget(ruler, 0.90, **budget_kw)
    return visit(page, "/", goal, target, b, gate=gate or Gate(), rng=random.Random(seed))


# -- channel independence -----------------------------------------------------

@pytest.mark.parametrize("seed", range(6))
def test_detect_gating_never_redirects_the_visitor(ruler, seed):
    """Detection changes what counts as found. It must not change what is clicked.

    The ungated run stops as soon as the target exists; the detect-gated run may
    keep going. So the ungated click sequence must be a PREFIX of the gated one —
    same decisions, just a different stopping point.
    """
    plain = FakePage(pages=_SITE(), target_on="/shop",
                     target_feat={"contrast": 1.05, "area": 300.0, "top": 4000.0})
    gated = FakePage(pages=_SITE(), target_on="/shop",
                     target_feat={"contrast": 1.05, "area": 300.0, "top": 4000.0})
    _visit(plain, ruler, gate=Gate(), seed=seed, unlimited=True)
    _visit(gated, ruler, gate=Gate(detect=True), seed=seed, unlimited=True)
    assert gated.clicks[:len(plain.clicks)] == plain.clicks


def test_an_imperceptible_target_is_not_found_when_detect_is_on(ruler):
    """Tiny, near-invisible, far below the fold: nobody sees this."""
    page = FakePage(pages=_SITE(), target_on="/shop",
                    target_feat={"contrast": 1.02, "area": 120.0, "top": 9000.0})
    found, _, _, _ = _visit(page, ruler, gate=Gate(detect=True), unlimited=True)
    assert found is False


def test_a_prominent_target_is_found_whether_or_not_detect_is_on(ruler):
    feat = {"contrast": 12.0, "area": 20000.0, "top": 80.0}
    for gate in (Gate(), Gate(detect=True)):
        page = FakePage(pages=_SITE(), target_on="/shop", target_feat=feat)
        found, _, _, _ = _visit(page, ruler, gate=gate, unlimited=True)
        assert found is True, gate.label


# -- exit reasons partition the failure modes (D-011) -------------------------

def test_reaching_the_target_reports_found(ruler, two_page_site):
    found, _, _, reason = _visit(two_page_site, ruler, unlimited=True)
    assert (found, reason) == (True, "found")


def test_running_out_of_patience_reports_quit(ruler):
    page = FakePage(pages=_SITE(), target_on="/never")
    found, _, _, reason = _visit(page, ruler, persistence=0.01)
    assert (found, reason) == (False, "quit")


def test_running_out_of_steps_reports_capped(ruler):
    """Unlimited patience, unreachable target: the cap is the only way out."""
    page = FakePage(pages=_SITE(), target_on="/never")
    found, _, trace, reason = _visit(page, ruler, unlimited=True)
    assert (found, reason) == (False, "capped")
    assert len(trace.steps) == MAX_STEPS


def test_a_page_with_nothing_to_click_reports_dead_end(ruler):
    page = FakePage(pages={"/": []}, target_on="/never")
    found, _, _, reason = _visit(page, ruler, unlimited=True)
    assert (found, reason) == (False, "dead_end")


def test_quit_cannot_be_reported_when_patience_is_unlimited(ruler):
    for seed in range(5):
        page = FakePage(pages=_SITE(), target_on="/never")
        _, _, _, reason = _visit(page, ruler, seed=seed, unlimited=True)
        assert reason != "quit"


# -- the trace is the audit trail --------------------------------------------

def test_unnoticed_elements_are_recorded(ruler):
    """"Never considered" is a report line, and it is often the finding."""
    page = FakePage(
        pages={"/": [element("Loud", "/", contrast=12.0, area=20000.0, top=50.0),
                     element("Provisioning", "/", contrast=1.4, area=200.0, top=6000.0)]},
        target_on="/never")
    _, _, trace, _ = _visit(page, ruler, unlimited=True)
    assert "Provisioning" in trace.unnoticed
    assert "Loud" not in trace.unnoticed


def test_every_step_is_traced(ruler):
    page = FakePage(pages=_SITE(), target_on="/never")
    _, _, trace, _ = _visit(page, ruler, unlimited=True)
    assert len(trace.steps) == MAX_STEPS
    assert all({"url", "clicked", "promise", "visibility", "spent"} <= s.keys()
               for s in trace.steps)


def test_exit_url_is_always_recorded(ruler, two_page_site):
    _, _, trace, _ = _visit(two_page_site, ruler, unlimited=True)
    assert trace.exit_url


# -- Gate bookkeeping ---------------------------------------------------------

def test_gate_labels_are_stable():
    assert Gate().label == "none"
    assert Gate.all_on().label == "all"
    assert Gate(choose=True).label == "choose"
    assert Gate(detect=True, cost=True).label == "detect+cost"


def test_gate_on_is_false_only_when_every_channel_is_off():
    assert Gate().on is False
    assert all(g.on for g in (Gate(detect=True), Gate(choose=True), Gate(cost=True)))


def _SITE():
    return {
        "/": [element("Shop the collection", "/shop"),
              element("About", "/about", contrast=2.0, area=900.0, top=2400.0)],
        "/shop": [element("Back", "/"), element("Packs", "/packs")],
        "/about": [element("Back", "/")],
        "/packs": [element("Back", "/")],
    }


# -- surviving a navigation that lands mid-evaluate (D-023) -------------------

class _FlakyPage:
    """Raises Playwright's context-destroyed error for the first `fails` calls."""

    def __init__(self, fails, value="ok"):
        self.fails, self.calls, self.value, self.waits = fails, 0, value, 0

    def evaluate(self, js, arg=None):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("Page.evaluate: Execution context was destroyed, "
                               "most likely because of a navigation")
        return self.value

    def wait_for_timeout(self, ms):
        self.waits += 1


def test_eval_stable_retries_a_destroyed_context():
    from humanbrowser.observe import eval_stable
    p = _FlakyPage(fails=2)
    assert eval_stable(p, "js") == "ok"
    assert p.calls == 3 and p.waits == 2


def test_eval_stable_gives_up_eventually():
    from humanbrowser.observe import eval_stable
    p = _FlakyPage(fails=99)
    with pytest.raises(RuntimeError, match="Execution context was destroyed"):
        eval_stable(p, "js", retries=2)
    assert p.calls == 3


def test_eval_stable_does_not_swallow_other_errors():
    """A real bug must not be retried into silence."""
    from humanbrowser.observe import eval_stable

    class Broken:
        calls = 0
        def evaluate(self, js, arg=None):
            Broken.calls += 1
            raise RuntimeError("ReferenceError: contrastOf is not defined")
        def wait_for_timeout(self, ms): pass

    with pytest.raises(RuntimeError, match="ReferenceError"):
        eval_stable(Broken(), "js")
    assert Broken.calls == 1


def test_eval_stable_passes_the_argument_through():
    from humanbrowser.observe import eval_stable

    class Echo:
        def evaluate(self, js, arg=None): return ("js", arg)
        def wait_for_timeout(self, ms): pass

    assert eval_stable(Echo(), "js", "#sel") == ("js", "#sel")
