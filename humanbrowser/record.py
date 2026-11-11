"""
Step capture of where a visitor gets stuck.

The population runs first, unrecorded, exactly as it always does. Then a few
representative visitors are replayed from the same seed. At each action the
replay takes a full-page screenshot and writes down what the visitor saw and
how it chose; the viewer draws the marks. Nothing is ever drawn on or scrolled
in the page (D-029).

It is a replay rather than a mode of the measurement so that nothing it does
can change what the visitor observes. And the replay has to prove it is the
same visit: every step's url, click, promise and missed lead, and the exit,
are compared with the measured trace, and a replay that diverges is deleted
rather than saved.
"""
from __future__ import annotations

import json
import math
import random
import shutil
import struct
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import policy, scent as scent_models, visibility
from .budget import EffortBudget
from .goals import GoalLeak
from .run import VIEWPORT, missed_lead, personas, visit

# Read-only: where the target is, in document pixels, without scrolling to it.
TARGET_BOX_JS = r"""
(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return [Math.round(r.x + scrollX), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)];
}
"""

# What is compared between the replay and the measured visit. Promise is the
# best score on the page, so it covers the whole observation, not just the click.
SIGNATURE_KEYS = ("url", "clicked", "href", "visibility", "promise", "missed", "digest")


class RecordDirError(ValueError):
    pass


def check_record_dir(path) -> None:
    """Refuse a directory that holds anything but a previous recording.

    `--record DIR` clears DIR/replays, so pointing it at a directory with the
    user's own files must be an error, not a deletion (D-029).
    """
    out = Path(path)
    if out.exists() and not out.is_dir():
        raise RecordDirError(f"--record {path}: not a directory")
    if out.is_dir() and any(out.iterdir()) and not (out / "run.json").is_file():
        raise RecordDirError(
            f"--record {path}: directory is not empty and has no run.json from a "
            f"previous recording; refusing to write into it. Use a new or empty directory.")


