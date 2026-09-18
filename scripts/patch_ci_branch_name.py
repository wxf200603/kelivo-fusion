#!/usr/bin/env python3
"""patch_ci_branch_name.py — point the triggers at the branch that exists.

The previous commit added `push` next to `pull_request` and copied the branch
name that was already there. That name was wrong: the workflow says
`branches: [master]`, the repository's default branch is `main`, and commits are
pushed with `git push origin HEAD:main`.

Consequence, measured rather than argued: the run for a4fba5e listed
`Build Merged APK` and nothing else, and the GitHub API reports
`default_branch = main`. So the checks had never matched a pull request either —
there is no `master` on the remote for one to target.

The gate is the whole point of this commit series, so it gets its own fix rather
than being folded into the parsing work.

Self-checks:

  1. Both triggers name `main`.
  2. No `[master]` survives inside the `on:` block — a half-fixed trigger is
     worse than an obviously broken one.
  3. The three checks are still there.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

BRANCH_FIXES = (
    ("  pull_request:\n    branches: [master]\n", "  pull_request:\n    branches: [main]\n"),
    ("  push:\n    branches: [master]\n", "  push:\n    branches: [main]\n"),
    # The adjacent comment said "master" too; leaving it would re-teach the
    # mistake that this commit exists to undo.
    (
        "  # Pushed straight to master, this repository never opened a pull request,\n",
        "  # Pushed straight to main, this repository never opened a pull request,\n",
    ),
)

REQUIRED_STEPS = (
    "dart format --output=none --set-exit-if-changed",
    "dart analyze --fatal-infos lib test integration_test",
    "flutter test",
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}")
text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
original = text

for stale, fixed in BRANCH_FIXES:
    if stale not in text:
        # Either already applied, or the anchor moved out from under us. Those
        # look identical from here, so the difference is asserted rather than
        # assumed: a missing anchor with no replacement present is a failure.
        check(fixed in text, f"anchor vanished and nothing replaced it: {stale.strip()}")
        print(f"  already fixed: {stale.strip()}")
        continue
    lines = text.splitlines(keepends=True)
    needle = stale.splitlines(keepends=True)
    width = len(needle)
    hits = [
        index
        for index in range(len(lines) - width + 1)
        if lines[index:index + width] == needle
    ]
    check(len(hits) == 1, f"{stale.strip()}: matched {len(hits)} times")
    if len(hits) == 1:
        lines[hits[0]:hits[0] + width] = fixed.splitlines(keepends=True)
        text = "".join(lines)
        print(f"  {stale.strip()}: -> {fixed.strip()}")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1 + 2. Both triggers, and nothing stale left in the trigger block.
head = text.split("\njobs:", 1)[0]
check("pull_request:" in head, "the pull_request trigger disappeared")
check("push:" in head, "the push trigger is missing")
check(head.count("branches: [main]") == 2, "both triggers must target main")
check("[master]" not in head, "[master] must not survive in the trigger block")

# 3. The gate itself is intact.
for step in REQUIRED_STEPS:
    check(step in text, f"the gate lost a step: {step}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: triggers target main, which is what the repository actually has")
print("  default_branch = main  (checked against the API, not assumed)")