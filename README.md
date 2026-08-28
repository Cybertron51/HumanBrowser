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

    cd fixtures/northlake && python3 -m http.server 8000 &

    python3 -m humanbrowser.run http://localhost:8000/index.html \
        --goal "shop the collection" --target "#collection" \
        --n 30 --compare --trace

`--compare` runs it twice, with and without the visibility gate, and prints the
difference. On the fixture that is 70% found without the gate, 17% with it.

    python3 -m humanbrowser.ruler show    # the human effort reference table

## Status

M1 done: the loop runs end to end with a cheap visibility gate, and the core
hypothesis passed (−53% found rate when the visitor can only act on what it
would plausibly notice).

Next: M2. Two known gaps — the vocabulary-gap test case gives no signal yet
because keyword scent is flat, and population runs are slow. The effort ruler is
modelled from Mind2Web's published mean, not measured. See PLAN.md.
