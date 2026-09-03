# Decision log

Why the code is the way it is. The point of this file is that we never re-run an
experiment we have already run, and never re-argue a choice we have already made
and understood.

`PLAN.md` is what we intend to do. This is what we have settled and what we
learned the hard way. When the two disagree, this file wins on matters of fact.

**Format.** Newest at the top of each section. Every entry gets a stable ID so
code comments can cite it (`# see D-007`). Status is one of:

- `active` — holds today
- `superseded by D-0xx` — we changed our mind; keep the entry, it records why
- `open` — known unresolved, do not assume either way

Entries are cheap. Write one whenever you make a non-obvious call, kill an idea,
or measure something. An entry that saves one re-run has paid for itself.

---

## Measurements

Numbers we have actually observed. Do not re-derive these; re-run only if the
code they depend on has changed, and then supersede the entry.

### M-008 — The position intervention is real: +10%, p=0.017, replicated
**Date:** 2026-09-03 · **Status:** active. **M2's acceptance criterion is met.**
`fixtures/northlake2`, embedding scent, gate on, n=300/cell, seed 11 — an
independent seed from M-007, not an extension of it.

| cell | found | 95% CI |
|---|---|---|
| footer, gate on | 53% (159/300) | [47%, 59%] |
| nav, gate on | 63% (188/300) | [57%, 68%] |

    difference  +10%   z=2.40   p=0.017   95% CI [+2%, +18%]

**It replicates.** M-007 measured 51% / 63% (+12%, p=0.087) at n=100 seed 3.
This is 53% / 63% (+10%, p=0.017) at n=300 seed 11. The effect was real all
along and simply underpowered — which is the outcome D-021 was written to make
distinguishable from M-006's phantom, where the point estimate *reversed* on
replication. The difference between those two cases is the whole reason for the
rule.

**What it means.** Moving one link from the footer into the main nav — same
content, same site, same goal — raises the fraction of simulated visitors who
find the feature by ten points. That is the product claim in its simplest form:
a design change scored before shipping it.

**The full 2x2 at matched power** (n=300, seed 11):

| | gate off | gate on | gate damage |
|---|---|---|---|
| footer | 81% [76,85] | 53% [47,59] | −28% |
| nav | 75% [69,79] | 63% [57,68] | −12% |

| effect | value | p |
|---|---|---|
| position, gate off | −6% (noise; true value 0) | 0.078 |
| **position, gate on** | **+10%** | **0.017** |

**Quote +10%, not the interaction.** Computing an interaction against the
measured control gave +16% (p=0.0029), but that subtracts a noisy estimate of a
quantity known to be exactly zero, which inflates both the effect and its
apparent significance. With the control null by construction (D-024), the
interaction *is* the gate-on effect: **+10%, p=0.017**. The larger number was an
artifact of treating a structural zero as something to be estimated.

The qualitative claim stands and is the one that matters: the gate is what makes
position matter. Move the link with visibility modelled and ten points more
visitors find the feature; move it without, and nothing changes, because nothing
in the model can see position.

**The gate-off control is exactly null, and this was settled mechanistically
rather than statistically** — see D-024. Observed −2% (n=100 seed 3), −6%
(n=300 seed 11), −3.7% (n=300 seed 23); none individually significant. Measuring
the actual click probabilities showed the two variants are the *same process*
with the gate off — identical element sets and identical P(click target) to four
decimal places on every page checked (0.1035, 0.0940, 0.1205). The true effect
is therefore zero by construction and every observed deviation is noise.

### M-007 — Redesigned fixture: the gate finally bites. Intervention not yet proven.
**Date:** 2026-09-03 · **Status:** superseded by M-008 (which replicated it at n=300)
`fixtures/northlake2/{footer,nav}`, 77 pages each, goal `"is there a way to be
notified when an item I want is available again"`, target `#restock-signup`
(label "Restock alerts"), embedding scent, n=100/cell, seed 3.

| | gate off | gate on | gate damage |
|---|---|---|---|
| footer | 79% [70,86] | 51% [41,61] | **−28%**, p<0.001 |
| nav | 77% [68,84] | 63% [53,72] | **−14%**, p=0.031 |
| position effect | −2%, p=0.73 | +12%, p=0.087 | interaction +14%, p=0.12 |

**Established.** The gate has a large, highly significant effect on this
fixture — the first time any fixture has produced one under a Rule 1-clean goal.
And the control passes: with the gate off, moving the link does nothing
(−2%, p=0.73). That is the result that matters most for validity, because it
rules out the DOM-ordering artifact that could have explained M-006.

**Not established.** That moving the link to the nav recovers found rate.
+12% at p=0.087 is the predicted direction and is *not* significant, and nor is
the interaction. Powering for a 51%→63% difference needs ~266/cell, so n=100 was
underpowered by design — see D-021, which I applied to the *reporting* but not
to the *planning*.

**Median cost tells the same story more quietly:** 5 actions footer/off,
6 footer/on, 4 nav/off, 5 nav/on. Moving the link saves about one action in both
arms.

### M-006 — The M2 position intervention shows nothing. The n=20 result was noise.
**Date:** 2026-09-03 · **Status:** active. **M2's acceptance criterion FAILS.**
Moving "Provisioning" from the footer into the main nav (`fixtures/northlake-nav`),
goal `"I run this same search every week, can I keep it"`, target
`#trail-alerts`, embedding scent, seed 7.

