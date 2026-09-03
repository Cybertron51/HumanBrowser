"""
One pass over the page: what is here, and how noticeable is it.

Replaces the split between perceive.py (elements) and a second call for visual
features. Done in a single JS evaluation because the two need the same element
handles, and because collecting viewport-only elements made anything below the
fold unreachable — the visitor could never click a footer link, so a buried
feature scored 0% whether or not the gate was on.

The fix here is document-wide collection with a position penalty rather than a
viewport cutoff: everything on the page is reachable, but things far down are
much less likely to be noticed. That is a stand-in for modelling scroll as a
real action, which is M3 work.
"""
from __future__ import annotations

# Colour and contrast maths, shared verbatim by every JS entry point below.
# It used to be pasted into each one; the target probe then drifted and ended up
# reporting a hardcoded contrast, which silently disabled the detection channel
# (see D-009). One copy, so they cannot disagree again.
FEATURE_HELPERS_JS = r"""
  const parse = (s) => {
    if (!s) return null;
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(parseFloat);
    if (p.length > 3 && p[3] === 0) return null;
    return [p[0], p[1], p[2]];
  };
  const gradientStop = (img) => {
    if (!img || img === 'none') return null;
    const m = img.match(/rgba?\([^)]+\)/);
    return m ? parse(m[0]) : null;
  };
  const bgOf = (el) => {
    let n = el;
    while (n && n !== document.documentElement) {
      const cs = getComputedStyle(n);
      const c = parse(cs.backgroundColor) || gradientStop(cs.backgroundImage);
      if (c) return c;
      n = n.parentElement;
    }
    return [255, 255, 255];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b);
  };
  const contrastOf = (cs, el) => {
    const l1 = lum(parse(cs.color) || [0, 0, 0]), l2 = lum(bgOf(el));
    return (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05);
  };
  const hidden = (cs) =>
    cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0;
"""

OBSERVE_JS = r"""
() => {
  const SEL = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[onclick]';
  const vw = innerWidth, vh = innerHeight;
""" + FEATURE_HELPERS_JS + r"""
  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (hidden(cs)) continue;

    // Occlusion test only where it is meaningful — inside the viewport.
    const inView = r.bottom > 0 && r.top < vh;
    if (inView) {
      const cx = Math.min(Math.max(r.left + r.width / 2, 1), vw - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 1), vh - 1);
      const top = document.elementFromPoint(cx, cy);
      if (top && !(el.contains(top) || top.contains(el))) continue;   // behind a modal
    }

    // Stamp an unambiguous handle. Clicking by visible text picked the wrong
    // element whenever two shared a label, and a strict-mode failure was then
    // indistinguishable from a genuine dead end.
    el.setAttribute('data-hb', String(out.length));

    out.push({
      hb: out.length,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') ||
            (el.tagName === 'A' ? 'link' : el.tagName === 'BUTTON' ? 'button' : el.tagName.toLowerCase()),
      name: (el.getAttribute('aria-label') || el.innerText || el.value ||
             el.getAttribute('placeholder') || el.getAttribute('title') || '')
             .trim().replace(/\s+/g, ' ').slice(0, 60),
      href: el.getAttribute('href') || null,
      box: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
      contrast: contrastOf(cs, el),
      area: r.width * r.height,
      top: r.y + scrollY,
      inView,
    });
  }
  return { viewport: vh, elements: out };
}
"""

# The same features, for one element named by a CSS selector. Returns null when
# the target is absent or not rendered, so "is it there" and "would it be
# noticed" are one round trip and use identical maths to OBSERVE_JS.
TARGET_JS = r"""
(sel) => {
""" + FEATURE_HELPERS_JS + r"""
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;
  const cs = getComputedStyle(el);
  if (hidden(cs)) return null;
  return {
    contrast: contrastOf(cs, el),
    area: r.width * r.height,
    top: r.y + scrollY,
    // The target's LABEL, for Rule 1 (D-019). A heading inside the element
    // beats its innerText: targeting a container would otherwise yield the
    // whole body copy, and Rule 1 would reject any goal sharing a word with
    // the feature's prose rather than with its name.
    name: (() => {
      const h = el.matches('h1,h2,h3,h4,h5,h6') ? el : el.querySelector('h1,h2,h3,h4,h5,h6');
      const raw = el.getAttribute('aria-label') || el.getAttribute('title') ||
                  (h && h.innerText) || el.value || el.innerText || '';
      return raw.trim().replace(/\s+/g, ' ').slice(0, 60);
    })(),
  };
}
"""


_DESTROYED = "Execution context was destroyed"


def eval_stable(page, js, arg=None, *, retries: int = 3, backoff_ms: int = 120):
    """page.evaluate that survives a navigation landing mid-call.

    Clicks are issued with no_wait_after=True and followed by a fixed settle
    wait. When that wait is short (D-017 cut it to 20 ms for speed) a navigation
    can still be in flight when the next evaluate runs, and Playwright destroys
    the execution context underneath it. Rare per step, near-certain across a
    few thousand steps — it killed three 300-visitor runs before the traceback
    was actually read (D-023).

    Retrying is correct rather than a papering-over: the page we want to observe
    is the one that has just finished loading, so waiting and re-evaluating asks
    the same question of the right context.
    """
    for attempt in range(retries + 1):
        try:
            return page.evaluate(js, arg) if arg is not None else page.evaluate(js)
        except Exception as e:
            if _DESTROYED not in str(e) or attempt == retries:
                raise
            page.wait_for_timeout(backoff_ms)


def observe(page, gate: bool = True) -> list[dict]:
    """Return the visitor's observation of the page, with visibility attached."""
    from .visibility import score

    res = eval_stable(page, OBSERVE_JS)
    vh = res["viewport"]
    for el in res["elements"]:
        el["visibility"] = round(score(el, vh), 4) if gate else 1.0
    return res["elements"]
