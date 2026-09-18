#!/usr/bin/env python3
"""patch_ci_l10n_recovery.py — hand the stale l10n output off the runner.

The gate's l10n step fails because the committed generated output is missing 672
lines that `flutter gen-l10n` produces (3 files, 5 hunks, +672/-0). Fixing that
means committing the generator's output — and this proot has no Flutter, so the
files can only be produced on the runner.

Recovering them by parsing `git diff` out of the job log was attempted first and
abandoned: the reconstructed patch failed `git apply --check` with "corrupt
patch at line 443". A generator's output is not something to rebuild by eye from
a log, so the runner is asked for the files instead.

The upload is on `failure()` deliberately: a passing run has nothing to hand
over, and an always-on upload would leave a stale artifact to be mistaken for
current.

Self-checks:

  1. The step is present exactly once, and is failure-only.
  2. The l10n check itself is unchanged — the gate must still fail when the
     output is stale, otherwise this becomes a way to ignore the problem.
  3. The other checks are still there.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

ANCHOR = (
    "      - name: Generate l10n and ensure committed outputs\n"
    "        run: |\n"
    "          flutter gen-l10n\n"
    "          git diff --exit-code -- lib/l10n\n"
)

RECOVERY = (
    "\n"
    "      - name: Upload the stale l10n output\n"
    "        # This proot has no Flutter, so when the check above fails the\n"
    "        # regenerated files have to come off the runner to be committed.\n"
    "        # failure() only: a passing run has nothing to hand over, and an\n"
    "        # always-on upload would leave a stale artifact behind.\n"
    "        if: failure()\n"
    "        uses: actions/upload-artifact@v4\n"
    "        with:\n"
    "          name: lib-l10n-regenerated\n"
    "          path: lib/l10n\n"
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}")
text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
original = text

if "lib-l10n-regenerated" in text:
    print("  recovery upload: already applied")
else:
    count = text.count(ANCHOR)
    check(count == 1, f"l10n step anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(ANCHOR, ANCHOR + RECOVERY, 1)
        print("  recovery upload: added after the l10n check")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1. One failure-only upload.
check(text.count("name: lib-l10n-regenerated") == 1, "expected exactly one upload step")
check(
    "        if: failure()\n        uses: actions/upload-artifact@v4" in text,
    "the upload must be failure-only",
)

# 2. The check still fails on stale output.
check("git diff --exit-code -- lib/l10n" in text, "the l10n check lost its assertion")
check("flutter gen-l10n" in text, "the generator invocation disappeared")

# 3. Nothing else moved.
for step in (
    "dart format --output=none --set-exit-if-changed",
    "dart analyze --fatal-infos lib test integration_test",
    "flutter test",
):
    check(step in text, f"the gate lost a step: {step}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: a stale l10n output is now uploaded so it can be committed verbatim")
print("  (the check still fails; this only makes the fix possible off-runner)")