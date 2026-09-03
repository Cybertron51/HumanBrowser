"""
How the visitor picks what to click.

v0 scent is deliberately stupid: word overlap between the goal and the element's
text. It exists so the loop can run today, and it gets replaced by embedding
similarity in M4. What matters now is the SHAPE:

    score = scent(element, goal) x visibility(element)

Two properties worth keeping when the pieces get smarter:

1. The gate is soft, not a filter. A hard cutoff makes a buried element
   unfindable rather than hard to find, which collapses the survival curve to
   0% or 100%. Some people do read footers. Low visibility should mean rarely
   chosen, not never.

2. Choice is stochastic. Real visitors on the same page do not all click the
   same thing. Softmax over scores, seeded per visitor. This is SNIF-ACT's
   random-utility selection rule.
"""
from __future__ import annotations

import math
import random

from . import scent as scent_models
from .scent import STOPWORDS, tokens   # re-exported; one owner lives in scent.py

REVISIT_PENALTY = 0.25   # multiplier for something already clicked this session
FLOOR = 1e-3             # nothing is truly unclickable
DEFAULT_TEMPERATURE = 0.35


def scent(goal: str, element: dict) -> float:
    """Keyword scent for one element. [0,1]. Kept for callers wanting one score."""
    return scent_models.DEFAULT.score(goal, [element])[0]


def score_elements(elements: list[dict], goal: str, *, gate: bool,
                   visited: set[str] | None = None,
                   scent_model=None) -> list[float]:
    """score = scent x visibility, floored, penalised for revisits.

    `scent_model` is batched because embedding scent wants to encode a whole
    page in one call; the keyword model ignores the distinction.
    """
    visited = visited or set()
    model = scent_model or scent_models.DEFAULT
    scents = model.score(goal, elements)
    out = []
    for el, s in zip(elements, scents):
        v = el.get("visibility", 1.0) if gate else 1.0
        x = max(FLOOR, s * v if gate else max(s, FLOOR))
        if _key(el) in visited:
            x *= REVISIT_PENALTY
        out.append(x)
    return out


def choose(elements: list[dict], goal: str, *, gate: bool, rng: random.Random,
           visited: set[str] | None = None,
           temperature: float = DEFAULT_TEMPERATURE,
           scent_model=None):
    """Pick an element by softmax over score. Returns (element, promise, scores)."""
    if not elements:
        return None, 0.0, []
    scores = score_elements(elements, goal, gate=gate, visited=visited,
                            scent_model=scent_model)
    m = max(scores)
    exps = [math.exp((s - m) / max(temperature, 1e-6)) for s in scores]
    total = sum(exps)
    r = rng.random() * total
    acc = 0.0
    pick = len(elements) - 1
    for i, e in enumerate(exps):
        acc += e
        if acc >= r:
            pick = i
            break
    # `promise` is how good this page looked, given only what could be noticed.
    return elements[pick], m, scores


def _key(el: dict) -> str:
    return f"{el.get('role')}|{el.get('name')}|{el.get('href')}"


def unnoticed(elements: list[dict], threshold: float) -> list[dict]:
    """Elements the visitor would rarely register. Often the finding."""
    return [e for e in elements if e.get("visibility", 1.0) < threshold]
