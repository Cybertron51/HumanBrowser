#!/usr/bin/env python3
"""Generate the M2 fixture, in two variants that differ by one link's position.

Northlake v1 could not produce a signal (M-006). Two reasons, both fixed here:

1. **The vocabulary gap was total.** The only route was labelled "Provisioning",
   which signals nothing to a person or a model. With no scent gradient the
   visitor stops foraging and diffuses, and diffusion makes the gate and link
   position irrelevant by construction. Here the route is "Restock alerts" — a
   *partial* gap: it shares no words with the goal, so Rule 1 passes, but it is
   semantically reachable, so there is a gradient to follow.

2. **The site was too small.** 15 pages against a 40-step cap meant a random
   walk saturated it and found the target about half the time regardless. This
   builds ~75 pages, so a visitor who is not following scent is genuinely lost.

The variants are identical except that `alerts.html` is linked from the footer
(control) or the main nav (intervention). That is the A/B a customer would
actually run: same content, one element moved.

    python3 fixtures/build_northlake2.py

The predicted signature, if the instrument works:

    gate off   footer ~= nav      scent leads there wherever it sits
    gate on    footer <  nav      position matters only when visibility is modelled

An interaction, not a main effect. Any single arm alone proves nothing.
"""
from __future__ import annotations

import pathlib
import shutil

ROOT = pathlib.Path(__file__).parent / "northlake2"

# The feature under test. Its label shares no content word with the goal below,
# so Rule 1 passes, but the two are semantically close enough to be findable.
TARGET_LABEL = "Restock alerts"
GOAL = "is there a way to be notified when an item I want is available again"

CATEGORIES = {
    "packs": ["Ridgeline 45L", "Ridgeline 65L", "Kestrel Daypack", "Scree 30L",
              "Fellrunner Vest", "Talus Hauler", "Cairn 20L", "Moraine 55L",
              "Drift Sling", "Basin Roll-Top"],
    "tents": ["Kestrel 2P", "Kestrel 3P", "Halfdome Bivy", "Larch Tarp",
              "Windward 4P", "Alpenglow 1P", "Cirque Shelter", "Foehn Fly",
              "Saddle Vestibule", "Corrie Groundsheet"],
    "apparel": ["Stormcell Shell", "Down Sweater", "Merino Baselayer",
                "Fleece Grid Hoody", "Softshell Pant", "Sun Hoody",
                "Insulated Skirt", "Rain Cap", "Glove Liner", "Neck Gaiter"],
    "footwear": ["Approach Low", "Approach Mid", "Trail Runner", "Winter Boot",
                 "Camp Slipper", "Gaiter Set", "Wool Sock", "Liner Sock",
                 "Insole Kit", "Bootlace Pair"],
    "sale": ["Last-Season Shell", "Outlet Pack", "Clearance Tent",
             "Seconds Baselayer", "Ex-Demo Stove", "Returned Sleeping Bag",
             "Scratch Lantern", "End-of-Line Poles", "Sample Gloves",
             "Odd-Size Boots"],
    "lookbook": ["Autumn Traverse", "Winter Ridge", "Spring Melt", "Summer Col",
                 "Coastal Path", "High Route", "Bothy Nights", "River Crossing",
                 "First Light", "Last Camp"],
}

UTILITY = ["about", "shipping", "returns", "terms", "privacy", "support",
           "journal", "contact"]

CSS = """
*{box-sizing:border-box}body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#111827;background:#fff}
header{display:flex;align-items:center;gap:22px;padding:16px 28px;border-bottom:1px solid #e5e7eb}
.logo{font-weight:700;letter-spacing:.04em;text-decoration:none;color:#111827}
nav{display:flex;gap:16px;flex:1}nav a{color:#1f2937;text-decoration:none;font-size:14px}
.cart{color:#1f2937;text-decoration:none;font-size:14px}
main{padding:28px;max-width:1100px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:0 0 6px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-top:22px}
.card{border:1px solid #e5e7eb;border-radius:9px;overflow:hidden}
.ph{height:120px;background:#f3f4f6}.b{padding:12px}.p{color:#6b7280;margin:4px 0 0}
.card a{color:#111827;text-decoration:none;font-weight:600;font-size:15px}
footer{margin-top:48px;padding:24px 28px;border-top:1px solid #e5e7eb;display:flex;gap:14px;flex-wrap:wrap}
footer a{color:#6b7280;text-decoration:none;font-size:12px}
"""


def slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("/", "-")


def chrome(variant: str, body: str, title: str) -> str:
    """Header, footer and the one link whose position is the whole experiment."""
    alerts = f'<a href="/alerts.html">{TARGET_LABEL}</a>'
    nav_links = "".join(f'<a href="/{c}.html">{c.title()}</a>' for c in CATEGORIES)
    nav_extra = alerts if variant == "nav" else ""
    foot_links = "".join(f'<a href="/{u}.html">{u.title()}</a>' for u in UTILITY)
    foot_extra = alerts if variant == "footer" else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{title} — Northlake</title><style>{CSS}</style></head><body>
<header>
  <a class="logo" href="/index.html">NORTHLAKE</a>
  <nav>{nav_links}{nav_extra}</nav>
  <a class="cart" href="/cart.html">Cart (0)</a>
</header>
<main>{body}</main>
<footer>{foot_links}{foot_extra}</footer>
</body></html>"""


def build(variant: str) -> int:
    out = ROOT / variant
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pages = 0

    def write(name: str, body: str, title: str):
        nonlocal pages
        (out / name).write_text(chrome(variant, body, title))
        pages += 1

    cards = "".join(
        f'<div class="card"><div class="ph"></div><div class="b">'
        f'<a href="/{c}.html">{c.title()}</a><p class="p">Shop {c}</p></div></div>'
        for c in CATEGORIES)
    write("index.html",
          f'<h1>Gear for long days out</h1><p>Packs, shelter and layers, '
          f'built for weather.</p><div class="grid">{cards}</div>',
          "Home")

    for cat, products in CATEGORIES.items():
        cards = "".join(
            f'<div class="card"><div class="ph"></div><div class="b">'
            f'<a href="/{slug(p)}.html">{p}</a><p class="p">${199 + 7 * i}</p>'
            f'</div></div>' for i, p in enumerate(products))
        write(f"{cat}.html", f'<h1>{cat.title()}</h1><div class="grid">{cards}</div>',
              cat.title())
        for p in products:
            write(f"{slug(p)}.html",
                  f'<h1>{p}</h1><p>Part of our {cat} range.</p>'
                  f'<p><a href="/{cat}.html">Back to {cat}</a></p>'
                  f'<p><button>Add to cart</button></p>', p)

    for u in UTILITY:
        write(f"{u}.html", f'<h1>{u.title()}</h1><p>Information about {u}.</p>', u.title())
    write("cart.html", '<h1>Cart</h1><p>Your cart is empty.</p>', "Cart")

    # The target. Its heading is the label Rule 1 checks against.
    write("alerts.html",
          f'<h1>{TARGET_LABEL}</h1>'
          f'<div id="restock-signup" style="margin-top:24px;padding:20px;'
          f'border:1px solid #e5e7eb;border-radius:9px">'
          f'<h2>{TARGET_LABEL}</h2>'
          f'<p>Tell us the item and size you are waiting on and we will let you '
          f'know the moment it is available again.</p>'
          f'<button id="watch-item">Watch this item</button></div>',
          TARGET_LABEL)
    return pages


if __name__ == "__main__":
    for v in ("footer", "nav"):
        n = build(v)
        print(f"  {v:7} {n} pages -> {ROOT / v}")
    print(f"\n  goal:   {GOAL!r}")
    print(f"  target: #restock-signup  (label {TARGET_LABEL!r})")
