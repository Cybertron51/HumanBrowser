"""Invariants of the visit loop, driven by the fake site in conftest.

The important one is channel independence: `detect` must change only the
verdict, never the path. If it steers the visitor, the M-002 decomposition is
measuring a mixture and the attribution is meaningless.
"""
from __future__ import annotations

import random

import pytest

from humanbrowser import visibility
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
    assert all({"url", "clicked", "promise", "visibility", "spent_before", "digest"} <= s.keys()
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


# -- the recorder's hook must be an observer, never a participant (D-026) ------

@pytest.mark.parametrize("seed", range(6))
def test_the_step_hook_does_not_change_the_visit(ruler, seed):
    from humanbrowser import policy
    plain, hooked, calls, decisions = FakePage(pages=_SITE()), FakePage(pages=_SITE()), [], []
    rng_a, rng_b = random.Random(seed), random.Random(seed)
    a = visit(plain, "/", "shop the collection", "#collection", EffortBudget(ruler, 0.90),
              gate=Gate.all_on(), rng=rng_a)
    b = EffortBudget(ruler, 0.90)
    c = visit(hooked, "/", "shop the collection", "#collection", b, gate=Gate.all_on(),
              rng=rng_b,
              on_step=lambda page, els, chosen, budget, decision: (
                  calls.append(chosen["name"]), decisions.append(decision)))
    assert hooked.clicks == plain.clicks
    assert (c[0], c[3], c[2].exit_url) == (a[0], a[3], a[2].exit_url)
    assert rng_a.getstate() == rng_b.getstate()   # computing p_ungated consumed nothing
    assert a[2].steps == c[2].steps               # incl. the observation digest
    assert len(calls) == b.actions            # once per action, including the last
    for d in decisions:
        assert sum(policy.choice_probabilities(d["ungated_scores"])) == pytest.approx(1.0)


def test_ungated_probabilities_equal_gated_ones_when_the_choice_channel_is_off(ruler):
    from humanbrowser import policy
    seen = []
    visit(FakePage(pages=_SITE()), "/", "shop the collection", "#collection",
          EffortBudget(ruler, 0.90), gate=Gate(), rng=random.Random(0),
          on_step=lambda page, els, chosen, budget, d: seen.append(d))
    assert seen and all(policy.choice_probabilities(d["scores"]) ==
                        policy.choice_probabilities(d["ungated_scores"]) for d in seen)


def test_personas_are_reproducible_and_prefix_stable():
    from humanbrowser.run import personas
    assert list(personas(7, 5)) == list(personas(7, 5))
    assert list(personas(7, 9))[:5] == list(personas(7, 5))


def test_representatives_are_the_median_of_the_commonest_exits():
    from humanbrowser.budget import Outcome
    from humanbrowser.record import pick_representatives
    from humanbrowser.run import Trace
    rows = [("/a", False, 3), ("/a", False, 9), ("/a", False, 20),
            ("/b", False, 5), ("/t", True, 2), ("/t", True, 4), ("/t", True, 30)]
    outs = [Outcome(f, n, n, 10, 1.0, 0.0, "found" if f else "quit") for _, f, n in rows]
    trs = [Trace(exit_url=u) for u, _, _ in rows]
    picks = pick_representatives(outs, trs, exits=1)
    assert [i for i, _ in picks] == [1, 5]    # median quitter at /a, median finder


# -- recording the missed lead is observation only (D-027) ---------------------

def _dim_lead_site():
    return {"/": [element("Notify me when back in stock", "/n", contrast=1.1, area=150.0, top=3000.0),
                  element("Shop the collection", "/shop"),
                  element("About", "/about")],
            "/shop": [element("Home", "/")], "/about": [element("Home", "/")],
            "/n": [element("Home", "/")]}


@pytest.mark.parametrize("seed", range(6))
def test_recording_the_missed_lead_changes_neither_path_nor_randomness(ruler, seed, monkeypatch):
    import humanbrowser.run as run

    def go():
        rng = random.Random(seed)
        page = FakePage(pages=_dim_lead_site(), target_on="/never")
        out = visit(page, "/", "notify me when in stock", "#x", EffortBudget(ruler, 0.90),
                    gate=Gate.all_on(), rng=rng)
        return page.clicks, out[3], rng.getstate(), out[2]

    clicks, reason, state, trace = go()
    monkeypatch.setattr(run, "missed_lead", lambda *a, **k: None)
    clicks0, reason0, state0, trace0 = go()
    assert (clicks, reason, state) == (clicks0, reason0, state0)
    assert all(s["missed"] is None for s in trace0.steps)
    assert any(s["missed"] for s in trace.steps)


def test_the_missed_lead_is_never_the_clicked_element_or_a_visible_one(ruler):
    page = FakePage(pages=_dim_lead_site(), target_on="/never")
    _, _, trace, _ = visit(page, "/", "notify me when in stock", "#x",
                           EffortBudget(ruler, 0.90), gate=Gate.all_on(),
                           rng=random.Random(1))
    for s in trace.steps:
        if s["missed"]:
            assert s["missed"]["name"] != s["clicked"]
            assert s["missed"]["visibility"] < visibility.DEFAULT_THRESHOLD


def test_no_missed_lead_is_recorded_when_the_choice_channel_is_off(ruler):
    """With choose off the dim link was weighed at full visibility: not missed."""
    for gate in (Gate(), Gate(detect=True), Gate(cost=True)):
        page = FakePage(pages=_dim_lead_site(), target_on="/never")
        _, _, trace, _ = visit(page, "/", "notify me when in stock", "#x",
                               EffortBudget(ruler, 0.90), gate=gate, rng=random.Random(1))
        assert trace.steps and all(s["missed"] is None for s in trace.steps), gate.label


# -- the replay must prove it saw the same page, and must not delete user files (D-029)

def test_the_signature_covers_every_candidate_not_just_the_clicked_one():
    from humanbrowser.record import _signature
    from humanbrowser.run import Trace, observation_digest
    base = [element("A", "/a"), element("B", "/b"), element("C", "/c")]
    changed = [dict(e) for e in base]
    changed[2] = dict(changed[2], visibility=0.123)         # not clicked, not the best
    step = lambda els: {"url": "/", "clicked": "A", "href": "/a", "visibility": 1.0,
                        "promise": 0.5, "missed": None, "digest": observation_digest(els)}
    t1, t2 = Trace(steps=[step(base)], exit_url="/"), Trace(steps=[step(changed)], exit_url="/")
    assert observation_digest(base) == observation_digest([dict(e) for e in base])
    assert _signature(t1, "quit") != _signature(t2, "quit")


def test_record_refuses_a_directory_that_is_not_a_previous_recording(tmp_path):
    from humanbrowser.record import RecordDirError, check_record_dir, record_population
    (tmp_path / "replays").mkdir()
    (tmp_path / "replays" / "mine.txt").write_text("keep")
    with pytest.raises(RecordDirError):
        check_record_dir(tmp_path)
    with pytest.raises(RecordDirError):
        next(record_population("u", "g", "t", [], [], gate=Gate(), out_dir=tmp_path, n=0,
                                 quantile=0.9, ruler=None, seed=0, unlimited=False,
                                 max_steps=1, settle_ms=0))
    assert (tmp_path / "replays" / "mine.txt").read_text() == "keep"


def test_record_accepts_new_empty_and_previous_recording_directories(tmp_path):
    from humanbrowser.record import check_record_dir
    check_record_dir(tmp_path / "does-not-exist-yet")
    check_record_dir(tmp_path)                                # empty
    (tmp_path / "run.json").write_text("{}")
    (tmp_path / "replays").mkdir()
    check_record_dir(tmp_path)                                # a previous recording
