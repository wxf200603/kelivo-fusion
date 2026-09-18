#!/usr/bin/env python3
"""patch_ci_format_recovery.py — hand the formatted files off the runner.

The gate's format step fails because three files it now has to look at are not
`dart format`-clean:

  lib/core/services/mcp/server/mcp_http_transport.dart
  lib/core/services/mcp/server/mcp_server_engine.dart
  lib/core/services/mcp/server/mcp_workspace_tools.dart

They were written by hand, in an environment with no Dart toolchain, and the
check only ever looks at the files a push touched — so they first came into its
scope in the commit that renamed their `_diag` field to a public `diag`. The
same push's fourth Dart file, `lib/main.dart`, was *not* reported as changed,
and that comparison is the evidence: the drift is in those three files, not in
the rename.

Committing the formatter's output means producing it, and this proot has no
Flutter. Rebuilding it by eye is the mistake `patch_ci_l10n_recovery.py` already
documents — an exact-output generator is not something to reconstruct from a
log. So the runner is asked for the files, the same way, with three differences
that are not accidents:

  * The staged copy keeps the repository's directory layout, because the set to
    hand over is whatever the push touched, not one directory with a known name.
  * The stage directory is `dart-format-recovery`, not `.dart-format-recovery`:
    upload-artifact@v4 skips hidden files by default and everything under a
    dot-directory counts as hidden, so a dotted stage would upload nothing.
  * Both recovery steps are keyed to the format step's own outcome *as well as*
    to `failure()`. The status function is not optional and its absence is not
    cosmetic: a step-level `if` without one is ANDed with an implicit
    `success()`, so the first version of this condition could never be true. The
    note above OLD_GATED carries the run that demonstrated it. The `steps.` half
    keeps the hand-off narrower than the l10n step's plain `failure()`, so a red
    `flutter test` cannot hand over a formatting artifact that looks like the
    reason the run is red.

Self-checks:

  1. The format check itself is untouched — still `--set-exit-if-changed` over
     the changed files, so this stays a gate rather than a way past one.
  2. Exactly one stage step and one upload step, and neither is gated without a
     status function.
  3. The stage keeps repository paths, and is not hidden.
  4. The document still parses, the format step kept its id, and the recovery
     sits between the format check and the l10n check.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

FORMAT_STEP = "      - name: Dart format (changed files only)\n        shell: bash\n"
FORMAT_STEP_WITH_ID = (
    "      - name: Dart format (changed files only)\n"
    "        id: dart-format\n"
    "        shell: bash\n"
)

# A step-level `if` that names no status function is ANDed with an implicit
# `success()`, so `steps.dart-format.outcome == 'failure'` on its own can never
# be true: the only run in which it would matter is one where a step failed.
# This script shipped that condition first, and the job said so out loud --
# `Dart format (changed files only): completed/failure` with both steps below it
# `completed/skipped`, next to the l10n step's plain `failure()` succeeding.
# Naming a status function is what turns the implicit check off; `failure()` is
# also the truthful half of the intent, and the `steps.` half is what keeps this
# narrower than the l10n step's upload.
OLD_GATED = "        if: steps.dart-format.outcome == 'failure'\n"
# Kept apart from `GATED` so the parsed-document check below can compare the
# YAML *value* rather than a slice of the line: stripping the leading whitespace
# off `GATED` leaves the `if: ` key in place, and no parsed value ever has it.
GATE_CONDITION = "failure() && steps.dart-format.outcome == 'failure'"
GATED = f"        if: {GATE_CONDITION}\n"

STAGE_STEP = "Stage the files dart format wants to change"
UPLOAD_STEP = "Upload the files dart format wants to change"
L10N_STEP = "Generate l10n and ensure committed outputs"
FORMAT_NAME = "Dart format (changed files only)"

L10N_ANCHOR = f"      - name: {L10N_STEP}\n"

RECOVERY = (
    f"      - name: {STAGE_STEP}\n"
    "        # Same hand-off as the l10n step below, for the same reason: this\n"
    "        # proot has no Flutter, so the formatter's output can only be\n"
    "        # produced on the runner. The staged copy keeps the repository's\n"
    "        # directories, so it can be copied straight back in.\n"
    "        if: steps.dart-format.outcome == 'failure'\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -euo pipefail\n"
    "          if [ \"${{ github.event_name }}\" = \"pull_request\" ]; then\n"
    "            BASE_SHA=\"${{ github.event.pull_request.base.sha }}\"\n"
    "            HEAD_SHA=\"${{ github.sha }}\"\n"
    "          else\n"
    "            BASE_SHA=\"${{ github.event.before }}\"\n"
    "            HEAD_SHA=\"${{ github.sha }}\"\n"
    "          fi\n"
    "          files=\"$(git diff --diff-filter=ACMR --name-only \"$BASE_SHA\" \"$HEAD_SHA\""
    " -- | grep -E '^(lib|test|integration_test)/.*\\.dart$' || true)\"\n"
    "          if [ -z \"$files\" ]; then\n"
    "            echo 'Nothing to hand over.'\n"
    "            exit 0\n"
    "          fi\n"
    "          staged=dart-format-recovery\n"
    "          rm -rf \"$staged\"\n"
    "          for f in $files; do\n"
    "            mkdir -p \"$staged/$(dirname \"$f\")\"\n"
    "            cp \"$f\" \"$staged/$f\"\n"
    "          done\n"
    "          dart format \"$staged\"\n"
    "\n"
    f"      - name: {UPLOAD_STEP}\n"
    "        # failure-only in effect: the format step's outcome is only\n"
    "        # 'failure' when the check above failed, and an always-on upload\n"
    "        # would leave a stale artifact behind.\n"
    "        if: steps.dart-format.outcome == 'failure'\n"
    "        uses: actions/upload-artifact@v4\n"
    "        with:\n"
    "          name: dart-format-recovery\n"
    "          path: dart-format-recovery\n"
    "\n"
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}")
text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
original = text

# The condition the first version of this carried can never be true, for the
# reason noted above OLD_GATED. It is migrated here rather than in a second
# script because the idempotent marker below is already in the file, so anything
# guarded by it would be skipped rather than repaired.
if OLD_GATED in text:
    count = text.count(OLD_GATED)
    check(count == 2, f"old gate condition matched {count} times (expected exactly 2)")
    if count == 2:
        text = text.replace(OLD_GATED, GATED)
        print("  gate condition: made status-aware")

# The format check needs a name of its own, so the recovery can key off it
# instead of off "some step in the job failed".
if "id: dart-format" in text:
    print("  format step id: already applied")
else:
    count = text.count(FORMAT_STEP)
    check(count == 1, f"format step anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(FORMAT_STEP, FORMAT_STEP_WITH_ID, 1)
        print("  format step id: added")

# Inserted before the l10n check: that keeps the hand-off adjacent to the step
# it belongs to, without touching the check that follows it.
if "dart-format-recovery" in text:
    print("  recovery steps: already applied")
else:
    count = text.count(L10N_ANCHOR)
    check(count == 1, f"l10n anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(L10N_ANCHOR, RECOVERY + L10N_ANCHOR, 1)
        print("  recovery steps: added before the l10n check")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1. The gate still gates, and did not lose a step.
check(
    "dart format --output=none --set-exit-if-changed $files" in text,
    "the format check lost --set-exit-if-changed",
)
for step in (
    "dart analyze --fatal-infos lib test integration_test",
    "flutter test",
    "git diff --exit-code -- lib/l10n",
):
    check(step in text, f"the gate lost a step: {step}")

# 2. One stage step, one upload step, neither keyed without a status function.
check(text.count(f"name: {STAGE_STEP}") == 1, "expected exactly one stage step")
check(text.count("name: dart-format-recovery") == 1, "expected exactly one upload step")
check(text.count(OLD_GATED) == 0, "a step is still gated without a status function")
check(
    text.count(GATED) == 2,
    f"both recovery steps must be gated on the format step (found {text.count(GATED)})",
)

# 3. The stage keeps repository paths, and is not hidden.
check("staged=dart-format-recovery\n" in text, "the stage directory must not be hidden")
check(
    'mkdir -p "$staged/$(dirname "$f")"' in text,
    "the stage must keep the repository's directories",
)
check(".dart-format-recovery" not in text, "a dotted stage directory uploads nothing")

# 4. The document still parses, and the steps are ordered format -> recovery ->
#    l10n.
document = None
try:
    document = yaml.safe_load(text)
except yaml.YAMLError as error:  # pragma: no cover - only on a broken edit
    check(False, f"the workflow no longer parses: {error}")

if isinstance(document, dict):
    steps = document["jobs"]["checks"]["steps"]
    position = {step.get("name"): index for index, step in enumerate(steps)}
    for name in (FORMAT_NAME, STAGE_STEP, UPLOAD_STEP, L10N_STEP):
        check(name in position, f"the parsed workflow is missing the step: {name}")
    if all(name in position for name in (FORMAT_NAME, STAGE_STEP, UPLOAD_STEP, L10N_STEP)):
        check(
            position[FORMAT_NAME] < position[STAGE_STEP] < position[L10N_STEP],
            "the recovery steps are not between the format check and the l10n check",
        )
        check(position[STAGE_STEP] < position[UPLOAD_STEP], "the upload is not after the stage")
        check(
            steps[position[FORMAT_NAME]].get("id") == "dart-format",
            "the format step lost its id",
        )
        check(
            steps[position[STAGE_STEP]].get("if") == GATE_CONDITION,
            "the stage step is not keyed to the format step",
        )
        check(
            steps[position[UPLOAD_STEP]].get("with", {}).get("path") == "dart-format-recovery",
            "the upload does not point at the stage directory",
        )

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the files dart format wants to change are now staged and uploaded")