#!/usr/bin/env bash
# Stop hook: refuse to end a turn that changed the instrument without recording why.
#
# The whole point of DECISIONS.md is that we never re-run an experiment or
# re-argue a choice. That only works if it is written at the moment the decision
# is made, which is exactly when it feels least necessary.
#
# Fires at most once per distinct set of changes, so it nags but cannot loop.
set -uo pipefail

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$root" || exit 0
[ -f DECISIONS.md ] || exit 0

# Changes to the instrument itself, or to the plan. Fixtures and docs are exempt.
changed=$(git status --porcelain -- '*.py' 'data/*.json' PLAN.md 2>/dev/null)
[ -z "$changed" ] && exit 0

# Already logged? Then nothing to do.
git status --porcelain -- DECISIONS.md 2>/dev/null | grep -q . && exit 0

# Nag once per distinct change set, never twice.
stamp_dir="${TMPDIR:-/tmp}/humanbrowser-decisions-guard"
mkdir -p "$stamp_dir" 2>/dev/null || exit 0
key=$(printf '%s' "$changed" | shasum 2>/dev/null | cut -d' ' -f1)
[ -z "$key" ] && exit 0
[ -f "$stamp_dir/$key" ] && exit 0
touch "$stamp_dir/$key"

files=$(printf '%s' "$changed" | awk '{print $2}' | paste -sd' ' -)

cat <<EOF
{"decision":"block","reason":"You changed the instrument ($files) but did not touch DECISIONS.md.\n\nIf this change embodies a choice, a dead end, or a measured result, add an entry now (D-nnn for a decision, M-nnn for a measurement) and say what it supersedes. Include the WHY -- an entry that only says what changed saves nobody any time.\n\nIf it is a pure refactor, a typo, or a mechanical fix with no judgement in it, say so in one line and stop. This check fires once per change set, so it will not ask again."}
EOF
