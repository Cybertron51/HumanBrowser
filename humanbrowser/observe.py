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

OBSERVE_JS = r"""
() => {
  const SEL = 'a[href],button,input,select,textarea,[role=button],[role=link],[role=tab],[onclick]';
  const vw = innerWidth, vh = innerHeight;

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

  const out = [];
  for (const el of document.querySelectorAll(SEL)) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;

    // Occlusion test only where it is meaningful — inside the viewport.
    const inView = r.bottom > 0 && r.top < vh;
    if (inView) {
      const cx = Math.min(Math.max(r.left + r.width / 2, 1), vw - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 1), vh - 1);
      const top = document.elementFromPoint(cx, cy);
      if (top && !(el.contains(top) || top.contains(el))) continue;   // behind a modal
    }

    const fg = parse(cs.color) || [0, 0, 0];
    const bg = bgOf(el);
    const l1 = lum(fg), l2 = lum(bg);

    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') ||
            (el.tagName === 'A' ? 'link' : el.tagName === 'BUTTON' ? 'button' : el.tagName.toLowerCase()),
      name: (el.getAttribute('aria-label') || el.innerText || el.value ||
             el.getAttribute('placeholder') || el.getAttribute('title') || '')
             .trim().replace(/\s+/g, ' ').slice(0, 60),
      href: el.getAttribute('href') || null,
      box: [Math.round(r.x), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height)],
      contrast: (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05),
      area: r.width * r.height,
      top: r.y + scrollY,
      inView,
    });
  }
  return { viewport: vh, elements: out };
}
"""


def observe(page, gate: bool = True) -> list[dict]:
    """Return the visitor's observation of the page, with visibility attached."""
    from .visibility import score

    res = page.evaluate(OBSERVE_JS)
    vh = res["viewport"]
    for el in res["elements"]:
        el["visibility"] = round(score(el, vh), 4) if gate else 1.0
    return res["elements"]
