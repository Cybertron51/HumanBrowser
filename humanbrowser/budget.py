"""
The effort budget — when a simulated visitor gives up.

Two ideas, both borrowed rather than invented:

1. The budget is denominated in HUMAN ACTIONS, read off the Mind2Web effort
   distribution (see ruler.py). A visitor at quantile 0.90 will spend as much
   effort as the 90th-percentile human spends on a comparable task, no more.
   This is what lets the output be stated in percentiles instead of made-up units.

2. Not every action costs the same. Effort that seems to be paying off is cheap;
   effort on a page that looks like a dead end is expensive. This is SNIF-ACT's
   satisficing rule (Fu & Pirolli 2007): the aspiration level is the running mean
   of how promising the pages you have already seen were, and you back out when
   the current page falls below it. Here it scales cost rather than triggering a
   separate action, which keeps a single termination condition.

`promise` is whatever your policy uses to score a page in [0,1] — for a scent
model, the best link score on the page; gate it by predicted visual attention so
the agent cannot be lured by something it would never have noticed.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .ruler import Ruler

# How much more a maximally unpromising action costs than a promising one.
# 3.0 => a total dead end burns 4 actions of budget per step.
FRUSTRATION_K = 3.0
EPS = 1e-6


@dataclass
class Step:
    n: int
    promise: float
    aspiration: float
    cost: float
    spent: float


@dataclass
class EffortBudget:
    ruler: Ruler
    quantile: float = 0.90
    persistence: float = 1.0        # population spread multiplier
    frustration_k: float = FRUSTRATION_K

    unlimited: bool = False         # patience removed, for confound isolation

    spent: float = 0.0
    actions: int = 0
    _promise_sum: float = 0.0
    _promise_n: int = 0
    trace: list[Step] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.budget = (math.inf if self.unlimited
                       else self.ruler.budget_at(self.quantile) * self.persistence)

    @property
    def aspiration(self) -> float:
        """Running mean of how promising the pages seen so far looked."""
        if self._promise_n == 0:
            return 0.0
        return self._promise_sum / self._promise_n

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.budget

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget - self.spent)

    def cost_of(self, promise: float) -> float:
        """Cost of one action on a page of this promise, given prior experience."""
        asp = self.aspiration
        if asp <= EPS:
            return 1.0
        shortfall = max(0.0, asp - promise) / asp
        return 1.0 + self.frustration_k * shortfall

    def spend(self, promise: float) -> bool:
        """Take one action. Returns True if the visitor is still going."""
        promise = min(max(promise, 0.0), 1.0)
        cost = self.cost_of(promise)
        self.spent += cost
        self.actions += 1
        self._promise_sum += promise
        self._promise_n += 1
        self.trace.append(Step(self.actions, promise, self.aspiration, cost, self.spent))
        return not self.exhausted


@dataclass
class Outcome:
    found: bool
    actions: int
    spent: float
    budget: float
    persistence: float
    last_promise: float
    reason: str = "found"     # found | quit | capped | dead_end


class Population:
    """A spread of visitors. Patience is a distribution, not a setting."""

    def __init__(self, ruler: Ruler, n: int = 200, quantile: float = 0.90,
                 spread: float = 0.35, seed: int | None = 0):
        self.ruler, self.n, self.quantile, self.spread = ruler, n, quantile, spread
        self.rng = random.Random(seed)

    def personas(self):
        """persistence ~ lognormal(median 1.0). Some visitors are dogged, most aren't."""
        mu = -self.spread * self.spread / 2
        for _ in range(self.n):
            yield math.exp(self.rng.gauss(mu, self.spread))

    def run(self, session) -> list[Outcome]:
        """`session(budget) -> (found: bool, last_promise: float)`

        The reason is derived from the budget rather than defaulted, or every
        outcome would be labelled "found" and contradict `found_rate`.
        """
        out = []
        for p in self.personas():
            b = EffortBudget(self.ruler, self.quantile, persistence=p)
            found, last = session(b)
            reason = "found" if found else ("quit" if b.exhausted else "capped")
            out.append(Outcome(found, b.actions, b.spent, b.budget, p, last, reason))
        return out


def survival_curve(outcomes: list[Outcome], max_actions: int = 30):
    """Fraction still searching after k actions, and cumulative found-by-k."""
    rows = []
    for k in range(1, max_actions + 1):
        searching = sum(1 for o in outcomes if not o.found and o.actions >= k)
        found_by = sum(1 for o in outcomes if o.found and o.actions <= k)
        rows.append((k, searching / len(outcomes), found_by / len(outcomes)))
    return rows


def summarize(outcomes: list[Outcome], ruler: Ruler) -> dict:
    finders = [o for o in outcomes if o.found]
    quitters = [o for o in outcomes if not o.found]
    med = _median([o.actions for o in finders]) if finders else None
    reasons = {}
    for o in outcomes:
        reasons[o.reason] = reasons.get(o.reason, 0) + 1
    return {
        "n": len(outcomes),
        "found_rate": len(finders) / len(outcomes),
        "median_actions_to_find": med,
        "human_percentile_of_median": (ruler.percentile_of(med)
                                      if med is not None else None),
        "median_actions_before_quitting": _median([o.actions for o in quitters]) if quitters else None,
        "reasons": reasons,
        "ruler_measured": ruler.measured,
    }


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion (Wilson score).

    Every found rate this project reports is k successes out of n visitors, and
    n is usually small enough that the interval is wide — at n=20 near 50% it
    spans about +-22 points. A bare percentage invites reading noise as effect,
    which is exactly what happened in M-006. Wilson rather than the normal
    approximation because it stays sane near 0 and 1.
    """
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def _median(xs):
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 else (s[m - 1] + s[m]) / 2
