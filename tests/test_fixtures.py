"""Guards on the M2 fixture generator.

The fixture encodes an experimental design (D-022). If someone edits the goal or
moves the link, these say so — a fixture that quietly stops testing what it
claims to test produces numbers that look fine and mean nothing.
"""
from __future__ import annotations

import pytest

from humanbrowser import goals

from fixtures.build_northlake2 import (CATEGORIES, GOAL, TARGET_LABEL, UTILITY,
                                       chrome, slug)

ALERTS = f'<a href="/alerts.html">{TARGET_LABEL}</a>'


# -- the design the fixture is supposed to embody -----------------------------

def test_the_goal_passes_rule_one():
    """The point of the redesign was a goal with no lexical overlap. If an edit
    reintroduces one, every number from this fixture becomes a string match."""
    goals.check(GOAL, TARGET_LABEL, "#restock-signup", "alerts")


def test_the_goal_is_not_merely_a_paraphrase_of_the_label():
    shared = goals.content_words(GOAL) & goals.content_words(TARGET_LABEL)
    assert shared == set()


def test_the_goal_is_phrased_as_a_user_question():
    """A goal in product vocabulary is the failure Rule 1 exists to catch; this
    is a weak proxy, but it catches a goal rewritten as a feature name."""
    assert len(GOAL.split()) >= 8


# -- the one difference between the variants ----------------------------------

def test_the_alerts_link_is_in_the_nav_only_in_the_nav_variant():
    page = chrome("nav", "<h1>x</h1>", "x")
    nav = page.split("<nav>")[1].split("</nav>")[0]
    assert ALERTS in nav


def test_the_alerts_link_is_in_the_footer_only_in_the_footer_variant():
    page = chrome("footer", "<h1>x</h1>", "x")
    foot = page.split("<footer>")[1].split("</footer>")[0]
    assert ALERTS in foot


@pytest.mark.parametrize("variant", ["footer", "nav"])
def test_the_link_appears_exactly_once(variant):
    """Two routes to the target would dilute the position effect being measured."""
    assert chrome(variant, "<h1>x</h1>", "x").count(ALERTS) == 1


def test_the_variants_differ_only_in_where_that_link_sits():
    a = chrome("footer", "<h1>x</h1>", "x").replace(ALERTS, "")
    b = chrome("nav", "<h1>x</h1>", "x").replace(ALERTS, "")
    assert a == b


# -- the site has to be big enough that diffusion cannot saturate it ----------

def test_the_site_is_large_enough_to_defeat_a_random_walk():
    """M-006: 15 pages against a 40-step cap meant a random walk found the
    target about half the time regardless, swamping every manipulation."""
    pages = 1 + len(CATEGORIES) + sum(len(v) for v in CATEGORIES.values()) \
            + len(UTILITY) + 2
    assert pages > 70


def test_every_page_carries_the_navigation():
    """The link must be reachable from anywhere, or the comparison measures
    graph structure rather than noticeability."""
    page = chrome("footer", "<h1>x</h1>", "x")
    for c in CATEGORIES:
        assert f'href="/{c}.html"' in page


def test_slugs_are_unique_across_every_product():
    names = [p for ps in CATEGORIES.values() for p in ps]
    assert len(set(map(slug, names))) == len(names)