def pick_representatives(outcomes, traces, exits: int = 3) -> list[tuple[int, str]]:
    """Which visitors to record, as (index, why).

    For each of the most common pages where visitors stopped, the one whose
    effort was the median of that group: the typical way of getting stuck
    there, not the most dramatic. Plus the median-effort finder, for contrast.
    """
    def median(group):
        group = sorted(group, key=lambda i: outcomes[i].actions)
        return group[(len(group) - 1) // 2]

    failed = [i for i, o in enumerate(outcomes) if not o.found]
    picks = []
    for url, c in Counter(traces[i].exit_url for i in failed).most_common(exits):
        i = median([j for j in failed if traces[j].exit_url == url])
        picks.append((i, f"{c}/{len(outcomes)} visitors stopped at {url}"))
    finders = [i for i, o in enumerate(outcomes) if o.found]
    if finders:
        picks.append((median(finders), f"{len(finders)}/{len(outcomes)} visitors found it"))
    return picks


def _signature(trace, reason):
    return ([tuple(s.get(k) for k in SIGNATURE_KEYS) for s in trace.steps],
            trace.exit_url, reason)


def dump_traces(outcomes, traces, path) -> None:
    rows = [{
        "visitor": i, "found": o.found, "reason": o.reason, "actions": o.actions,
        "spent": round(o.spent, 2),
        "budget": None if math.isinf(o.budget) else round(o.budget, 2),
        "persistence": round(o.persistence, 4), "exit_url": t.exit_url,
        "steps": t.steps, "unnoticed": sorted(t.unnoticed),
    } for i, (o, t) in enumerate(zip(outcomes, traces))]
    Path(path).write_text(json.dumps(rows, indent=1))


def png_size(path) -> tuple[int, int]:
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


class _Capture:
    """The replay's on_step. Takes screenshots and writes down data; never
    touches the page's DOM or scroll position."""

    def __init__(self, goal, gate, scent_model, directory: Path):
        self.goal, self.gate, self.dir = goal, gate, directory
        self.model = scent_model or scent_models.DEFAULT
        self.steps: list[dict] = []

    def on_step(self, page, els, chosen, budget, decision):
        i = len(self.steps) + 1
        name = f"step-{i:02d}.png"
        page.screenshot(path=str(self.dir / name), full_page=True)
        w, h = png_size(self.dir / name)
        scents = self.model.score(self.goal, els)
        lead = missed_lead(els, self.goal, chosen, self.model) if self.gate.choose else None
        last = budget.trace[-1]
        self.steps.append({
            "i": i, "url": page.url, "screenshot": name,
            "page": {"width": w, "height": h},
            "clicked": next(k for k, e in enumerate(els) if e is chosen),
            "promise": round(last.promise, 3), "cost": round(last.cost, 3),
            "spent": round(budget.spent, 2),
            "spent_before": round(budget.trace[-2].spent if len(budget.trace) > 1 else 0.0, 4),
            "missed": None if lead is None else next(k for k, e in enumerate(els) if e is lead[0]),
            "candidates": [{
                "name": e["name"], "href": e.get("href"), "box": e["box"],
                "scent": round(sc, 4), "visibility": e.get("visibility"),
                "score": round(sc_, 4), "p": round(p, 4), "p_ungated": round(pu, 4),
                "noticed": e.get("visibility", 1.0) >= visibility.DEFAULT_THRESHOLD,
                "revisit": rv,
            } for e, sc, sc_, p, pu, rv in zip(els, scents, decision["scores"], decision["probs"],
                                                 policy.choice_probabilities(decision["ungated_scores"]),
                                                 decision["revisit"])],
        })


def record_population(start_url, goal, target, outcomes, traces, *, gate, out_dir,
                      n, quantile, ruler, seed, unlimited, max_steps, settle_ms,
                      scent_model=None, check_goal=True, exits=3):
    """Replay the representative visitors with step capture. Yields one line per pick."""
    out = Path(out_dir)
    check_record_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out / "replays", ignore_errors=True)
    dump_traces(outcomes, traces, out / "traces.json")
    people = list(personas(seed, n))
    reasons = Counter(o.reason for o in outcomes)
    (out / "run.json").write_text(json.dumps({
        "goal": goal, "start_url": start_url, "target": target, "n": n, "seed": seed,
        "gate": gate.label, "scent": getattr(scent_model, "name", "keyword"),
        "quantile": quantile, "max_steps": max_steps, "viewport": dict(VIEWPORT),
        "ruler": {"measured": bool(ruler.measured)},
        "found": sum(o.found for o in outcomes), "reasons": dict(reasons),
    }, indent=1))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for i, why in pick_representatives(outcomes, traces, exits):
                persist, visitor_seed = people[i]
                b = EffortBudget(ruler, quantile, persistence=persist, unlimited=unlimited)
                vdir = out / "replays" / f"visitor-{i:03d}"
                vdir.mkdir(parents=True)
                cap = _Capture(goal, gate, scent_model, vdir)
                ctx = browser.new_context(viewport=VIEWPORT)
                page = ctx.new_page()
                error, end = None, None
                try:
                    _, _, tr, reason = visit(page, start_url, goal, target, b, gate=gate,
                                             rng=random.Random(visitor_seed),
                                             max_steps=max_steps, settle_ms=settle_ms,
                                             scent_model=scent_model, check_goal=check_goal,
                                             on_step=cap.on_step)
                    page.screenshot(path=str(vdir / "end.png"), full_page=True)
                    w, h = png_size(vdir / "end.png")
                    end = {"url": page.url, "screenshot": "end.png",
                           "page": {"width": w, "height": h},
                           "target_box": page.evaluate(TARGET_BOX_JS, target)
                           if reason == "found" else None}
                except GoalLeak:
                    shutil.rmtree(vdir, ignore_errors=True)
                    raise                # invalidates the run, not just this replay
                except Exception as e:
                    error = e
                finally:
                    ctx.close()
                if error is not None:
                    shutil.rmtree(vdir, ignore_errors=True)
                    yield f"visitor {i}: FAILED ({type(error).__name__}: {error})"
                    continue
                if _signature(tr, reason) != _signature(traces[i], outcomes[i].reason):
                    shutil.rmtree(vdir, ignore_errors=True)
                    yield (f"visitor {i}: DISCARDED - the replay took a different path "
                           f"from the measured visit, so it is not a recording of it")
                    continue
                (vdir / "replay.json").write_text(json.dumps({
                    "visitor": i, "why": why, "found": reason == "found", "reason": reason,
                    "actions": b.actions,
                    "budget": None if math.isinf(b.budget) else round(b.budget, 2),
                    "persistence": round(persist, 4), "steps": cap.steps, "end": end,
                }, indent=1))
                yield f"{vdir}/  ({why}; {b.actions} actions)"
        finally:
            browser.close()

    from . import viewer
    build = getattr(viewer, "build", None)
    if build is not None:
        yield f"viewer: {build(out)}"
