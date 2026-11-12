"""The tests a fake page cannot provide.

D-009 was a hardcoded constant inside a JS string. `FakePage` returns canned
features and never executes that string, so no amount of unit testing could see
it. These run a real engine against real HTML.

    pytest -m browser          # just these
    pytest -m "not browser"    # skip them
"""
from __future__ import annotations

import pytest

from humanbrowser import visibility
from humanbrowser.observe import TARGET_JS, observe
from humanbrowser.run import VIEWPORT, _visible_target

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport=VIEWPORT)
    pg = ctx.new_page()
    yield pg
    ctx.close()


def _load(page, css, text="Shop the collection"):
    page.set_content(f"""
      <body style="margin:0;background:#ffffff">
        <a id="cta" href="/shop" style="display:block;width:420px;height:64px;{css}">{text}</a>
        <a id="other" href="/x" style="color:#111">Elsewhere</a>
      </body>""")


# -- D-009: the detection channel must actually read contrast -----------------

def test_a_low_contrast_target_fails_the_gate(page):
    """Large and above the fold, so area and depth both pass. Only contrast can
    reject it — which is exactly what the hardcoded value used to prevent."""
    _load(page, "color:#f2f2f2;background:#ffffff")
    assert _visible_target(page, "#cta", False) is True      # it is present
    assert _visible_target(page, "#cta", True) is False      # but nobody sees it


def test_a_high_contrast_target_passes_the_gate(page):
    _load(page, "color:#000000;background:#ffffff")
    assert _visible_target(page, "#cta", True) is True


def test_contrast_is_what_separates_those_two_cases(page):
    """Pin the mechanism, not just the outcome: identical geometry, different ink."""
    _load(page, "color:#f2f2f2;background:#ffffff")
    faint = page.evaluate(TARGET_JS, "#cta")
    _load(page, "color:#000000;background:#ffffff")
    bold = page.evaluate(TARGET_JS, "#cta")
    assert faint["area"] == bold["area"] and faint["top"] == bold["top"]
    assert faint["contrast"] < 2.0 < bold["contrast"]


def test_target_probe_and_observe_agree_on_contrast(page):
    """The two JS paths must not drift apart again.

    They were separately maintained copies of the same maths, which is how one
    of them ended up returning a constant. They now share FEATURE_HELPERS_JS;
    this asserts they still produce the same answer for the same element.
    """
    for css in ("color:#f2f2f2;background:#ffffff",
                "color:#000000;background:#ffffff",
                "color:#777777;background:#eeeeee"):
        _load(page, css)
        probe = page.evaluate(TARGET_JS, "#cta")
        seen = next(e for e in observe(page) if e["name"] == "Shop the collection")
        assert probe["contrast"] == pytest.approx(seen["contrast"], rel=1e-9)
        assert probe["area"] == pytest.approx(seen["area"], rel=1e-9)


# -- target presence ----------------------------------------------------------

def test_a_missing_target_is_never_found(page):
    _load(page, "color:#000")
    for gate in (True, False):
        assert _visible_target(page, "#nope", gate) is False


def test_a_display_none_target_is_never_found(page):
    _load(page, "color:#000;display:none")
    for gate in (True, False):
        assert _visible_target(page, "#cta", gate) is False


# -- click handles ------------------------------------------------------------

def test_data_hb_handles_are_unique_and_clickable(page):
    """Two links with identical text: clicking by text picked whichever came
    first, or raised in strict mode. The stamped handle disambiguates."""
    page.set_content("""
      <body style="margin:0">
        <a id="one" href="#one" style="display:block;color:#000">Save</a>
        <a id="two" href="#two" style="display:block;color:#000">Save</a>
      </body>""")
    els = observe(page)
    handles = [e["hb"] for e in els]
    assert len(handles) == len(set(handles))
    second = next(e for e in els if e["hb"] == 1)
    page.click(f'[data-hb="{second["hb"]}"]')
    assert page.url.endswith("#two")


def test_observe_reports_geometry_in_document_coordinates(page):
    """Below-fold elements must stay reachable with a depth penalty, not be
    dropped — dropping them made buried features score 0% either way (D-005)."""
    page.set_content("""
      <body style="margin:0">
        <div style="height:3000px"></div>
        <a id="deep" href="/deep" style="color:#000">Provisioning</a>
      </body>""")
    els = observe(page)
    deep = next(e for e in els if e["name"] == "Provisioning")
    assert deep["top"] > VIEWPORT["height"]
    assert deep["inView"] is False
    assert deep["visibility"] < visibility.DEFAULT_THRESHOLD


# -- D-029: the recorder's capture step must leave the page exactly as it was -

def test_the_capture_step_leaves_the_page_unchanged(page, tmp_path):
    from humanbrowser import policy
    from humanbrowser.budget import EffortBudget
    from humanbrowser.record import _Capture
    from humanbrowser.ruler import provisional
    from humanbrowser.run import Gate

    page.set_content("""<!doctype html>
      <body style="margin:0;background:#fff;font-family:Arial">
        <a href="/a" style="display:block;width:400px;height:60px;color:#000">Top</a>
        <div style="height:240px"></div>
        <a href="/n" style="display:block;width:400px;height:40px;color:#000">Near</a>
        <div style="height:4600px"></div>
        <a href="/b" style="font-size:10px;color:#999">Buried</a>
      </body>""")
    page.evaluate("() => window.scrollTo(0, 120)")
    page.wait_for_timeout(100)      # let the first frame lay out before measuring
    before = observe(page)
    seen = {e["name"]: e for e in before}
    assert set(seen) == {"Top", "Near", "Buried"}
    assert seen["Near"]["inView"] is True          # in the viewport at scrollY 120
    assert seen["Top"]["inView"] is False and seen["Buried"]["inView"] is False
    assert seen["Buried"]["top"] > 4500
    dom = page.evaluate("() => document.documentElement.outerHTML")
    scroll = page.evaluate("() => [scrollX, scrollY]")
    assert scroll == [0, 120]

    budget = EffortBudget(provisional(), 0.90)
    budget.spend(0.5)
    scores = policy.score_elements(before, "anything", gate=True)
    cap = _Capture("anything", Gate.all_on(), None, tmp_path)
    cap.on_step(page, before, seen["Near"], budget, {
        "scores": scores, "probs": policy.choice_probabilities(scores),
        "ungated_scores": scores, "revisit": [False] * len(before)})

    assert page.evaluate("() => [scrollX, scrollY]") == scroll
    assert page.evaluate("() => document.documentElement.outerHTML") == dom
    assert observe(page) == before
    assert cap.steps[0]["page"]["height"] > 4900      # it really captured the whole page