| cell | found | 95% CI |
|---|---|---|
| footer, gate off | 52% | [42%, 62%] |
| footer, gate on | 49% | [39%, 59%] |
| nav, gate off | 41% | [31%, 51%] |
| nav, gate on | 41% | [31%, 51%] |

| comparison | z | p |
|---|---|---|
| position, gate off | 1.56 | 0.12 |
| position, gate on | 1.14 | 0.26 |
| gate, footer | 0.42 | 0.67 |
| gate, nav | 0.00 | 1.00 |

**Nothing is significant.** All four cells overlap. Moving the link did not
raise the found rate; the point estimate went *down*.

**The n=20 run said the opposite and it was pure noise.** It read footer 40% /
nav 65% off / nav 75% on, and was written up here as the acceptance criterion
passing. At n=20 near p=0.5 the standard error is 11 points, so that "+35%" was
about 1.5 SE. The direction reversed at n=100. Nothing about the earlier run was
salvageable.

**Why there is no effect — and it is not about scent quality.** With
uninformative scent (M-005) every score is near the floor, so the visitor
performs a random walk. Northlake is 15 pages and the cap is 40 steps: a
40-step random walk saturates a 15-node graph, so it reaches `provisioning.html`
about half the time no matter where the link sits. The manipulation is swamped
by diffusion.

**This is the deeper problem.** Information foraging needs a scent *gradient*.
With no gradient the model does not degrade gracefully into a worse forager — it
stops being a forager at all and becomes Brownian motion, and Brownian motion on
a small graph finds everything eventually. Both the gate and link position are
then irrelevant by construction.

**So the vocabulary-gap case as built cannot produce a signal**, and no scent
model will rescue it, because "Provisioning" carries no signal for a human
either. What M2 needs is a **partial** vocabulary gap: a label with real
semantic pull that is badly placed. "Provisioning" is a total gap, which is a
different and less useful defect.

Also worth testing separately: a larger site, or a step cap small relative to
the site, so that diffusion cannot saturate it.

### M-005 — Embedding scent does NOT unblock the vocabulary-gap case
**Date:** 2026-09-03 · **Status:** active. **Refutes the prescription in D-007.**
Northlake, goal `"I run this same search every week, can I keep it"`, target
`#trail-alerts` (reachable only via the footer link "Provisioning"), n=20,
seed 0, `--compare`:

| scent | gate off | gate on | delta |
|---|---|---|---|
| keyword | 50% | 50% | +0% |
| embedding | 40% | 40% | **+0%** |

**The prediction failed.** D-007 diagnosed the no-signal case as flat scent and
concluded embeddings would fix it. Embeddings make scent non-flat and the case
still gives nothing.

**Why — the diagnostic is the finding.** Scores for that goal over
`index.html`, ranked:

    0.199  Browse lookbook
    0.193  Shop the collection
    0.181  NORTHLAKE
    0.158  Privacy
    ...
    0.058  Provisioning      <- the only route to the target, 10th of 18
    0.000  Cart (0)

Two separate failures, and only the first is a tuning problem:

1. **The spread is too small for the temperature.** 0.199 across the whole page
   gives a max/min odds ratio of 1.76x at T=0.35 — nearly uniform. Cosine
   similarities of short link text are compressed into a narrow band; they do
   not span [0,1] the way keyword overlap does.

2. **The ranking is wrong, so sharpening would make it worse.** "Provisioning"
   sits below "Privacy" and "Terms". Lowering the temperature would concentrate
   probability on "Browse lookbook" — confidently, on the wrong link.

**Non-flat but uninformative is no better than flat.** D-007's diagnosis was
right and its prescription was wrong, and those are separable: the gate needs
scent that *varies*, but it needs scent that varies *correctly*.

**This may be the fixture, not the model.** "Provisioning" does not signal "save
a search" to a person either — that is what makes it a seeded discoverability
defect. A label opaque to humans should be opaque to the model. So this is
arguably the instrument being right, and the M2 case needs a target whose label
is *findable but badly placed*, which is what the position intervention tests.

**Open:** separate temperatures for choice and for `promise` (they have
different requirements — `promise` needs absolute calibration, `choose` needs
relative discrimination) would fix (1) but not (2). Do not build it until there
is a case where (2) is not the binding constraint.

### M-004 — The gate barely blocks reachability. It multiplies cost by 66x.
**Date:** 2026-09-03 · **Status:** active, supersedes the split in M-003
Northlake, `"shop the collection"`, `#collection`, n=30, seed 0,
`--settle-ms 20`. Patience-limited cells at `--max-steps 120`, unlimited-patience
cells at `--max-steps 400`.

| arm | gate | patience | found | median actions to find |
|---|---|---|---|---|
| control | off | **off** | **100%** | **1** |
| perception | on | **off** | **90%** | **66** |
| headline | on | on | 17% | — |
| baseline | off | on | 70% | — |

**perception −10%  ·  patience −43%  ·  total −53%**

**The finding is the last column, not the found rates.** Ungated, the visitor
lands on "Shop the collection" immediately — scent 1.0, top of the page, one
action. Gated, that CTA is below the noticeability threshold, so the visitor
never considers it and has to stumble to `shop.html` by some other route: a
median of **66 actions**, which the ruler puts at the 100th percentile of
recorded human task effort.

