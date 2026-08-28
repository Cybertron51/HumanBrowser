"""
The loop. One visitor, or a population of them.

    python3 -m humanbrowser.run http://localhost:8000/ \
        --goal "I run this same search every week, can I keep it" \
        --target "#trail-alerts button" \
        --n 25 --gate

Add --compare to run it twice, gate off and gate on, and print the difference.
That comparison is the day-one hypothesis test: does limiting the visitor to
what they would plausibly notice change what they miss?
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright

from . import policy, visibility
from .observe import observe, OBSERVE_JS
from .budget import EffortBudget, Outcome, summarize
from .ruler import Ruler

VIEWPORT = {"width": 1440, "height": 900}
MAX_STEPS = 40


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)
    unnoticed: set[str] = field(default_factory=set)
    exit_url: str = ""


def _visible_target(page, target: str, gate: bool) -> bool:
    """Present, on screen, and — if gating — actually perceptible."""
    loc = page.locator(target).first
    if loc.count() == 0:
        return False
    if not gate:
        return True
    box = loc.bounding_box()
    if not box:
        return False
    feat = page.evaluate(
        """(b) => {
             const el = document.elementFromPoint(
               Math.min(Math.max(b.x + b.w/2, 1), innerWidth-1),
               Math.min(Math.max(b.y + b.h/2, 1), innerHeight-1));
             const cs = el ? getComputedStyle(el) : null;
             return {contrast: 12, area: b.w*b.h, top: b.y + scrollY};
           }""",
        {"x": box["x"], "y": box["y"], "w": box["width"], "h": box["height"]})
    return visibility.score(feat, VIEWPORT["height"]) >= visibility.DEFAULT_THRESHOLD


def visit(page, start_url: str, goal: str, target: str, budget: EffortBudget,
          *, gate: bool, rng: random.Random) -> tuple[bool, float, Trace]:
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(150)
    trace, visited, last = Trace(), set(), 0.0

    for _ in range(MAX_STEPS):
        els = observe(page, gate=gate)
        if gate:
            for e in policy.unnoticed(els, visibility.DEFAULT_THRESHOLD):
                trace.unnoticed.add(e["name"] or e.get("href") or "?")

        if _visible_target(page, target, gate):
            trace.exit_url = page.url
            return True, last, trace

        el, promise, _ = policy.choose(els, goal, gate=gate, rng=rng, visited=visited)
        if el is None:
            break
        last = promise
        trace.steps.append({
            "url": page.url, "clicked": el["name"], "promise": round(promise, 3),
            "visibility": el.get("visibility"), "spent": round(budget.spent, 2),
        })
        if not budget.spend(promise):
            trace.exit_url = page.url
            return False, promise, trace

        visited.add(policy._key(el))
        try:
            page.click(f"text={el['name']}" if el["name"] else "body",
                       timeout=2500, no_wait_after=True)
            page.wait_for_timeout(200)
        except Exception:
            pass  # a dead click still costs the visitor an action

    trace.exit_url = page.url
    return False, last, trace


def run_population(start_url: str, goal: str, target: str, *, n: int, gate: bool,
                   quantile: float, ruler: Ruler, seed: int = 0, headless: bool = True):
    rng_master = random.Random(seed)
    outcomes, traces = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()
        for i in range(n):
            persist = 2.718 ** rng_master.gauss(-0.35 * 0.35 / 2, 0.35)
            b = EffortBudget(ruler, quantile, persistence=persist)
            found, last, tr = visit(page, start_url, goal, target, b,
                                    gate=gate, rng=random.Random(rng_master.random()))
            outcomes.append(Outcome(found, b.actions, b.spent, b.budget, persist, last))
            traces.append(tr)
        browser.close()
    return outcomes, traces


def report(outcomes, traces, ruler, gate: bool) -> str:
    s = summarize(outcomes, ruler)
    quit_urls = [t.exit_url for t, o in zip(traces, outcomes) if not o.found]
    top_exit = statistics.mode(quit_urls) if quit_urls else "-"
    never = {}
    for t in traces:
        for u in t.unnoticed:
            never[u] = never.get(u, 0) + 1
    lines = [
        f"  gate                 {'ON' if gate else 'OFF'}",
        f"  found                {s['found_rate']:.0%}  ({sum(o.found for o in outcomes)}/{s['n']})",
    ]
    if s["median_actions_to_find"]:
        pct = s["human_percentile_of_median"]
        lines.append(f"  median cost to find  {s['median_actions_to_find']:.0f} actions"
                     f"  ->  {pct:.0%} percentile of human task effort")
    if s["median_actions_before_quitting"]:
        lines.append(f"  quit before finding  {1-s['found_rate']:.0%}, "
                     f"median {s['median_actions_before_quitting']:.0f} actions in")
        lines.append(f"  most common exit     {top_exit}")
    if never:
        worst = sorted(never.items(), key=lambda kv: -kv[1])[:3]
        for name, c in worst:
            lines.append(f"  rarely noticed       {name!r} ({c}/{len(traces)} runs)")
    if not s["ruler_measured"]:
        lines.append("  ruler                PROVISIONAL (estimated, not measured)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--target", required=True, help="CSS selector for the feature")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--quantile", type=float, default=0.90)
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--compare", action="store_true", help="run gate off vs on")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trace", action="store_true", help="print the first visitor's steps")
    a = ap.parse_args()

    ruler = Ruler.load()
    modes = [False, True] if a.compare else [a.gate]
    results = {}
    for g in modes:
        outs, trs = run_population(a.url, a.goal, a.target, n=a.n, gate=g,
                                   quantile=a.quantile, ruler=ruler, seed=a.seed)
        results[g] = (outs, trs)
        print(f"\nGOAL   {a.goal!r}\nTARGET {a.target}")
        print(report(outs, trs, ruler, g))
        if a.trace:
            print("\n  first visitor:")
            for st in trs[0].steps:
                print(f"    {st['spent']:>5}  vis={st['visibility']}  "
                      f"promise={st['promise']}  clicked {st['clicked']!r}")

    if a.compare:
        off = sum(o.found for o in results[False][0]) / a.n
        on = sum(o.found for o in results[True][0]) / a.n
        print(f"\n  {'='*46}\n  HYPOTHESIS TEST")
        print(f"  found rate  gate OFF {off:.0%}   gate ON {on:.0%}   delta {on-off:+.0%}")
        print("  " + ("gating changes what the visitor misses."
                      if abs(on - off) >= 0.15 else
                      "gating barely moved the number - investigate before building M3."))


if __name__ == "__main__":
    main()
