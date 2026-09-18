#!/usr/bin/env python3
"""patch_ci_format_recovery.py — hand the files the formatter would rewrite off the runner.

Two things the format check could not see, both found by running it.

1. It only looks at the files a push changes. The three hand-written MCP files
   have been dirty since before the gate existed, and the gate only looked at
   them when a push finally touched them (0d2b475's rename). A file that nobody
   touches is never looked at, so "the check passed" does not mean "the tree is
   formatted" — and the next commit that touches any of those files turns the
   gate red again, which is exactly what happened. This adds a report over the
   whole repository, handed over whether or not the check failed.

2. It could pass without looking at anything. Its diff is taken against
   `github.event.before`, and a commit that a force-push made unreachable is in
   no ref, so the runner's checkout does not have it, so the diff fails — and
   `|| true` on the filtered form swallowed that and reported "No changed Dart
   files to format-check" for a push that changed three. The diff is now kept
   separate from the filter, so a failed diff fails the step.

The report is deliberately not an assertion. It does not fail the job, and on a
clean tree the staged copy is dropped once every file matches, so a green run
leaves no artifact behind — the same reason the l10n step's upload is
failure-only.

Self-checks:

  1. The gate's assertion is unchanged: still `--set-exit-if-changed` over the
     files the push changed, and it still fails the job when they are dirty.
  2. A failed diff can no longer be reported as "nothing to check".
  3. One report step and one upload step, both `always()`, and the stage
     directory is not hidden — upload-artifact@v4 skips dot-directories.
  4. The document still parses, the report follows the check, and no other step
     is touched.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

FORMAT_NAME = "Dart format (changed files only)"
REPORT_NAME = "Stage the files the formatter would rewrite"
UPLOAD_NAME = "Upload the files the formatter would rewrite"
L10N_NAME = "Generate l10n and ensure committed outputs"
ARTIFACT = "dart-format-recovery"

# The `|| true` that swallowed a failed diff. Replaced by two statements so the
# diff's own failure cannot be mistaken for an empty file list.
SWALLOWED = (
    '          files="$(git diff --diff-filter=ACMR --name-only "$BASE_SHA" "$HEAD_SHA"'
    " -- | grep -E '^(lib|test|integration_test)/.*\\.dart$' || true)\"\n"
)
SEPARATED = (
    "          # Kept apart from the filter below on purpose: `|| true` on the filtered\n"
    "          # form turned a failed diff -- a base that a force-push left unreachable,\n"
    "          # for instance -- into \"no changed Dart files\", which is a silent pass.\n"
    '          changed="$(git diff --diff-filter=ACMR --name-only "$BASE_SHA" "$HEAD_SHA" --)"\n'
    "          files=\"$(printf '%s\\n' \"$changed\""
    " | grep -E '^(lib|test|integration_test)/.*\\.dart$' || true)\"\n"
)

L10N_ANCHOR = f"      - name: {L10N_NAME}\n"

REPORT = (
    f"      - name: {REPORT_NAME}\n"
    "        # Not conditional on the check above failing. That check only looks at\n"
    "        # the files this push changed, so a file nobody has touched since the\n"
    "        # gate was added is never looked at -- which is how three files stayed\n"
    "        # unformatted through four pushes, and why this report covers the whole\n"
    "        # repository instead.\n"
    "        #\n"
    "        # A report, not a second assertion: nothing here fails the job, and on a\n"
    "        # clean tree the staged copy is dropped, so a green run hands over\n"
    "        # nothing that could be mistaken for something to commit.\n"
    "        if: always()\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -euo pipefail\n"
    f"          staged={ARTIFACT}\n"
    '          rm -rf "$staged"\n'
    "\n"
    '          dart_files="$(git ls-files -- lib test integration_test | grep -E \'\\.dart$\' || true)"\n'
    '          while IFS= read -r f; do\n'
    '            [ -n "$f" ] || continue\n'
    '            mkdir -p "$staged/$(dirname "$f")"\n'
    '            cp "$f" "$staged/$f"\n'
    '          done <<< "$dart_files"\n'
    "\n"
    "          # --parents is not used above: the loop builds the repository's own\n"
    "          # directory layout, so the artifact can be copied straight back in.\n"
    '          dart format "$staged"\n'
    "\n"
    "          kept=0\n"
    '          while IFS= read -r f; do\n'
    '            rel="${f#"$staged"/}"\n'
    '            if cmp -s "$f" "$rel"; then rm -f "$f"; else kept=$((kept + 1)); fi\n'
    '          done < <(find "$staged" -name \'*.dart\' -type f)\n'
    "\n"
    '          if [ "$kept" -eq 0 ]; then\n'
    '            rm -rf "$staged"\n'
    "            echo 'Every tracked Dart file is already formatted; nothing to hand over.'\n"
    "          else\n"
    '            echo "Handing over $kept file(s) the formatter would rewrite."\n'
    "          fi\n"
    "\n"
    f"      - name: {UPLOAD_NAME}\n"
    "        # `always()` for the same reason the staging is: the formatter's output is\n"
    "        # the only thing here that cannot be produced off the runner. When the\n"
    "        # staging found nothing it removed the directory, so this stays quiet on\n"
    "        # a clean tree instead of leaving a stale artifact to be mistaken for\n"
    "        # current output.\n"
    "        if: always()\n"
    "        uses: actions/upload-artifact@v4\n"
    "        with:\n"
    f"          name: {ARTIFACT}\n"
    f"          path: {ARTIFACT}\n"
    "          if-no-files-found: ignore\n"
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}")
text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
original = text

if f"name: {REPORT_NAME}" in text:
    print("  report step: already applied")
else:
    count = text.count(SWALLOWED)
    check(count == 1, f"the format step's diff line matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(SWALLOWED, SEPARATED, 1)
        print("  format step: the diff is no longer filtered through `|| true`")

    count = text.count(L10N_ANCHOR)
    check(count == 1, f"l10n anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(L10N_ANCHOR, REPORT + L10N_ANCHOR, 1)
        print("  report step: added before the l10n check")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1. The gate still gates.
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

# 2. A failed diff is no longer reported as an empty file list.
check(SWALLOWED not in text, "the diff is still filtered through `|| true`")
check(
    'changed="$(git diff --diff-filter=ACMR --name-only "$BASE_SHA" "$HEAD_SHA" --)"' in text,
    "the diff is not kept separate from the filter",
)

# 3. One report, one upload, both unconditional on the check above.
check(text.count(f"name: {REPORT_NAME}") == 1, "expected exactly one report step")
check(text.count(f"name: {ARTIFACT}") == 1, "expected exactly one upload step")
check(text.count("        if: always()\n") == 2, "both report steps must be unconditional")
check(f"          staged={ARTIFACT}\n" in text, "the stage directory must not be hidden")
check(f".{ARTIFACT}" not in text, "a dotted stage directory uploads nothing")
check(
    'done < <(find "$staged" -name \'*.dart\' -type f)' in text,
    "the staging must drop the files that are already formatted",
)
check("if-no-files-found: ignore" in text, "a clean run must not fail the upload")

# 4. The document still parses, and the steps are ordered.
document = None
try:
    document = yaml.safe_load(text)
except yaml.YAMLError as error:  # pragma: no cover - only on a broken edit
    check(False, f"the workflow no longer parses: {error}")

if isinstance(document, dict):
    steps = document["jobs"]["checks"]["steps"]
    position = {step.get("name"): index for index, step in enumerate(steps)}
    for name in (FORMAT_NAME, REPORT_NAME, UPLOAD_NAME, L10N_NAME):
        check(name in position, f"the parsed workflow is missing the step: {name}")
    if all(name in position for name in (FORMAT_NAME, REPORT_NAME, UPLOAD_NAME, L10N_NAME)):
        check(
            position[FORMAT_NAME] < position[REPORT_NAME] < position[L10N_NAME],
            "the report is not between the format check and the l10n check",
        )
        check(position[REPORT_NAME] < position[UPLOAD_NAME], "the upload is not after the report")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the files the formatter would rewrite are staged and uploaded, unconditionally")