So making an element imperceptible does **not** make the feature unreachable —
90% still get there eventually. It makes getting there cost 66x more, and *that*
is what removes 73 points of found rate once visitors are allowed to give up.

This is the clearest statement of the product thesis so far, and it is exactly
what a funnel cannot show you: the feature is findable, and nobody finds it.

**Caveat:** 3/30 gated visitors were still capped at 400 steps, so 90% is a
slight lower bound. The control was fully converged (0 capped).

**Provenance:** assembled from separate runs at matched seed and settings, not
one `--decompose` invocation — two long runs were killed mid-flight. The
patience-limited cells are cap-independent (no visitor was ever capped in them),
so mixing 120 and 400 is sound. `--decompose` now runs all seven cells (D-018).

### M-003 — The decomposition survives fixing the instrument, unchanged
**Date:** 2026-09-03 · **Status:** active, supersedes M-002
Same setup, re-run after D-009 and D-013–D-017: contrast fixed, fresh context
per visitor, unambiguous click handles, `--max-steps 120`, `--settle-ms 20`,
n=30, seed 0.

| cell | found | delta | vs M-002 |
|---|---|---|---|
| baseline | 70% | — | same |
| detect only | 70% | +0% | same |
| choose only | 17% | −53% | same |
| cost only | 70% | +0% | same |
| all channels | 17% | −53% | same |
| all, no quit | **63%** | **−7%** | was 37% / −33% at cap 40 |

**The five patience-limited cells are identical to the digit.** Four real
defects — contrast-blind detection, state bleeding between visitors,
text-matched clicks, an artificially low cap — affected them not at all. That is
a better outcome than the numbers moving: M-001 and M-002 were measured on a
flawed instrument and were right anyway.

**But the unlimited-patience cell moved a long way, and it rewrites the split.**

| cap | perception | patience |
|---|---|---|
| 40 (M-002) | −33% | −20% |
| 120 (here) | **−7%** | **−46%** |

At a cap high enough to matter, a gated visitor almost always gets there in the
end — 63% against a 70% baseline. What the gate actually does is make it cost
enormously more: median 31 actions to find, which the ruler puts at the 100th
percentile of recorded human task effort. So the damage is **not** that the
target becomes unreachable. It is that reaching it stops being worth it.

**M-002's split was an artifact of the cap**, and D-012's warning that the
perception figure was "a lower bound" turns out to have been understating it by
a factor of four.

**Methodological consequence, and it is the important line here: a
perception/patience split is not quotable while the unlimited-patience arm is
still hitting the cap.** 11/30 visitors were still capped at 120, so −7% remains
an upper bound on perception damage. Report the split only once `capped` is 0,
or report it as a bound and say which.

Two smaller things:

- **The `detect = 0` prediction was wrong.** See D-009 — a property of what
  `#collection` is, not a bug artifact.
- Do not read "the fixes were pointless" out of the unchanged cells. Three of
  the four were validity defects that could move a number on a different site,
  and the suite that would have caught D-009 now exists (D-013).

### M-002 — Gate channel decomposition: the −53% is entirely the choice channel
**Date:** 2026-08-29 · **Status:** superseded by M-003; point 1 was WRONG
Same setup as M-001 (Northlake, `"shop the collection"`, `#collection`, n=30,
seed 0), each gate channel isolated:

| cell | found | delta | failure modes |
|---|---|---|---|
| baseline | 70% | — | quit 9 |
| detect only | 70% | **+0%** | quit 9 |
| choose only | 17% | **−53%** | quit 25 |
| cost only | 70% | **+0%** | quit 9 |
| all channels | 17% | −53% | quit 25 |
| all, no quit | 37% | −33% | capped 19 |

**Three things this settles.**

1. ~~**`detect` contributes nothing** — but only because of D-009. This row is
   measuring the bug, not the design. Fix D-009 and `detect` will start biting.~~
   **WRONG — corrected by M-003.** The prediction failed: `detect` is still 0 on
   the fixed code. The target `#collection` is a plain high-contrast heading, so
   the contrast bug never affected it. See D-009 for the full correction.

2. **`cost` contributes exactly nothing**, as D-006 predicted from the algebra.
   Gating `promise` does not make visitors quit sooner, because `cost_of` keys
   off promise/aspiration and both dim together. The obvious confound is not a
   confound. D-006 is now measured, not just derived.

3. **The whole −53% is `choose`** — the mechanism the project is about. There is
   no interaction term: `choose` alone equals all three together.

**Splitting the damage.** With patience removed the gate still costs −33%
(70% → 37%), and 19/30 of those visitors hit `MAX_STEPS=40` rather than
finishing, so −33% is a *lower bound* on the pure perception effect. The
remaining −20% is patience amplification: visitors who would have found it
eventually but ran out of budget first.

Both halves are the thesis, not confounds — "hard to see" causing "gives up
sooner" is the causal chain being modelled. But they are different claims and
reports must not merge them.

**Open:** re-run with a larger `MAX_STEPS` to find where the unlimited-patience
arm actually asymptotes. 37% is not the ceiling.

### M-001 — M1 go/no-go: gating changes what the visitor misses
**Date:** 2026-08-28 · **Status:** active, but see D-008 and D-009
Northlake fixture, goal `"shop the collection"`, target the low-contrast hero
CTA, n=30: found rate **70% gate off, 17% gate on, delta −53%**.

