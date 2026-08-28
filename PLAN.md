# HumanBrowser — build plan

**What it measures:** how hard a feature is for a human to find, as a number you
can track across releases.

You ship something. Adoption is low. Analytics cannot tell you whether people
found it and didn't want it, or never found it at all — those look identical in
a funnel and need opposite fixes. HumanBrowser runs a population of simulated
visitors at the feature and reports how many reach it, how much effort it costs
them, and where the ones who fail give up.

Nothing on the market does this. Attention tools score a screenshot and cannot
click. Agent tools click but cannot see, and never give up. Tree testing covers
findability but runs on a stripped-down text menu, not your real interface. NN/g
defines *discoverability* — encountering functionality you weren't aware of —
and names no dedicated technique for measuring it.

---

## The metric

Effort is denominated in **human actions**, read off a reference distribution
built from Mind2Web: 2,350 tasks, 137 real websites, complete human action
sequences, mean 7.3 actions per task.

A run reports:

```
FEATURE: Trail Alerts (save a search)
GOAL:    "I run this same search every week, can I keep it?"

  found                41%
  median cost to find  14 actions  →  93rd percentile of human task effort
  quit before finding  59%, median 9 actions in
  most common exit     footer (34%), Account menu (19%)
  never considered     "Provisioning" link — below attention threshold in 89% of runs
```

The headline claim is **"this costs more than 93% of ordinary web tasks."**
Not a 0–100 score. A percentile against real recorded human effort.

### Why this is defensible

Mind2Web contains only completed tasks — every trajectory was demonstrated and
verified. So it calibrates *effort under goal pursuit* and says nothing directly
about abandonment. We do not pretend otherwise. The quit threshold is derived
from a high quantile of the effort distribution, which is a modelling choice and
is labelled as one in every report.

Two properties make the conservatism work in our favour:

- Mind2Web annotators were paid and instructed, so they were more motivated than
  an idle visitor. The distribution is an **upper bound** on real patience.
  Difficulty scores built on it *understate* the problem.
- Every comparison is within-instrument: this feature against that feature, this
  release against last. Calibration error is shared and cancels. We never claim
  the bot is a human — only that when it struggles, humans struggle.

---

## Architecture

| Module | Does | Status |
|---|---|---|
| `perceive.py` | Turn a live page into the visitor's observation: interactive elements, bounding boxes, accessibility tree, viewport-scoped, occlusion-tested | **working** |
| `ruler.py` | Human effort reference distribution and percentile lookups | **working** (ruler provisional — see below) |
| `budget.py` | Effort budget, frustration-weighted spending, quit rule, population sampling, survival curves | **working** |
| `attention.py` | Predicted visual attention per element; gates what the policy may consider | to build (M1) |
| `policy.py` | Choose the next action: scent × visibility | to build (M2) |
| `report.py` | Session traces → the report above | to build (M2) |

### How the pieces connect

```
page ──perceive──> [elements, boxes, a11y tree]
                          │
                   attention (saliency per element)
                          │
                   policy: score = scent(element, goal) × visibility(element)
                          │
                   budget.spend(promise = best score on page)
                          │
              exhausted? ──yes──> abandon, record exit point
                          │
                          no ──> act, next page
```

`promise` is the single number connecting perception to persistence: how good
this page looks, given only what the visitor would plausibly have noticed.

### The quit rule

From `budget.py`. Two ideas, both borrowed:

1. Budget = `ruler.budget_at(quantile) × persistence`. A visitor at q=0.90
   spends what the 90th-percentile human spends on a comparable task.
2. Actions are not equally expensive. Cost scales with how far the current page
   falls below the **aspiration level** — the running mean of how promising the
   pages already seen were. A dead end burns budget up to 4× faster than a
   promising trail. This is SNIF-ACT's satisficing rule (Fu & Pirolli 2007),
   folded into the cost function so there is one termination condition instead
   of two.

Patience is sampled per visitor (log-normal, median 1.0), so the output is a
survival curve rather than a point estimate. Some people are dogged; most aren't.

---

## Two rules that will make or break this

**1. The goal string must never contain the label you are testing.**

If the goal is "find Trail Alerts" and the feature is called Trail Alerts, you
have built a string matcher and it will report that everything is easy. Goals
must be phrased in the user's vocabulary — *"I run this same search every week,
can I keep it?"* — because the vocabulary gap between how users think and how you
labelled it is where most real discoverability failures live.

Enforce this in code: reject any goal that shares a content word with the target
element's accessible name or any label on the path to it. Make it a hard failure,
not a warning.

**2. Gate the policy by predicted attention.**

An LLM is unusually good at semantic matching. It will connect "keep this search"
to a small footer link labelled "Provisioning" faster than a person scanning that
footer would, and your difficulty scores will collapse toward zero. The attention
gate is what stops the bot from considering elements it would never have noticed.
Without it this project measures nothing.

Corollary: the gate must be *auditable*. Log every element that was filtered out
each step. "Never considered" is a report line, and it is often the finding.

---

## Milestones

### M0 — foundations ✔
Perception layer, effort ruler, budget mechanic, a fixture site with a seeded
defect. All present and runnable.

**Done:** `python -m humanbrowser.ruler show` prints a percentile table;
`budget.py` produces a survival curve from a simulated session.

