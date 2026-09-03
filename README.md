# HumanBrowser

Measures how hard a feature is for a human to find.

A population of simulated visitors is turned loose on your site with a goal
phrased the way a user would think about it. Each has a limited appetite for
effort, denominated in real human actions, and each can give up. The output is
a discoverability number you can track across releases.

    found                41%
    median cost to find  14 actions  ->  93rd percentile of human task effort
    quit before finding  59%, median 9 actions in

See `PLAN.md` for the build plan and `RESEARCH.md` for the landscape.

## Quick start

    pip install playwright && playwright install chromium
    pip install sentence-transformers          # optional, for --scent embedding

    python3 fixtures/build_northlake2.py
    cd fixtures/northlake2/footer && python3 -m http.server 8002 &

    python3 -m humanbrowser.run http://localhost:8002/index.html \
        --goal "is there a way to be notified when an item I want is available again" \
        --target "#restock-signup" --n 100 --scent embedding --compare

## The goal must not contain the words you are testing

If the goal is "find Trail Alerts" and the feature is called Trail Alerts, you
have built a string matcher and it will report that everything is easy. Goals
are phrased the way a user who does not know the feature's name would ask.

This is enforced, not advised. A goal sharing a content word with the target's
selector, its `--target-label`, or its real accessible name exits 2:

    GOAL LEAK
    Goal 'shop the collection' shares 'collection' with '#collection'

`--allow-goal-leak` overrides it for reproducing old measurements, and marks
every report it produces.

`--compare` runs it twice, with and without the visibility gate, and prints the
difference.

The gate is three independent channels, because bundling them behind one flag
makes a found-rate delta unattributable:

    --channels detect,choose,cost   # any subset
    --decompose                     # run the isolation cells and attribute the delta
    --no-quit                       # unlimited patience, to separate perception from patience

`--decompose` is the one to reach for. `detect` changes what counts as *found*,
`choose` changes what gets clicked, `cost` changes how fast patience burns —
only the middle one is the thing this project claims to measure.

Scent — how much a link looks like it leads to the goal — is pluggable:

    --scent keyword     word overlap. Fast, no dependency, deliberately crude.
    --scent embedding   sentence-transformer cosine. Continuous, so the
                        visibility gate has something to weight.

    python3 -m humanbrowser.ruler show    # the human effort reference table

## Read the confidence intervals

Every found rate is k successes out of n visitors, printed with a 95% interval.
Near 50%, n=20 is about ±22 points and n=100 about ±10. `--compare` refuses to
interpret a delta whose intervals overlap.

This is not decoration. A 40% → 75% "effect" measured here at n=20 reversed
direction at n=100 (M-006 in `DECISIONS.md`). Do not run an intervention
comparison at n < 100, and expect to need n ≈ 300 for a ten-point difference.

## Tests

    pip install pytest && python3 -m pytest

They assert invariants, not numbers: no golden-file test pins a found rate,
because found rates are meant to move as the model improves. What must not move
is the structure — cost stays scale-invariant in promise, visibility only ever
lowers a score, the gate stays soft rather than becoming a filter, and the
detection channel never redirects the visitor.

`pytest -m browser` runs the subset needing real Chromium. Those are not
optional: the perception code lives in injected JavaScript, and no Python-level
test can execute it. A hardcoded constant hid in there for a week.

## Status

M1, M2 and M4 done. M4 was taken before M3, reversing the order in `PLAN.md`:
the gate can only do work in proportion to how much scent varies, so sharpening
scent was the binding constraint, not the saliency model.

Two results worth knowing before reading anything else:

**The gate's whole effect runs through what the visitor clicks** (M-002 to
M-004). Detection and patience burn rate each measure exactly zero. Making an
element imperceptible costs about 10 points of reachability and multiplies the
cost of finding it by **66x** — the feature stays findable, and nobody finds it,
which is precisely what a funnel cannot show you.

**A design change can be scored before shipping it** (M-008). Moving one link
from the footer into the main nav raises the found rate by **+10% (p=0.017,
n=300, replicated)**. With the visibility gate switched off the same move does
nothing at all — as it must, since nothing in the model can then see position.

Next: M3, the real saliency model, and M5 validation. The effort ruler is still
modelled rather than measured, so absolute percentiles are not yet trustworthy;
within-instrument comparisons are unaffected.

`DECISIONS.md` records what is settled, what was tried and abandoned, and which
predictions turned out wrong. Read it before proposing changes — several
obvious-looking ideas are in there with the reason they failed.