This was the project's go/no-go and it passed, which is what licensed the two
days for the real saliency model (M3). Two caveats found later that narrow what
it proves — read D-008 and D-009 before quoting this number.

---

## Decisions

### D-025 — Nine defects from the first code review of this work
**Date:** 2026-09-03 · **Status:** active
All fixed, with regression tests where a test could have caught them. Recorded
because two are instances of failure modes already in this log, which means the
lessons had not actually been learned.

**The worst one: `--decompose` silently ignored `--scent`.** The decompose path
never forwarded `scent_model`, `check_goal` or `settle_ms`, so any future
`--decompose --scent embedding` would have run the *keyword* model and printed a
table with nothing indicating it. The entire M4 channel decomposition would have
been computed with the model M4 exists to replace.

*Why it survived:* an earlier `str.replace()` patch did not match and made no
change; I "verified" it with a grep that returned **one** of the two expected
call sites and did not notice the second was missing. A silent no-op edit plus a
grep that cannot distinguish "one hit" from "one of two hits". Verify a patch by
its effect, not by a substring appearing somewhere in the file.

**A recurrence of D-009's exact pattern.** `_visible_target` had become dead in
production — `visit()` inlined the same logic — while `tests/test_browser.py`
still asserted on it. So the browser tests written specifically to catch
contrast drift were testing a *copy* of the shipped path. `visit()` now calls
`_visible_target`, passing the already-fetched features so there is no second
round trip. **Two copies of a rule is how D-009 happened, and it happened again
inside the fix for it.**

The rest:

- Stale `data-hb` handles were never cleared, so an element stamped on one
  observation but filtered out on the next kept its attribute; a click on
  `[data-hb="3"]` takes the first DOM match, usually the stale one. Latent on
  static fixtures, live the moment a modal or dropdown appears.
- The capped-visitor warning summed both no-quit arms and divided by `n`, so it
  could print "50/25 visitors hit the cap" — on the very line that tells a
  reader whether to trust the perception/patience split.
- `if med else None` treated a median of **0** actions as missing data, so the
  "median cost to find" line vanished for the easiest possible site (target on
  the landing page). Truthiness where `is not None` was meant.
- `Population.run` never set `Outcome.reason`, so every outcome took the
  `"found"` default and quitters would be reported as successes.