### M1 — walking skeleton + cheap gate ✔ (2026-08-28)
The loop runs: observe → score → spend → click → repeat until found or out of
patience. `PICK_NEXT` is word overlap with the goal; `FOUND` is a CSS selector.
The visibility gate is the cheap stand-in — WCAG contrast, element area, depth
down the page — no model, no download.

**Result on the Northlake fixture,** goal `"shop the collection"`, target the
low-contrast hero CTA:

    found rate   gate OFF 70%   gate ON 17%   delta -53%

The hypothesis holds. Limiting the visitor to what they would plausibly notice
changes what they miss, on day one, with a crude gate. That is the go/no-go and
it passed — the real saliency model is now worth the two days.

### M2 — population reporting and the second test case
The population runner and report exist. Two gaps:

1. **The vocabulary-gap case does not work yet.** Goal `"I run this same search
   every week"` against `#trail-alerts` (reachable only via a footer link
   labelled "Provisioning") gives 50% / 50%, gate off vs on. Reason: keyword
   overlap is zero for every element, so scores are flat, so softmax is
   near-uniform and visibility has nothing to modulate. **The gate only does
   work when there is scent to weight.** This makes M4 a prerequisite for the
   more interesting product case, not polish.
2. **Speed.** Flat scent means visitors wander to MAX_STEPS. 30 visitors × 2
   arms exceeded two minutes. Needs either faster scent convergence or parallel
   contexts.

**Done when:** both test cases produce a signal, and moving `Provisioning` from
the footer into the main nav measurably raises the found rate.

### M3 — the real attention model
Replace the contrast/area/depth heuristic with SUM (`--condition 3`, MIT,
trained on UEyes + FiWI). Viewport-by-viewport capture, compose into document
coordinates, integrate saliency mass per element box, normalize by area.

**Done when:** the gate-on/gate-off delta is at least as large as the crude
gate's −53%, and the per-element ranking is stable across runs.

**Watch:** never feed a full-page screenshot to the saliency model. A stitched
1440×9000 image puts the model's learned centre bias in the middle of the
*document*, where no one has ever looked.

### M4 — make it honest
Keyword → embedding scent (this is now load-bearing, see M2). Measured ruler
instead of the estimate. Reject goals containing the target's own words.

### M5 — validation
Replace the provisional ruler with the measured one:
`pip install datasets && python -m humanbrowser.ruler build`. Needs an
unrestricted network — HuggingFace is blocked from some environments.

Then validate, in ascending order of cost and strength:

1. **Self-consistency.** Rank the fixture's features by difficulty. Does the
   order match what anyone eyeballing the site would say?
2. **Known-easy anchors.** On a real site, features whose discoverability is
   already known from analytics should come out easy. This is calibration against
   reference points the customer already owns, for free.
3. **Monotonicity against Mind2Web.** Does the bot need more actions on tasks
   where humans needed more actions? Free, uses public data, and is a stronger
   validation than anything published in the 2024–2026 simulated-user literature.
4. **First-click data**, if it ever becomes worth the money. ~$3–5/response on
   Lyssna. Not required — 1–3 carry the argument.

**Done:** a validation section in the README with real numbers, and a stated
claim narrow enough to survive scrutiny.

---

## What is provisional right now

`data/effort_ruler.json` is **modelled, not measured.** The mean (7.3 actions) is
the published Mind2Web figure. The spread is a log-normal assumption with
σ = 0.55, chosen because task-effort distributions are right-skewed and bounded
below at 1. Every percentile in the current output inherits that assumption.

Fix it in M3. Until then, reports must print `ruler: PROVISIONAL` — `budget.py`
already carries the flag through `summarize()`.

---

## Decisions not yet made

- **Does the attention gate actually change what the agent misses?** The whole
  project rests on this and it is testable in a weekend: run the Northlake
  fixture with and without the gate and compare found rates on the low-contrast
  CTA. If the gate changes nothing, stop and rethink.
- **Scent model.** Sentence-transformer cosine is the cheap default. An LLM
  judging "does this link look like it leads to X" is better and far slower.
  Probably: embeddings for scoring every element, LLM only for the top few.
- **What counts as a page.** Modals, drawers and filter states are not URLs.
  Needs a state-abstraction rule before multi-page crawling is meaningful.
- **Who this is for.** A CI check for product teams and an audit tool for
  agencies are different products with the same engine.

---

## Prior art worth not re-deriving

- **Fu & Pirolli, SNIF-ACT (2007)** — the giving-up rule, fit to 74 people at
  R² 0.69–0.91 on link choice. `budget.py` implements a variant.
- **Chi et al., Bloodhound (CHI 2003)** — automated site-wide simulation,
  validated on 244 people. Died because scent needed a hand-authored keyword
  query per goal and because JavaScript broke the static link graph. Both causes
  are now removable.
- **Jin, Bai & Oulasvirta (arXiv:2603.11759, 2026)** — modern scent via sentence
  transformers in a POMDP with bounded memory. Do not rebuild this. It is
  text-only and not gated by vision, which is the gap we are filling.
- **Humanoid (ASE 2019)** — the only explorer trained on human interaction
  traces; its authors later reported the learned model was not the source of its
  gains. Cite the caveat with the idea.

Full landscape in `RESEARCH.md`.
