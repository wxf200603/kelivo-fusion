#!/usr/bin/env python3
"""patch_ci_push_gate.py — let the checks that already exist actually run.

`.github/workflows/pr-check.yml` contains `dart format`, `dart analyze
--fatal-infos` and `flutter test`, and its format step already handles the
non-pull-request case (`github.event.before`). What it lacks is a trigger: it is
`pull_request` only, so the three commits pushed straight to master
(633692f, fa40a15, 26b2e68, 18b7d1a) were never analysed or tested — the green
runs were `build-merged-apk`, which proves the APK compiles and nothing else.

This adds `push` to the same workflow rather than creating a second one: a new
file would carry its own copy of the toolchain setup and the two would drift.

The Kotlin unit-test step is deliberately *not* added here. There are no Kotlin
tests yet, so the step would report NO-SOURCE and prove nothing; it lands with
the first real test and its junit dependency, in the commit that adds the
org.hjson parsing.

Self-checks:

  1. Both triggers are present, on the same branch name the repo uses.
  2. The three checks still exist — this commit must not weaken the gate.
  3. Nothing else in the file moved.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

TRIGGER_ANCHOR = "on:\n  pull_request:\n    branches: [master]\n"
TRIGGER_REPLACEMENT = (
    "on:\n"
    "  pull_request:\n"
    "    branches: [master]\n"
    "  # Pushed straight to master, this repository never opened a pull request,\n"
    "  # so analyze/test/format never ran at all. Same workflow, second trigger:\n"
    "  # a separate file would duplicate the toolchain setup and drift from it.\n"
    "  push:\n"
    "    branches: [master]\n"
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

if "  push:\n    branches: [master]\n" in text:
    print("  trigger: already applied")
else:
    lines = text.splitlines(keepends=True)
    needle = TRIGGER_ANCHOR.splitlines(keepends=True)
    width = len(needle)
    hits = [
        index
        for index in range(len(lines) - width + 1)
        if lines[index:index + width] == needle
    ]
    check(len(hits) == 1, f"trigger anchor matched {len(hits)} times (expected exactly 1)")
    if len(hits) == 1:
        lines[hits[0]:hits[0] + width] = TRIGGER_REPLACEMENT.splitlines(keepends=True)
        text = "".join(lines)
        print("  trigger: push added alongside pull_request")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1. Both triggers, same branch as the repository actually uses.
head = text.split("jobs:", 1)[0]
check("pull_request:" in head, "the pull_request trigger disappeared")
check("push:" in head, "the push trigger is missing")
check(head.count("branches: [master]") == 2, "both triggers must target master")

# 2. The gate itself is intact.
for step in REQUIRED_STEPS:
    check(step in text, f"the gate lost a step: {step}")

check(
    "if: ${{ github.event_name == 'pull_request' }}" in text,
    "the PR-only l10n step must stay PR-only",
)

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: analyze / test / format now run on every push to master")
print("  (kotlin unit tests arrive with the first kotlin test, not as an empty step)")