- `run.py`'s module docstring example aborts under Rule 1 — `#trail-alerts
  button` resolves to a button labelled "Save this search", which collides with
  the goal's "search".
- `--compare` silently discarded `--channels`/`--gate`; now an explicit error.
- Persistence was sampled with a truncated `2.718 **` literal in `run.py` and
  `math.exp` in `budget.py`, two generators for one population. Now one `SPREAD`
  constant, with a test asserting they agree.

### D-024 — Check the mechanism before reaching for a p-value
**Date:** 2026-09-03 · **Status:** active
When an arm *should* be null by construction, verify that by measuring the
mechanism — here, the actual selection probabilities — rather than by
accumulating samples until a test resolves.

**What happened.** The gate-off control read −2% (p=0.73), then −6% (p=0.078),
then −3.7% (p=0.272). None significant. I pooled all three *after seeing them*,
got −4.8% at p=0.042, and briefly had a "significant" effect that cannot exist:
with the gate off `score = scent`, and the target scores 0.412 in both variants,
so the two arms are the same process. Instrumenting `observe` + `score_elements`
confirmed it — identical element sets, identical P(click target) to four
decimals on every page.

**Two lessons, and the second is the one I keep relearning.**

1. Post-hoc pooling of arms you have already inspected manufactures
   significance. Decide the analysis before looking, or treat the pooled result
   as exploratory only.
2. A mechanism check is stronger evidence than any p-value and is usually
   cheaper. One 20-second instrumentation run beat 1500 simulated visitors and
   settled the question outright rather than probabilistically.

Applies beyond controls: `promise` scale-invariance (D-006) was also derived
from the code first and confirmed by measurement second, and that ordering is
why it held up.

### D-023 — Observation retries a destroyed execution context
**Date:** 2026-09-03 · **Status:** active. Fixes a bug D-017 introduced.
`observe.eval_stable()` wraps `page.evaluate`, retrying up to 3 times (120 ms
apart) when Playwright reports "Execution context was destroyed". Clicks are
also followed by `wait_for_load_state("domcontentloaded")` before the fixed
settle pause, so the common case does not need the retry at all.

**The bug.** Clicks use `no_wait_after=True` and are followed by a fixed sleep.
At `--settle-ms 200` a navigation had almost always landed by the next
`observe`; at 20 ms it frequently had not, and the evaluate ran against a
context Chromium had already torn down. Probability per step is small;
probability across 300 visitors x tens of steps is near 1.

**What this says about D-017's validation.** I checked that 20 ms and 200 ms
produced *identical results* at n=30 and concluded the wait bought nothing. That
was true and insufficient: it tested output equivalence, not robustness at
scale. A timing change needs a soak, not just an A/B of the answer.

**Why retrying is correct and not a paper-over.** The page we want to observe is
the one that just finished loading, so waiting and re-asking queries the right
context. Other exceptions are re-raised untouched, and there is a test asserting
a `ReferenceError` in the JS is *not* retried into silence — retry logic that
swallows real bugs would be far worse than the race.

**Three 300-visitor runs died on this before the traceback was read**, because
the command piped stderr into `grep`, so the error was filtered out and only an
empty result and exit code 1 survived. Two of those failures were attributed to
system load, which was a real but separate problem. **Read the error before
theorising about the cause.**

### D-022 — The M2 fixture is generated, and its defect is a *partial* vocabulary gap
**Date:** 2026-09-03 · **Status:** active, supersedes the Northlake v1 M2 case
`fixtures/build_northlake2.py` generates two 77-page variants differing only in
whether `alerts.html` is linked from the footer or the nav.

**Two changes, each answering one half of M-006:**

1. **Partial gap, not total.** "Restock alerts" shares no content word with the
   goal (Rule 1 passes) but is semantically reachable — scent 0.412, ranked 1st
   of 23, against 0.058 and rank 10/18 for "Provisioning". A *total* gap leaves
   no gradient, and with no gradient the visitor stops foraging and diffuses.
2. **77 pages, not 15.** A 40-step walk saturated the old site, so diffusion
   found the target ~50% of the time regardless and swamped every manipulation.

**The design is an interaction, and it is pre-registered** in the generator's
docstring: gate off → footer ≈ nav; gate on → footer < nav. Any single arm
proves nothing, and stating the prediction before running is what makes the
control interpretable.

**The goal wording was selected by measurement, and that should be stated.** I
tested five plausible phrasings and took the one with the strongest gradient;
the first attempt ranked 5th because "my size has come in" pulls toward Apparel
and Footwear. This is legitimate fixture design — the goal is still realistic
user vocabulary and still passes Rule 1 — but it is tuning the fixture against
the model, and a reader should know that rather than assume the goal fell out of
the air.

**Keep Northlake v1.** Its total-gap case is a real phenomenon worth having a
fixture for; it is just not a test of the gate.

### D-021 — Every found rate carries a confidence interval, and overlaps are called inconclusive
**Date:** 2026-09-03 · **Status:** active
`budget.wilson()` gives a 95% Wilson interval; `report()` prints it beside every
found rate, and `--compare` now refuses to interpret a delta whose intervals
overlap, printing INCONCLUSIVE and telling you to raise `--n`.

**Why:** M-006. A bare "40% vs 75%" was reported as an effect when it was 1.5
standard errors of nothing, and the direction reversed at n=100. The tool
printed a number with no indication of its precision, so the noise looked like a
finding — and the previous verdict logic hard-coded `abs(delta) >= 0.15` as
"real", which at n=20 is well inside the noise floor.

**Rule of thumb this encodes:** near p=0.5 the standard error is 0.5/sqrt(n).
n=20 gives +-11 points, n=100 gives +-5. Do not run an intervention comparison
at n < 100 and do not quote a delta smaller than roughly 3/sqrt(n).

### D-020 — Scent is a pluggable batched model
**Date:** 2026-09-03 · **Status:** active
`scent.py` owns `KeywordScent` and `EmbeddingScent` (sentence-transformers
`all-MiniLM-L6-v2`), selected with `--scent`. `policy.score_elements` and
`choose` take a `scent_model`. Keyword remains the default so the project runs
with no model download.

**Batched by element list, not per element**, because embedding wants to encode
a whole page in one call; encodings are cached by text across the run.

**Negative cosines are clamped to 0.** "Actively unrelated" and "unrelated" are
the same thing to a visitor, and a negative would invert the gate — multiplying
by visibility would make a faint irrelevant link outrank a prominent one.

`scent.py` also owns `STOPWORDS` and `tokens`; `policy` and `goals` import them
rather than keeping copies. Three copies of the contrast maths is what produced
D-009, and the stoplist was on its way to the same fate.

### D-019 — Rule 1 is enforced, in two places, as a hard failure
**Date:** 2026-09-03 · **Status:** active, closes the gap D-008 opened
`goals.check` raises `GoalLeak`. Enforced before the run against the target
selector and `--target-label`, and again inside `visit()` against the target's
real accessible name the first time a visitor reaches it — that label is not
knowable in advance. The in-run check aborts the population rather than warning.

**Why two places:** the selector often carries the label (`#collection`), but
not always (`#trail-alerts` for a feature called "Trail Alerts"). Checking only
what is known up front would let the important case through.

**The label is a heading, not `innerText`.** `TARGET_JS` prefers `aria-label`,
then `title`, then a heading inside the element. Targeting a container returns
its entire body copy otherwise, and Rule 1 would reject any goal sharing a word
with the feature's *prose* rather than its *name* — which would have rejected
`PLAN.md`'s own canonical example, since "Trail Alerts" is described as "Save a
search and we will email you...". The rule is about the label being tested.

**`--allow-goal-leak` exists** so old measurements stay reproducible, but it
prints a banner saying the number measures string matching. A silent override
would defeat the point.

**Our own README was violating this**, exactly as D-008 predicted:
`--goal "shop the collection" --target "#collection"` now exits 2.

**Bug found while testing:** the plural stemmer stripped `es` unconditionally,
turning `invoices` into `invoic`, which then failed to match `invoice` — the
check passed a goal that does leak. It now only strips `es` after a sibilant.
A rule that silently under-fires is worse than no rule, since it reads as a
clean bill of health.

