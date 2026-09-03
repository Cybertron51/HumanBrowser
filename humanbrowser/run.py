"""
The loop. One visitor, or a population of them.

    python3 -m humanbrowser.run http://localhost:8002/index.html \
        --goal "is there a way to be notified when an item I want is available again" \
        --target "#restock-signup" \
        --n 100 --gate --scent embedding

Add --compare to run it twice, gate off and gate on, and print the difference.
That comparison is the day-one hypothesis test: does limiting the visitor to
what they would plausibly notice change what they miss?
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from dataclasses import dataclass, field

from playwright.sync_api import sync_playwright

from . import goals, policy, scent as scent_models, visibility
from .observe import eval_stable, observe, TARGET_JS
from .budget import EffortBudget, Outcome, summarize, wilson
from .ruler import Ruler

VIEWPORT = {"width": 1440, "height": 900}
MAX_STEPS = 40

# Milliseconds waited after a navigation and after a click, for the page to
# settle. This is the dominant cost of a run: at the default it is ~0.35s of
# pure sleep per step, which is most of the wall clock. It is a real knob for
# JS-heavy sites that render after domcontentloaded, and near-pointless for a
# static fixture — see D-017.
SETTLE_MS = 200

# Population spread of patience; matches budget.Population.personas.
SPREAD = 0.35


@dataclass(frozen=True)
class Gate:
    """The visibility gate enters the loop in three independent places.

    Bundling them behind one boolean confounds three different mechanisms:

      detect  changes what counts as FOUND. Not a behaviour change at all —
              it redefines the outcome variable. Same path, different verdict.
      choose  down-weights faint elements in the softmax, so the visitor goes
              somewhere else. This is the effect the project is about.
      cost    feeds gated `promise` to budget.spend, so patience burns at a
              different rate. Note cost_of uses promise/aspiration, a ratio,
              so a uniform dimming cancels; only per-page variation leaks in.

    Run them one at a time to attribute a found-rate delta to a mechanism.
    """
    detect: bool = False
    choose: bool = False
    cost: bool = False

    @property
    def on(self) -> bool:
        return self.detect or self.choose or self.cost

    @property
    def label(self) -> str:
        if not self.on:
            return "none"
        if self.detect and self.choose and self.cost:
            return "all"
        return "+".join(c for c in ("detect", "choose", "cost") if getattr(self, c))

    @classmethod
    def all_on(cls) -> "Gate":
        return cls(True, True, True)


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)
    unnoticed: set[str] = field(default_factory=set)
    exit_url: str = ""
    click_errors: int = 0     # clicks the harness could not perform: our fault, not the visitor's


def _perceptible(feat: dict) -> bool:
    return visibility.score(feat, VIEWPORT["height"]) >= visibility.DEFAULT_THRESHOLD


_UNFETCHED = object()


def _visible_target(page, target: str, gate: bool, feat=_UNFETCHED) -> bool:
    """Present, on screen, and — if gating — actually perceptible.

    Features come from TARGET_JS, the same maths OBSERVE_JS uses on every other
    element. This previously reported a hardcoded contrast, which meant the
    detection channel silently reduced to area x depth (D-009).

    `visit()` has already fetched `feat` for the Rule 1 check, so it passes it
    in rather than paying for a second round trip. It must go through this
    function and not reimplement it: the browser tests assert on this code, and
    a second copy of the logic is exactly how D-009 happened.
    """
    if feat is _UNFETCHED:
        feat = eval_stable(page, TARGET_JS, target)
    if feat is None:
        return False
    return True if not gate else _perceptible(feat)


def visit(page, start_url: str, goal: str, target: str, budget: EffortBudget,
          *, gate: Gate, rng: random.Random,
          max_steps: int = MAX_STEPS,
          settle_ms: int = SETTLE_MS,
          scent_model=None,
          check_goal: bool = True) -> tuple[bool, float, Trace, str]:
    """Returns (found, last_promise, trace, reason).

    `reason` distinguishes the three ways a visitor can fail, which a bare
    found=False cannot: ran out of patience, hit the step cap, or found nothing
    clickable. Without it, max_steps exhaustion masquerades as giving up.
    """
    page.goto(start_url, wait_until="domcontentloaded")
    page.wait_for_timeout(settle_ms)
    trace, visited, last = Trace(), set(), 0.0

    for _ in range(max_steps):
        # Always compute real visibility; each channel decides whether to use it.
        els = observe(page, gate=True)
        for e in policy.unnoticed(els, visibility.DEFAULT_THRESHOLD):
            trace.unnoticed.add(e["name"] or e.get("href") or "?")

        feat = eval_stable(page, TARGET_JS, target)
        if feat is not None and check_goal:
            # Rule 1, against the target's real label. Only knowable once the
            # visitor has reached it, so it aborts the run rather than warning.
            goals.check(goal, feat.get("name", ""),
                        where="the target's accessible name")
        if _visible_target(page, target, gate.detect, feat=feat):
            trace.exit_url = page.url
            return True, last, trace, "found"

        el, _, _ = policy.choose(els, goal, gate=gate.choose, rng=rng, visited=visited,
                                 scent_model=scent_model)
        if el is None:
            trace.exit_url = page.url
            return False, last, trace, "dead_end"

        # Promise for the budget is scored independently of the choice channel.
        promise = max(policy.score_elements(els, goal, gate=gate.cost, visited=visited,
                                            scent_model=scent_model))
        last = promise
        trace.steps.append({
            "url": page.url, "clicked": el["name"], "promise": round(promise, 3),
            "visibility": el.get("visibility"), "spent": round(budget.spent, 2),
        })
        if not budget.spend(promise):
            trace.exit_url = page.url
            return False, promise, trace, "quit"

        visited.add(policy._key(el))
        try:
            page.click(f'[data-hb="{el["hb"]}"]', timeout=2500, no_wait_after=True)
            try:
                # Prefer waiting for the navigation this click may have started
                # over sleeping blindly; the fixed pause then covers rendering.
                page.wait_for_load_state("domcontentloaded", timeout=2500)
            except Exception:
                pass
            page.wait_for_timeout(settle_ms)
        except Exception:
            # The visitor still spent the action, so we do not refund it — but
            # this is the harness failing, not the site being a dead end, and
            # conflating the two inflates measured difficulty. Count it.
            trace.click_errors += 1

    trace.exit_url = page.url
    return False, last, trace, "capped"


def run_population(start_url: str, goal: str, target: str, *, n: int, gate: Gate,
                   quantile: float, ruler: Ruler, seed: int = 0, headless: bool = True,
                   unlimited: bool = False, max_steps: int = MAX_STEPS,
                   settle_ms: int = SETTLE_MS, scent_model=None,
                   check_goal: bool = True, browser=None):
    """Run n visitors. Pass `browser` to reuse one launch across arms."""
    if browser is not None:
        return _run_on(browser, start_url, goal, target, n=n, gate=gate,
                       quantile=quantile, ruler=ruler, seed=seed,
                       unlimited=unlimited, max_steps=max_steps, settle_ms=settle_ms,
                       scent_model=scent_model, check_goal=check_goal)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        try:
            return _run_on(b, start_url, goal, target, n=n, gate=gate,
                           quantile=quantile, ruler=ruler, seed=seed,
                           unlimited=unlimited, max_steps=max_steps, settle_ms=settle_ms,
                           scent_model=scent_model, check_goal=check_goal)
        finally:
            b.close()


def _run_on(browser, start_url, goal, target, *, n, gate, quantile, ruler, seed,
            unlimited, max_steps, settle_ms, scent_model=None, check_goal=True):
    rng_master = random.Random(seed)
    outcomes, traces = [], []
    for _ in range(n):
        persist = math.exp(rng_master.gauss(-SPREAD * SPREAD / 2, SPREAD))
        b = EffortBudget(ruler, quantile, persistence=persist, unlimited=unlimited)
        # A fresh context per visitor: cookies and localStorage must not carry
        # over, or visitor 30 is no longer a first-time visitor.
        ctx = browser.new_context(viewport=VIEWPORT)
        try:
            found, last, tr, reason = visit(ctx.new_page(), start_url, goal, target, b,
                                            gate=gate, rng=random.Random(rng_master.random()),
                                            max_steps=max_steps, settle_ms=settle_ms,
                                            scent_model=scent_model, check_goal=check_goal)
        finally:
            ctx.close()
        outcomes.append(Outcome(found, b.actions, b.spent, b.budget, persist, last, reason))
        traces.append(tr)
    return outcomes, traces


def report(outcomes, traces, ruler, gate: Gate, scent_model=None) -> str:
    s = summarize(outcomes, ruler)
    quit_urls = [t.exit_url for t, o in zip(traces, outcomes) if not o.found]
    top_exit = statistics.mode(quit_urls) if quit_urls else "-"
    never = {}
    for t in traces:
        for u in t.unnoticed:
            never[u] = never.get(u, 0) + 1
    fails = {k: v for k, v in s["reasons"].items() if k != "found"}
    lo, hi = wilson(sum(o.found for o in outcomes), s["n"])
    lines = [
        f"  scent                {getattr(scent_model, 'name', 'keyword')}",
        f"  gate                 {gate.label}",
        f"  found                {s['found_rate']:.0%}  "
        f"({sum(o.found for o in outcomes)}/{s['n']})  "
        f"95% CI [{lo:.0%}, {hi:.0%}]",
    ]
    if fails:
        lines.append("  failed because       " + ", ".join(
            f"{k} {v}" for k, v in sorted(fails.items(), key=lambda kv: -kv[1])))
    if s["median_actions_to_find"] is not None:
        pct = s["human_percentile_of_median"]
        lines.append(f"  median cost to find  {s['median_actions_to_find']:.0f} actions"
                     f"  ->  {pct:.0%} percentile of human task effort")
    if s["median_actions_before_quitting"] is not None:
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


def decompose(a, ruler):
    """Attribute the gate's found-rate delta to the channel that caused it.

    Each cell turns on exactly one channel, so the delta from baseline is that
    channel's isolated contribution. The single-channel deltas will not sum to
    the all-on delta; the residual is the interaction.
    """
    # The last two cells are a matched pair. Comparing a gated no-quit arm
    # against the patience-limited baseline changes two variables at once and
    # produces nonsense: at --max-steps 400 it made the gate look BENEFICIAL
    # (+20%), because the baseline was the only arm still giving up.
    cells = [
        ("baseline",      Gate(),                     False),
        ("detect only",   Gate(detect=True),          False),
        ("choose only",   Gate(choose=True),          False),
        ("cost only",     Gate(cost=True),            False),
        ("all channels",  Gate.all_on(),              False),
        ("none, no quit", Gate(),                     True),
        ("all, no quit",  Gate.all_on(),              True),
    ]
    rows, errors = [], 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for name, g, unlimited in cells:
                outs, trs = run_population(a.url, a.goal, a.target, n=a.n, gate=g,
                                           quantile=a.quantile, ruler=ruler,
                                           seed=a.seed, unlimited=unlimited,
                                           max_steps=a.max_steps, settle_ms=a.settle_ms,
                                           scent_model=a.scent_model,
                                           check_goal=not a.allow_goal_leak,
                                           browser=browser)
                s = summarize(outs, ruler)
                rows.append((name, s["found_rate"], s["reasons"]))
                errors += sum(t.click_errors for t in trs)
                print(f"  ran {name:<14} found {s['found_rate']:.0%}", flush=True)
        finally:
            browser.close()

    base = rows[0][1]
    print(f"\n  {'='*62}\n  CHANNEL DECOMPOSITION   n={a.n}  goal={a.goal!r}")
    print(f"  {'cell':<14} {'found':>6} {'delta':>7}   failure modes")
    for name, rate, reasons in rows:
        fails = ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])
                          if k != "found") or "-"
        d = "" if name == "baseline" else f"{rate - base:+.0%}"
        print(f"  {name:<14} {rate:>5.0%} {d:>7}   {fails}")

    full = next(r for n, r, _ in rows if n == "all channels")
    free_off, off_reasons = next((r, x) for n, r, x in rows if n == "none, no quit")
    free_on, nq_reasons = next((r, x) for n, r, x in rows if n == "all, no quit")

    # Splitting the gate's damage into the part perception causes directly and
    # the part patience amplifies. Both belong to the thesis - "hard to see"
    # causing "gives up sooner" is the mechanism, not a confound - but they are
    # different claims and the report should not merge them.
    #
    # Perception is measured with patience held OFF in BOTH arms. Comparing a
    # no-quit arm against the patience-limited baseline varies two things at
    # once and is meaningless (M-004).
    perception = free_on - free_off   # gate's effect when nobody ever gives up
    amplified = (full - base) - perception
    print(f"\n  gate damage {full - base:+.0%} splits into:")
    print(f"    perception     {perception:+.0%}  gated vs ungated, patience off in both arms")
    print(f"    patience       {amplified:+.0%}  the rest: found it eventually, gave up first")

    capped = nq_reasons.get("capped", 0) + off_reasons.get("capped", 0)
    if capped:
        # This split moved from -33/-20 to -7/-46 purely by raising the cap from
        # 40 to 120 on identical inputs (M-003). While anyone is still capped,
        # the numbers above are bounds, not measurements.
        print(f"\n    !! {capped}/{2 * a.n} unlimited-patience visitors (both arms) hit "
              f"--max-steps={a.max_steps}.")
        print("       DO NOT QUOTE THIS SPLIT. It is highly sensitive to the cap while")
        print("       anyone is still hitting it. Raise --max-steps until capped is 0.")
    if errors:
        print(f"\n  WARNING {errors} clicks failed in the harness. Those actions were "
              "charged to\n  visitors as dead ends, so difficulty here is overstated.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--goal", required=True)
    ap.add_argument("--target", required=True, help="CSS selector for the feature")
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--quantile", type=float, default=0.90)
    ap.add_argument("--gate", action="store_true", help="all channels on")
    ap.add_argument("--channels", default="", help="comma-separated: detect,choose,cost")
    ap.add_argument("--no-quit", action="store_true", help="unlimited patience")
    ap.add_argument("--scent", default="keyword", choices=["keyword", "embedding"],
                    help="keyword: word overlap. embedding: sentence-transformer cosine")
    ap.add_argument("--scent-model", default=scent_models.DEFAULT_MODEL,
                    help="sentence-transformers model id, for --scent embedding")
    ap.add_argument("--target-label", default="",
                    help="the feature's real label, checked against the goal (Rule 1)")
    ap.add_argument("--allow-goal-leak", action="store_true",
                    help="run anyway when the goal quotes the target's own words. "
                         "The result measures string matching; every report is marked.")
    ap.add_argument("--settle-ms", type=int, default=SETTLE_MS,
                    help="wait after navigation and click; dominates wall clock")
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS,
                    help="hard cap on actions per visitor, independent of patience")
    ap.add_argument("--compare", action="store_true", help="run gate off vs on")
    ap.add_argument("--decompose", action="store_true",
                    help="isolate each gate channel's contribution")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trace", action="store_true", help="print the first visitor's steps")
    a = ap.parse_args()

    ruler = Ruler.load()

    # Rule 1, first pass: the selector and any declared label are known now.
    # The target's real accessible name is checked inside visit(), when the
    # visitor first reaches it.
    if not a.allow_goal_leak:
        try:
            goals.check(a.goal, a.target, where="the target selector")
            goals.check(a.goal, a.target_label, where="--target-label")
        except goals.GoalLeak as e:
            ap.exit(2, f"\nGOAL LEAK\n{e}\n\nOverride with --allow-goal-leak if you "
                       "are deliberately reproducing an old measurement.\n")
    a.scent_model = scent_models.get(a.scent, a.scent_model)
    if a.allow_goal_leak:
        print("\n  !! --allow-goal-leak: the goal may quote the target's own label.")
        print("     Any number below measures string matching, not discoverability.")

    if a.decompose:
        return decompose(a, ruler)

    if a.channels:
        picked = {c.strip() for c in a.channels.split(",") if c.strip()}
        bad = picked - {"detect", "choose", "cost"}
        if bad:
            ap.error(f"unknown channel(s): {', '.join(sorted(bad))}")
        gate = Gate(*(c in picked for c in ("detect", "choose", "cost")))
    else:
        gate = Gate.all_on() if a.gate else Gate()

    if a.compare and (a.channels or a.gate):
        ap.error("--compare runs gate off vs all channels on; drop --gate/--channels")
    modes = [Gate(), Gate.all_on()] if a.compare else [gate]
    results = {}
    for g in modes:
        outs, trs = run_population(a.url, a.goal, a.target, n=a.n, gate=g,
                                   quantile=a.quantile, ruler=ruler, seed=a.seed,
                                   unlimited=a.no_quit, max_steps=a.max_steps,
                                   settle_ms=a.settle_ms, scent_model=a.scent_model,
                                   check_goal=not a.allow_goal_leak)
        results[g.label] = outs
        print(f"\nGOAL   {a.goal!r}\nTARGET {a.target}")
        print(report(outs, trs, ruler, g, a.scent_model))
        if a.trace:
            print("\n  first visitor:")
            for st in trs[0].steps:
                print(f"    {st['spent']:>5}  vis={st['visibility']}  "
                      f"promise={st['promise']}  clicked {st['clicked']!r}")

    if a.compare:
        off = sum(o.found for o in results["none"]) / a.n
        on = sum(o.found for o in results["all"]) / a.n
        print(f"\n  {'='*46}\n  HYPOTHESIS TEST")
        olo, ohi = wilson(sum(o.found for o in results["none"]), a.n)
        nlo, nhi = wilson(sum(o.found for o in results["all"]), a.n)
        print(f"  found rate  gate OFF {off:.0%} [{olo:.0%},{ohi:.0%}]"
              f"   gate ON {on:.0%} [{nlo:.0%},{nhi:.0%}]   delta {on-off:+.0%}")
        if olo <= nhi and nlo <= ohi:
            print("  INCONCLUSIVE - the intervals overlap. This delta is not evidence of")
            print(f"  anything; at n={a.n} it is what noise looks like. Raise --n.")
        else:
            print("  gating changes what the visitor misses.")


if __name__ == "__main__":
    main()
