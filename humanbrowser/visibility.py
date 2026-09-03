"""
Crude "would a person plausibly notice this?" score.

Day-1 stand-in for a real saliency model. Three signals a browser can measure
for free, no model download:

  contrast  text vs its effective background, as a WCAG ratio
  size      how much of the viewport the element occupies
  position  how far down the document it sits

The point is not accuracy. The point is that it is the same SHAPE of signal a
saliency model produces, so we can find out on day one whether gating the policy
by perceptibility changes what the visitor misses. If it does, the real model
(SUM, --condition 3) is worth the two days. If it does not, stop.

Known crudeness, all deliberate:
  - gradient backgrounds are approximated by their first colour stop
  - no account of surrounding clutter, faces, images, or motion
  - position is a linear proxy for scroll cost, not measured attention
"""
from __future__ import annotations

# Tuning. Deliberately few knobs, all readable.
CONTRAST_FULL = 7.0        # WCAG AAA — at or above this, contrast stops helping
AREA_FLOOR = 600.0         # px^2; a small inline link
AREA_CEIL = 24000.0        # px^2; a big hero button
FOLD_DECAY = 0.55          # multiplier per viewport-height below the fold
AREA_FLOOR_WEIGHT = 0.35   # a tiny element is still somewhat noticeable
DEFAULT_THRESHOLD = 0.22   # below this, the visitor does not consider it


def _norm_contrast(ratio: float) -> float:
    return max(0.0, min(1.0, (ratio - 1.0) / (CONTRAST_FULL - 1.0)))


def _norm_area(px2: float) -> float:
    import math
    if px2 <= AREA_FLOOR:
        return 0.0
    if px2 >= AREA_CEIL:
        return 1.0
    return math.log(px2 / AREA_FLOOR) / math.log(AREA_CEIL / AREA_FLOOR)


def _norm_position(top_px: float, viewport_h: float) -> float:
    depth = max(0.0, top_px) / max(viewport_h, 1.0)
    return FOLD_DECAY ** depth


def score(feat: dict, viewport_h: float = 900.0) -> float:
    """Combine into [0,1]. Contrast is the gate; size and depth modulate it."""
    c = _norm_contrast(feat.get("contrast", 1.0))
    a = _norm_area(feat.get("area", 0.0))
    p = _norm_position(feat.get("top", 0.0), viewport_h)
    return c * (AREA_FLOOR_WEIGHT + (1 - AREA_FLOOR_WEIGHT) * a) * p


def annotate(elements: list[dict], feats: list[dict], viewport_h: float = 900.0) -> list[dict]:
    """Attach `visibility` to each element, in place, and return the list."""
    for el, f in zip(elements, feats):
        el["features"] = f
        el["visibility"] = round(score(f, viewport_h), 4)
    return elements