### D-018 — Measure perception with patience held off in BOTH arms
**Date:** 2026-09-03 · **Status:** active, fixes a bug in D-012's formula
`--decompose` now runs seven cells, adding `none, no quit`. Perception is
`(gate on, no quit) − (gate off, no quit)`. It used to be
`(gate on, no quit) − (patience-limited baseline)`.

**Why:** that subtraction changed two variables at once — the gate *and*
patience — and silently attributed both to perception. It went unnoticed while
the cap was low because both terms happened to move the same way. At
`--max-steps 400` it broke visibly: the gated no-quit arm scored 90% against a
70% baseline, making the visibility gate look **beneficial**, +20% perception
"damage". The correct control is 100%, so the true figure is −10%.

**How it surfaced:** a convergence check that was only meant to tighten a bound.
The absurd sign was the tell. Worth remembering that the split looked plausible
at every cap that did not expose it — −33%/−20% at 40, −7%/−46% at 120 — and
none of those were right.

**Rule:** when isolating one factor, every other factor must be identical in
both arms. Obvious, and I still got it wrong by reusing a baseline that was
convenient rather than matched.

### D-017 — Settle time is a flag, and it was most of the wall clock
**Date:** 2026-09-03 · **Status:** active
`--settle-ms` (default 200) controls the wait after a navigation and after a
click. These were hardcoded 150 ms and 200 ms.

**Why:** measured 0.25 s per step, essentially all of it these sleeps. The
120-step decomposition was a ~90 minute job and was killed before finishing its
first cell. At `--settle-ms 20` the same run is 4.5x faster.

**Validated, not assumed:** n=30, seed 0, gate on, 40 steps gives byte-identical
outcomes at 200 ms and 20 ms (20% found, 8 quit, same failure modes) — 10.9 s
versus 2.4 s. The wait buys nothing on a static fixture.

**Do not carry the low value to a real site.** The wait exists for pages that
render after `domcontentloaded`; a JS-heavy app observed 20 ms in will look
emptier than it is, and every element that has not painted yet is invisible to
the visitor for the wrong reason. Re-validate per site the same way: same seed,
two settle times, confirm the outcome is unchanged.

This is a partial answer to M2's speed gap. The real fix is running visitors
concurrently, which the per-visitor contexts from D-015 now make possible.

### D-016 — One copy of the colour maths, shared by every JS entry point
**Date:** 2026-09-03 · **Status:** active
`observe.FEATURE_HELPERS_JS` holds `parse`/`bgOf`/`lum`/`contrastOf`/`hidden`.
`OBSERVE_JS` and `TARGET_JS` are both built from it. `visibility.FEATURES_JS`
and `humanbrowser/perceive.py` are deleted (D-004 said they were dead; they
were still on disk).

**Why:** there were three separately maintained copies of the same contrast
calculation. One of them drifted into returning a literal, which is D-009. The
duplication was the root cause, not the constant. A test now asserts the two
surviving entry points return identical features for the same element, so a
future divergence fails rather than silently disabling a channel.

### D-015 — A fresh browser context per visitor
**Date:** 2026-09-03 · **Status:** active
`_run_on` creates and closes a `new_context` per visitor instead of sharing one
page across the whole population.

**Why:** cookies and `localStorage` persisted, so visitor 30 was not a
first-time visitor — the population was measuring a gradually more experienced
user. Every number before M-003 carries this. It also gets us most of the way to
the parallel contexts M2 wants for speed.

### D-014 — Click by stamped handle, not by visible text
**Date:** 2026-09-03 · **Status:** active
`OBSERVE_JS` stamps `data-hb="<i>"` on each element it returns; `visit` clicks
`[data-hb="i"]`. Failures increment `Trace.click_errors` and the report warns
when any occurred.

**Why:** `page.click("text=Save")` picked whichever "Save" came first, or raised
under strict mode when several matched. The exception was swallowed as a dead
end, so a harness failure and a genuine dead end were indistinguishable and both
inflated measured difficulty. Now the click is unambiguous, and the residual
failures are counted rather than silently priced into the metric.

### D-013 — Test invariants, never numbers
**Date:** 2026-09-03 · **Status:** active
`tests/` asserts properties that must hold for the instrument to mean anything.
There is deliberately **no golden-file test pinning a found rate**.

