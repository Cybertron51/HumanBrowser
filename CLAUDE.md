# HumanBrowser

Measures how hard a feature is for a human to find. `PLAN.md` is the roadmap,
`RESEARCH.md` the landscape, `DECISIONS.md` the record of what we have settled.

## Read DECISIONS.md before proposing anything

It records choices already made, dead ends already hit, and numbers already
measured. Check it before suggesting a change to the instrument — several
obvious-looking ideas are in there with the reason they were abandoned.

## Log decisions as you make them

**Write a `DECISIONS.md` entry in the same turn as the change it explains.** A
Stop hook enforces this: if a `.py` file, `data/*.json`, or `PLAN.md` changes
and `DECISIONS.md` does not, the turn is blocked once with a reminder.

Log an entry when you:

- make a non-obvious call, or pick one approach over another
- kill an idea, or find that something does not work — **especially this**;
  a recorded dead end is what stops it being retried in three months
- measure something (a found rate, a delta, a timing)
- find a defect that affects the validity of a number, not just correctness

Use `D-nnn` for decisions, `M-nnn` for measurements. Newest first. Always give
the **why** — an entry that says only what changed saves nobody any time. When a
new entry overturns an old one, mark the old one `superseded by D-nnn` and leave
it in place; the reversal is the useful part.

Pure refactors, typos and mechanical fixes need no entry.

## Working notes

- The metric is a percentile against recorded human effort, never a 0-100 score.
- Reports must print `ruler: PROVISIONAL` until the ruler is measured (M5).
- Run the fixture with `.venv/bin/python`; `fixtures/northlake` needs a local
  server on port 8000.
