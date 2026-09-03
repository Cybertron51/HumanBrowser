"""A fake page, so the loop is testable without a browser.

Deliberately not a mock: it is a tiny working model of a site — pages, links,
navigation — so `visit()` runs its real control flow against it. Tests that
assert on click sequences and exit reasons are then fast and deterministic.
"""
from __future__ import annotations

import pytest

from humanbrowser.ruler import provisional


def element(name, href=None, *, contrast=12.0, area=8000.0, top=100.0, role="link"):
    """One interactive element, shaped as observe.py's JS returns it."""
    return {"hb": 0, "tag": "a", "role": role, "name": name, "href": href,
            "box": [0, int(top), 100, 40], "contrast": contrast, "area": area,
            "top": top, "inView": top < 900}


class FakePage:
    """Pages keyed by url. Clicking a link's text navigates to its href."""

    def __init__(self, pages, target_on=None, target_feat=None, viewport_h=900):
        self.pages = pages
        self.target_on = target_on            # url where the target selector exists
        self.target_feat = target_feat or {"contrast": 12.0, "area": 8000.0, "top": 100.0}
        self.viewport_h = viewport_h
        self.url = next(iter(pages))
        self.clicks = []
        self.failing_clicks = set()           # names whose click raises

    # -- playwright surface used by run.visit --------------------------------

    def goto(self, url, wait_until=None):
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg=None):
        if arg is None:                        # observe.OBSERVE_JS
            els = [dict(e, hb=i) for i, e in enumerate(self.pages.get(self.url, []))]
            return {"viewport": self.viewport_h, "elements": els}
        # observe.TARGET_JS: null when the target is absent or not rendered.
        return dict(self.target_feat) if self.url == self.target_on else None

    def click(self, selector, timeout=None, no_wait_after=None):
        hb = int(selector.split('"')[1])
        el = self.pages.get(self.url, [])[hb]
        self.clicks.append(el["name"])
        if el["name"] in self.failing_clicks:
            raise RuntimeError("element detached")
        if el.get("href"):
            self.url = el["href"]
        # a click that navigates nowhere is a real dead end, not an error


@pytest.fixture
def ruler():
    return provisional()


@pytest.fixture
def two_page_site():
    """Home links to /shop; the target lives on /shop."""
    return FakePage(
        pages={
            "/": [element("Shop the collection", "/shop"),
                  element("About", "/about", area=900.0, top=2400.0, contrast=2.0)],
            "/shop": [element("Back", "/")],
            "/about": [element("Back", "/")],
        },
        target_on="/shop",
    )
