"""Rule 1: a goal must not quote the vocabulary of the thing it seeks.

The failure this prevents is silent. A leaking goal produces a plausible-looking
found rate that measures string matching, so the check has to be a hard failure
and it has to catch the near-misses, not just exact repeats.
"""
from __future__ import annotations

import pytest

from humanbrowser import goals
from humanbrowser.goals import GoalLeak


# -- the case that has been shipping in our own README since M1 ---------------

def test_the_m1_fixture_goal_leaks_through_the_selector():
    """`--goal "shop the collection" --target "#collection"`. This is the exact
    command in the README, and it is a string matcher (D-008)."""
    with pytest.raises(GoalLeak):
        goals.check("shop the collection", "#collection")


def test_the_m1_fixture_goal_leaks_through_the_label():
    with pytest.raises(GoalLeak):
        goals.check("shop the collection", "The collection")


def test_a_user_phrased_goal_passes():
    """How someone who does not know the feature's name would ask."""
    goals.check("I run this same search every week, can I keep it",
                "#trail-alerts", "Trail Alerts", "Provisioning")


# -- what counts as a collision ----------------------------------------------

@pytest.mark.parametrize("goal,label", [
    ("save my basket", "Save basket"),          # exact word
    ("save my baskets", "Save basket"),         # plural on the goal side
    ("save my basket", "Saved baskets"),        # plural on the label side
    ("find the CATEGORIES", "category page"),   # case + plural
    ("checkout now", "#checkout-button"),       # inside a selector
    ("track my delivery", "[data-id='delivery']"),
])
def test_collisions_are_rejected(goal, label):
    with pytest.raises(GoalLeak):
        goals.check(goal, label)


@pytest.mark.parametrize("goal,label", [
    ("keep this search for later", "Provisioning"),
    ("where do I complain", "Support"),
    ("I want to send this back", "Returns policy"),
    ("", "Anything"),                            # nothing to leak
    ("some goal", ""),                           # nothing to check against
])
def test_non_collisions_are_allowed(goal, label):
    goals.check(goal, label)


def test_stopwords_alone_do_not_collide():
    """Otherwise every goal collides with every label via 'the' and 'for'."""
    goals.check("what can I do with the thing", "The Do For You")


def test_short_words_do_not_collide():
    """Two-letter tokens are noise, not vocabulary."""
    goals.check("go up a level", "Up")


# -- the error has to be usable ----------------------------------------------

def test_the_error_names_the_shared_words_and_the_label():
    with pytest.raises(GoalLeak) as e:
        goals.check("shop the collection", "The collection", where="the selector")
    msg = str(e.value)
    assert "collection" in msg
    assert "The collection" in msg
    assert "the selector" in msg
    assert "Rule 1" in msg


def test_every_label_is_checked_not_just_the_first():
    with pytest.raises(GoalLeak):
        goals.check("find my invoices", "Home", "Account", "Invoice history")


# -- the helpers --------------------------------------------------------------

def test_leaks_reports_the_shared_words():
    assert goals.leaks("save the collection", "collection page") == {"collection"}


def test_content_words_strips_stopwords_and_stems():
    assert goals.content_words("The Collections are here") == {"collection"}


def test_selector_punctuation_is_not_vocabulary():
    assert goals.leaks("nav to it", "[role='nav']") == {"nav"}
    assert goals.leaks("find something", "#a > .b:hover") == set()
