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
import re

STOPWORDS = {
    "a", "an", "the", "i", "my", "me", "we", "it", "this", "that", "these",
    "is", "are", "was", "be", "been", "can", "could", "do", "does", "did",
    "to", "of", "for", "in", "on", "at", "by", "with", "and", "or", "but",
    "if", "so", "as", "from", "up", "out", "am", "want", "need", "would",
    "like", "how", "what", "where", "there", "here", "you", "your", "again",
}

REVISIT_PENALTY = 0.25   # multiplier for something already clicked this session
FLOOR = 1e-3             # nothing is truly unclickable
DEFAULT_TEMPERATURE = 0.35


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in STOPWORDS and len(w) > 2}


def scent(goal: str, element: dict) -> float:
    """Word overlap between the goal and the element's visible text. [0,1]."""
    g = tokens(goal)
    if not g:
        return 0.0
    e = tokens(" ".join(filter(None, [element.get("name"), element.get("href")])))
    if not e:
        return 0.0
    return len(g & e) / len(g)


def score_elements(elements: list[dict], goal: str, *, gate: bool,
                   visited: set[str] | None = None) -> list[float]:
    visited = visited or set()
    out = []
    for el in elements:
        s = scent(goal, el)
        v = el.get("visibility", 1.0) if gate else 1.0
        x = max(FLOOR, s * v if gate else max(s, FLOOR))
        if _key(el) in visited:
            x *= REVISIT_PENALTY
        out.append(x)
    return out


def choose(elements: list[dict], goal: str, *, gate: bool, rng: random.Random,
           visited: set[str] | None = None,
           temperature: float = DEFAULT_TEMPERATURE):
    """Pick an element by softmax over score. Returns (element, promise, scores)."""
    if not elements:
        return None, 0.0, []
    scores = score_elements(elements, goal, gate=gate, visited=visited)
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
