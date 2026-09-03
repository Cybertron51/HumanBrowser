"""Rule 1: the goal must not contain the words you are testing.

If the goal is "find Trail Alerts" and the feature is called Trail Alerts, you
have built a string matcher and it will report that everything is easy. Goals
must be phrased in the user's vocabulary — "I run this same search every week,
can I keep it?" — because the vocabulary gap between how users think and how you
labelled it is where most real discoverability failures live.

This is a hard failure, never a warning. A run that violates it produces a
number that looks fine and means nothing, which is worse than no number.

Enforced in two places, because the target's real label is not known until the
visitor reaches it:

  before the run   against the CSS selector, and --target-label if given
  during the run   against the target's actual accessible name, the first time
                   it is located; the run aborts rather than reporting

See D-008 and D-019.
"""
from __future__ import annotations

import re

from .scent import STOPWORDS   # one owner for the stoplist (see D-016)

# Selector punctuation and the structural words that are not content.
_SELECTOR_NOISE = re.compile(r"[#.\[\]='\"<>~+*:()-]+")


class GoalLeak(ValueError):
    """The goal shares vocabulary with the thing it is supposed to be looking for."""


def _stem(word: str) -> str:
    """Crude singularisation, so `collections` still collides with `collection`.

    Only strips `es` after a sibilant (boxes, dishes). Doing it unconditionally
    turned `invoices` into `invoic`, which then failed to match `invoice` — the
    check silently passed a goal that does leak.
    """
    if len(word) < 4 or word.endswith("ss"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("es") and (word[-3] in "sxzo" or word.endswith(("ches", "shes"))):
        return word[:-2]
    if word.endswith("s"):
        return word[:-1]
    return word


def content_words(text: str) -> set[str]:
    """Stopword-filtered, crudely stemmed tokens of length > 2."""
    raw = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {_stem(w) for w in raw if w not in STOPWORDS and len(w) > 2}


def leaks(goal: str, label: str) -> set[str]:
    """Content words the goal and the label share."""
    return content_words(goal) & content_words(_SELECTOR_NOISE.sub(" ", label or ""))


def check(goal: str, *labels: str, where: str = "") -> None:
    """Raise GoalLeak if the goal shares a content word with any label.

    Empty and whitespace-only labels are ignored; a missing label is not a pass,
    it is simply nothing to check yet.
    """
    for label in labels:
        shared = leaks(goal, label)
        if shared:
            words = ", ".join(sorted(shared))
            raise GoalLeak(
                f"Goal {goal!r} shares {words!r} with {label!r}"
                + (f" ({where})" if where else "")
                + ".\nRule 1: a goal containing the target's own vocabulary measures"
                  " string matching, not discoverability. Rephrase it the way a user"
                  " who does not know the feature's name would ask for it."
            )