**Why:** a test asserting "found rate is 70%" is satisfied by editing the 70
when it moves, so it protects nothing — and found rates are *supposed* to move
as the model improves. What must not move is the structure: cost stays
scale-invariant in promise (D-006), visibility only ever lowers a score, the
gate stays soft (D-003), flat scent leaves it a no-op (D-007), `detect` never
redirects the visitor (M-002's validity), reasons partition the population.

**`tests/test_browser.py` is not optional.** D-009 lived inside a JS string;
`FakePage` returns canned features and never executes it, so the unit suite is
structurally blind to that whole class of bug. Verified by reintroducing D-009
and confirming three browser tests fail — a test nobody has ever seen fail is a
test nobody should trust.

### D-012 — Report perception and patience damage separately, never merged
**Date:** 2026-08-29 · **Status:** active
`--decompose` splits the gate's found-rate damage into the part that survives
infinite patience (perception) and the part that only appears once patience is
finite (amplification), and flags the perception figure as a lower bound when
any unlimited-patience visitor hit `MAX_STEPS`.

**Why:** the first version of this compared all-on against all-on-no-quit and
concluded "the drop is largely PATIENCE", which is wrong — the `cost` cell shows
patience contributes nothing to the *gate's* effect. Removing patience helps
because low-scent wandering costs actions, not because gating changed the burn
rate. Two different sentences, and the earlier one would have sent us looking
for a bug in `budget.py` that does not exist.

**Amended 2026-09-03 (M-003):** the split is strongly sensitive to
`--max-steps`, so the "lower bound" caveat the report prints is load-bearing,
not a footnote — at cap 40 the split read −33%/−20%, at cap 120 it reads
−7%/−46% on identical inputs. **Do not quote a split while `capped` is nonzero.**
The report already flags it; the flag must be believed.

A further caveat that is not in the code yet: at a cap far above human effort
the "pure perception" figure stops being a behavioural quantity at all. The
ruler puts 31 actions at the 100th percentile, so a visitor still searching at
step 300 is not a model of anybody. The honest claim is the patience-limited
one; the perception limit is a mathematical asymptote, useful for bounding the
mechanism, not for reporting to a customer.

### D-011 — Record *why* a visitor failed, not just that it did
**Date:** 2026-08-29 · **Status:** active
`Outcome.reason` is one of `found | quit | capped | dead_end`.

**Why:** `visit()` returns `found=False` from three different places — patience
exhausted, `MAX_STEPS` hit, nothing clickable — and downstream they were
indistinguishable. A visitor who wandered into the step cap was being reported as
having given up, which is a different finding with a different fix. This also
makes the failure bucket interpretable in every report for free.

### D-010 — The visibility gate is three independent channels, not one boolean
**Date:** 2026-08-29 · **Status:** active
`Gate(detect, choose, cost)` in `run.py`. `--gate` turns on all three;
`--channels detect,choose` runs any subset; `--decompose` runs the isolation
cells.

**Why:** one `gate` flag was threaded into three places that do genuinely
different things, so the −53% in M-001 was unattributable:

| channel | what it changes | is it the effect we want? |
|---|---|---|
| `detect` | what counts as FOUND (`_visible_target`) | **no** — redefines the outcome variable, same path different verdict |
| `choose` | softmax weights in `policy.choose` | **yes** — this is the thesis |
| `cost` | `promise` fed to `budget.spend` | no — patience burn rate |

A found-rate delta that comes from `detect` is close to tautological. One that
comes from `choose` is the product. They needed separating before M3 replaces
the heuristic and bakes the ambiguity in deeper.

### D-009 — `_visible_target` was contrast-blind (bug, not a decision)
**Date:** 2026-08-29 · **Status:** FIXED 2026-09-03 — see D-016, M-003
`run.py` hardcoded `contrast: 12` in the injected JS. It computed `el` and `cs`
on the two preceding lines and then discarded them. `CONTRAST_FULL` is 7, so
`_norm_contrast(12)` clamped to 1.0 and the target's gate check reduced to
area × depth.

**Consequence while it stood: smaller than predicted, and the prediction was
wrong.** M-002 recorded that `detect = 0` was "measuring the bug, not the
design", and predicted the channel would start biting once the constant was
removed. It did not — M-003 measures `detect = 0` again on the fixed code.

The reason is that the target and the faint element are *different elements*.
`#collection` is `<h1 id="collection">The collection</h1>` on `shop.html`: black
on white, above the fold, entirely perceptible. The low-contrast element is the
CTA *link* on `index.html`, which is gated by `choose`, not `detect`. The bug
was real and worth fixing, but it never touched this measurement, because on
this fixture the target is easy to see once you arrive — it is the path to it
that is hard.

**Generalise carefully:** `detect` is not inert. `test_a_low_contrast_target_
fails_the_gate` shows it rejecting a faint target. It contributes nothing *here*
because of what `#collection` is. A fixture whose target is itself buried would
show a different split.

**How it hid for so long:** it was a constant inside a JS string. No Python-level
test can execute that string, so the unit suite is structurally incapable of
seeing this class of bug. That is why `tests/test_browser.py` exists (D-013).

**Fixed by** replacing the ad-hoc probe with `observe.TARGET_JS`, which shares
`FEATURE_HELPERS_JS` with `OBSERVE_JS` so the two cannot disagree again (D-016).

### D-008 — The M1 goal string violates PLAN.md's own Rule 1
**Date:** 2026-08-29 · **Status:** open
Goal `"shop the collection"` against `<a href="/shop.html">Shop the
collection</a>` is a verbatim label match, so `policy.scent` returns exactly 1.0.
`PLAN.md` says sharing a content word with the target's accessible name must be
a hard failure. It is not enforced anywhere (that is M4).

**Why it matters, and why it is not fatal:** M-001 is therefore measured on the
case most favourable to the gate — maximum scent times low visibility is where
the gate has the most room to move the number. Combined with the M2 finding that
a zero-scent goal gives no signal at all (D-007), the two bracket the real
result: **the gate does work in proportion to scent variance**, and keyword
overlap only ever emits 1.0 or 0.0. That is a much stronger argument for M4 than
"polish", and it is the reason M4 blocks M2.

### D-007 — Flat scent makes the gate a no-op; M4 blocks M2
**Date:** 2026-08-28 · **Status:** active
The vocabulary-gap case (goal `"I run this same search every week"`, target
`#trail-alerts` behind a footer link labelled "Provisioning") gives 50%/50%
gate off vs on.

**Why:** `score = scent × visibility`. When every scent is 0, every score is
`FLOOR`, softmax over a flat vector is uniform, and visibility has nothing to
modulate. The gate cannot down-weight what is already uniform.

**Consequence:** embedding scent (M4) is a *prerequisite* for the M2 product
case, not a later refinement. Do not attempt to fix M2 by tuning the gate.

### D-006 — `cost_of` is scale-invariant in promise
**Date:** 2026-08-29 · **Status:** active
`shortfall = (aspiration − promise) / aspiration` is a ratio, and aspiration is
the running mean of the same promises. So multiplying every promise by a
constant leaves cost **exactly** unchanged.

**Why this is worth knowing:** it means gating `promise` does not mechanically
make visitors quit sooner, which was the obvious confound to worry about. Only
*per-page variation* in visibility leaks into the burn rate. Second-order.
This property is worth preserving if `cost_of` is ever rewritten.

### D-005 — Document-wide collection with a position penalty, not a viewport cutoff
**Date:** 2026-08-28 · **Status:** active, supersedes the viewport-scoped approach
`observe.py` collects every matching element in the document and penalises depth,
rather than collecting only what is in the viewport.

**Why:** viewport-only collection made anything below the fold *unreachable* —
the visitor could never click a footer link, so a buried feature scored 0%
whether or not the gate was on, and the comparison was meaningless. This is a
stand-in for modelling scroll as a real action, which is M3 work.

**Dead end recorded:** do not go back to viewport-scoped element collection
without first making scroll an action with a cost.

### D-004 — One JS evaluation per step, not two
**Date:** 2026-08-28 · **Status:** active, supersedes `perceive.py`
`observe.py` collects elements and their visual features in a single
`page.evaluate`. `perceive.py` and `visibility.FEATURES_JS` are the superseded
two-call version and are now dead code.

**Why:** the two passes needed the same element handles, and splitting them
meant re-querying the DOM and re-matching boxes to elements.

### D-003 — Choice is stochastic, gate is soft
**Date:** 2026-08-28 · **Status:** active
Softmax over scores, seeded per visitor; visibility multiplies the score rather
than filtering the element out. `FLOOR = 1e-3` keeps everything nominally
clickable.

**Why:** a hard visibility cutoff makes a buried element *unfindable* rather than
*hard to find*, which collapses the survival curve to 0% or 100% and destroys the
metric. Some people do read footers. Low visibility must mean rarely chosen, not
never chosen. Deterministic choice has the same problem: real visitors on the
same page do not all click the same thing. This is SNIF-ACT's random-utility
rule.

**Keep this property when the pieces get smarter.**

### D-002 — Effort is denominated in human actions, reported as a percentile
**Date:** 2026-08-27 · **Status:** active
Budget = `ruler.budget_at(quantile) × persistence`, read off the Mind2Web
distribution. The headline claim is "costs more than N% of ordinary web tasks",
never a 0–100 score.

**Why:** a made-up 0–100 score is unfalsifiable and invites arguing about the
scale. A percentile against recorded human effort is a claim someone can check.
Mind2Web contains only *completed* tasks, so it calibrates effort under goal
pursuit and says nothing directly about abandonment — the quit threshold is a
modelling choice and every report must label it as one.

### D-001 — The ruler is modelled, not measured
**Date:** 2026-08-27 · **Status:** open — fix is M5
`data/effort_ruler.json` uses the published Mind2Web mean (7.3 actions) with a
log-normal spread, σ = 0.55 assumed because task-effort distributions are
right-skewed and bounded below at 1.

Every percentile in every current report inherits that assumption. Reports must
print `ruler: PROVISIONAL` — `summarize()` carries the flag. Within-instrument
comparisons (this release vs last) are unaffected because the error is shared.

---

## Open questions

Not yet decided. Do not assume an answer.

- **What counts as a page?** Modals, drawers and filter states are not URLs.
  Needs a state-abstraction rule before multi-page crawling means anything.
- **Who is this for?** A CI check for product teams and an audit tool for
  agencies are different products on the same engine.
- **Scent model shape.** Embeddings for scoring every element, LLM for the top
  few, is the current guess. Not tested.

---

## Known defects

Tracked here because they affect the validity of numbers, not just correctness.

**Cleared 2026-09-03:** contrast-blind detection (D-009), state bleed between
visitors (D-015), failed clicks counted as dead ends (D-014), no tests (D-013).
Every measurement before M-003 was taken on the instrument with all four
present, which is why M-001 and M-002 are marked superseded rather than simply
kept.

Still outstanding:

- **The ruler is modelled, not measured** (D-001). Fix is M5. Within-instrument
  comparisons are unaffected; absolute percentiles are not trustworthy.
- **Rule 1 is not enforced** (D-008). Nothing rejects a goal that shares a
  content word with the target's own label, so it is still possible to run a
  string-matching benchmark by accident. M4.
- **Scroll is not an action.** Depth is a static penalty, not a cost the visitor
  pays (D-005). Until it is, "below the fold" is modelled as "less noticeable"
  rather than "reachable but expensive".
- **`--max-steps` is an artificial bound.** When unlimited-patience visitors hit
  it, the perception figure is a lower bound rather than a measurement. The
  report says so when it happens; check that line before quoting a number.
