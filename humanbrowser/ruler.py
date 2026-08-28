"""
Human effort reference distribution — the ruler the quit threshold is measured against.

The whole metric rests on one idea: people don't abandon at some absolute step
count, they abandon when a task is costing notably more than tasks like it
normally cost. So we need to know what "normally" is, in real human actions, on
real websites.

Mind2Web (NeurIPS 2023) is that reference: 2,350 tasks, 137 websites, 31
domains, each with the complete human action sequence recorded via Playwright.
`len(action_reprs)` for a task is the number of actions a human actually took.

IMPORTANT — survivorship: every Mind2Web task was completed and verified. There
are no abandonments in it. So it calibrates EFFORT UNDER GOAL PURSUIT, never
patience directly. We derive a quit threshold from a high quantile of the effort
distribution, which is a modelling choice, documented as such in the report.

Its annotators were also paid and instructed, i.e. more motivated than an idle
visitor, so the distribution is an UPPER BOUND on real-world patience. Difficulty
scores built on it understate the problem, which is the safe direction.

Usage:
    python -m humanbrowser.ruler build     # needs network + `pip install datasets`
    python -m humanbrowser.ruler show
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_left
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, os.pardir, "data", "effort_ruler.json")

QUANTILES = [0.10, 0.25, 0.50, 0.75, 0.80, 0.90, 0.95, 0.99]

# Published Mind2Web statistic (NeurIPS 2023, Deng et al., Table 1).
MIND2WEB_MEAN_ACTIONS = 7.3
# Shape assumption for the provisional ruler only. Task-completion effort is
# right-skewed and bounded below at 1, so log-normal is the conventional choice.
# sigma is NOT measured — it is a placeholder. Replace it by running `build`.
PROVISIONAL_SIGMA = 0.55


@dataclass
class Ruler:
    """Maps between an action count and its percentile among human task effort."""

    counts: list[int] | None          # sorted observed action counts, if measured
    quantiles: dict[str, float]       # quantile -> action count
    mean: float
    n: int
    provenance: str
    measured: bool

    # -- lookups -------------------------------------------------------------

    def budget_at(self, quantile: float) -> float:
        """Action budget corresponding to a quantile of human effort."""
        if self.counts:
            if not 0 < quantile < 1:
                raise ValueError("quantile must be in (0,1)")
            i = min(int(quantile * (len(self.counts) - 1)), len(self.counts) - 1)
            return float(self.counts[i])
        return _lognormal_quantile(self.mean, PROVISIONAL_SIGMA, quantile)

    def percentile_of(self, actions: float) -> float:
        """What fraction of human tasks cost fewer actions than this?"""
        if self.counts:
            return bisect_left(self.counts, actions) / len(self.counts)
        return _lognormal_cdf(self.mean, PROVISIONAL_SIGMA, actions)

    # -- io ------------------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "measured": self.measured,
            "provenance": self.provenance,
            "n_tasks": self.n,
            "mean_actions": round(self.mean, 3),
            "quantiles": {k: round(v, 2) for k, v in self.quantiles.items()},
            "counts": self.counts,
        }

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "Ruler":
        with open(path) as f:
            d = json.load(f)
        return cls(
            counts=d.get("counts"),
            quantiles=d["quantiles"],
            mean=d["mean_actions"],
            n=d["n_tasks"],
            provenance=d["provenance"],
            measured=d["measured"],
        )

    def save(self, path: str = DEFAULT_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)


# -- log-normal helpers (provisional ruler only) -----------------------------

def _lognormal_mu(mean: float, sigma: float) -> float:
    return math.log(mean) - sigma * sigma / 2


def _lognormal_quantile(mean: float, sigma: float, q: float) -> float:
    # inverse CDF via the probit approximation of the standard normal
    z = _probit(q)
    return math.exp(_lognormal_mu(mean, sigma) + sigma * z)


def _lognormal_cdf(mean: float, sigma: float, x: float) -> float:
    if x <= 0:
        return 0.0
    z = (math.log(x) - _lognormal_mu(mean, sigma)) / sigma
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def _probit(p: float) -> float:
    """Acklam's inverse normal CDF approximation. |error| < 1.15e-9."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0,1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# -- construction ------------------------------------------------------------

def provisional() -> Ruler:
    """Ruler modelled from the one published Mind2Web statistic. Not measured."""
    q = {f"{x:.2f}": _lognormal_quantile(MIND2WEB_MEAN_ACTIONS, PROVISIONAL_SIGMA, x)
         for x in QUANTILES}
    return Ruler(
        counts=None,
        quantiles=q,
        mean=MIND2WEB_MEAN_ACTIONS,
        n=2350,
        provenance=(
            "PROVISIONAL. Log-normal with mean=7.3 (Mind2Web published mean, "
            f"Deng et al. NeurIPS 2023) and assumed sigma={PROVISIONAL_SIGMA}. "
            "The mean is real; the spread is a modelling assumption. "
            "Replace by running `python -m humanbrowser.ruler build`."
        ),
        measured=False,
    )


def build(split: str = "train") -> Ruler:
    """Measure the real distribution. Needs network and `pip install datasets`."""
    from datasets import load_dataset  # imported lazily; optional dependency

    ds = load_dataset("osunlp/Mind2Web", split=split)
    counts = sorted(len(r["action_reprs"]) for r in ds)
    if not counts:
        raise RuntimeError("no tasks loaded")
    mean = sum(counts) / len(counts)
    r = Ruler(
        counts=counts,
        quantiles={},
        mean=mean,
        n=len(counts),
        provenance=f"MEASURED from osunlp/Mind2Web split={split} (len(action_reprs)).",
        measured=True,
    )
    r.quantiles = {f"{q:.2f}": r.budget_at(q) for q in QUANTILES}
    return r


if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "build":
        ruler = build(sys.argv[2] if len(sys.argv) > 2 else "train")
        ruler.save()
        print(f"measured {ruler.n} tasks -> {DEFAULT_PATH}")
    else:
        ruler = Ruler.load() if os.path.exists(DEFAULT_PATH) else provisional()
    print(("MEASURED" if ruler.measured else "PROVISIONAL") + f"  n={ruler.n}  mean={ruler.mean:.2f}")
    print(ruler.provenance)
    for q, v in ruler.quantiles.items():
        print(f"  p{float(q)*100:>4.0f}  {v:6.1f} actions")
