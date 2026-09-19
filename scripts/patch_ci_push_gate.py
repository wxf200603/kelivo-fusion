#!/usr/bin/env python3
"""patch_ci_push_gate.py — let the checks that already exist actually run.

`.github/workflows/pr-check.yml` contains `dart format`, `dart analyze
--fatal-infos` and `flutter test`, and its format step already handles the
non-pull-request case (`github.event.before`). What it lacks is a trigger: it is
`pull_request` only, so the three commits pushed straight to main
(633692f, fa40a15, 26b2e68, 18b7d1a) were never analysed or tested — the green
runs were `build-merged-apk`, which proves the APK compiles and nothing else.

This adds `push` to the same workflow rather than creating a second one: a new
file would carry its own copy of the toolchain setup and the two would drift.

The Kotlin unit tests came in as a probe, because `android/gradlew` is gitignored
(android/.gitignore:1,4,5), nothing in this repository had ever invoked a Kotlin
test, and this job had no JDK step of its own -- so how one would even run was a
question for the runner. The probe answered it: java 17.0.20.1 is present,
`flutter build apk --config-only` writes the wrapper back (gradlew 4971 bytes,
gradle-wrapper.jar 53636 bytes), and
`cd android && ./gradlew :app:testDebugUnitTest --no-daemon` then runs 118 tests.
With the mechanism a fact rather than a guess, the step is a gate, and it lives
here: this is the script whose job is letting the checks that already exist
actually run. It is guarded so only pushes touching android/ pay its ~7 minutes,
and that guard cannot reuse the list the format step computes -- that list is
filtered to `^(lib|test|integration_test)/.*\\.dart$`, so `android/` never appears
in it and a condition built on it would look like a gate and never fire.

Self-checks:

  1. Both triggers are present, on the same branch name the repo uses.
  2. The four checks still exist: the Dart three, and the Kotlin gate.
  3. The android/ guard is extracted from the workflow and run as bash: a change
     under android/ must not skip the tests, a change outside it must skip, and
     the format step's filter must still be unable to serve that purpose.
"""
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

TRIGGER_ANCHOR = "on:\n  pull_request:\n    branches: [main]\n"
TRIGGER_REPLACEMENT = (
    "on:\n"
    "  pull_request:\n"
    "    branches: [main]\n"
    "  # Pushed straight to main, this repository never opened a pull request,\n"
    "  # so analyze/test/format never ran at all. Same workflow, second trigger:\n"
    "  # a separate file would duplicate the toolchain setup and drift from it.\n"
    "  push:\n"
    "    branches: [main]\n"
)

# The Kotlin unit tests, as a gate. They began as a probe -- `continue-on-error`,
# asking the runner how a unit test could run at all -- because `android/gradlew`
# is gitignored (android/.gitignore:1,4,5) and nothing here had ever invoked one.
# The probe answered: java 17.0.20.1 is present, `flutter build apk --config-only`
# writes the wrapper back, and `:app:testDebugUnitTest` then runs 118 tests. With
# the mechanism a fact, the step is a gate, and it is guarded so that only pushes
# touching android/ pay its ~7 minutes.
KOTLIN_ANCHOR = "      - name: flutter test\n        run: flutter test\n"
KOTLIN_STEP = (
    "\n"
    "      - name: Android unit tests (Kotlin)\n"
    "        # A gate, not a probe. The step that preceded this one was a probe, and it\n"
    "        # answered what it was asked: java 17.0.20.1 is present, `android/gradlew` is\n"
    "        # absent on checkout (android/.gitignore:1,4,5),\n"
    "        # `flutter build apk --config-only` writes it back (gradlew 4971 bytes,\n"
    "        # gradle-wrapper.jar 53636 bytes), and\n"
    "        # `cd android && ./gradlew :app:testDebugUnitTest --no-daemon` then runs 118\n"
    "        # tests -- six of which were red until fa018fd fixed the fixtures.\n"
    "        #\n"
    "        # Only pushes that touch android/ pay the ~7 minutes this costs. The list the\n"
    "        # format step computes cannot be reused for that decision: it is filtered to\n"
    "        # `^(lib|test|integration_test)/.*\\.dart$`, so `android/` never appears in it\n"
    "        # and a condition built on it would never fire -- a gate that looks present\n"
    "        # and is not. The list below is computed for this question alone.\n"
    "        shell: bash\n"
    "        run: |\n"
    "          set -uo pipefail\n"
    "\n"
    "          if [ \"${{ github.event_name }}\" = \"pull_request\" ]; then\n"
    "            BASE_SHA=\"${{ github.event.pull_request.base.sha }}\"\n"
    "            HEAD_SHA=\"${{ github.sha }}\"\n"
    "          else\n"
    "            BASE_SHA=\"${{ github.event.before }}\"\n"
    "            HEAD_SHA=\"${{ github.sha }}\"\n"
    "          fi\n"
    "          changed=\"$(git diff --name-only \"$BASE_SHA\" \"$HEAD_SHA\" 2>/dev/null || true)\"\n"
    "          case \"$changed\" in\n"
    "            *android/*) ;;\n"
    "            *)\n"
    "              echo \"no android/ path changed in $BASE_SHA..$HEAD_SHA: skipping the Kotlin unit tests\"\n"
    "              # The skip is the half that can be wrong in silence: on a new branch\n"
    "              # `github.event.before` is all zeros, the diff comes back empty, and\n"
    "              # every run is green with one line saying it skipped. So the skip\n"
    "              # says what it received, and whether the base it diffed against was\n"
    "              # a commit at all -- a skip that should have run is then visible in\n"
    "              # the log rather than inferred from a step that passed. This echo is\n"
    "              # also the marker the patch script keys on: a workflow still carrying\n"
    "              # the silent version is rewritten, not recognised as done.\n"
    "              echo \"changed paths: $(printf '%s\\n' \"$changed\" | grep -c . || true)\"\n"
    "              printf '%s\\n' \"$changed\" | grep . | head -5 | sed 's/^/    /' || true\n"
    "              if ! git rev-parse --verify --quiet \"${BASE_SHA}^{commit}\" >/dev/null 2>&1; then\n"
    "                echo \"base '${BASE_SHA}' is not a commit in this checkout: the diff is empty for that reason, and not because nothing changed\"\n"
    "              fi\n"
    "              exit 0\n"
    "              ;;\n"
    "          esac\n"
    "\n"
    "          echo '--- java ---'\n"
    "          java -version 2>&1 | head -3 || true\n"
    "          echo '--- wrapper before ---'\n"
    "          ls -l android/gradlew android/gradlew.bat android/gradle/wrapper/gradle-wrapper.jar 2>&1 || true\n"
    "          echo '--- config-only ---'\n"
    "          flutter build apk --config-only 2>&1 | tail -5 || true\n"
    "          echo '--- wrapper after ---'\n"
    "          ls -l android/gradlew android/gradle/wrapper/gradle-wrapper.jar 2>&1 || true\n"
    "          echo '--- unit tests ---'\n"
    "          if [ -x android/gradlew ]; then\n"
    "            (cd android && ./gradlew :app:testDebugUnitTest --no-daemon 2>&1 | tail -40)\n"
    "            # `tail -40` can cut the assertion messages off, and those are what say\n"
    "            # why a run is red. They are read back from the report the task leaves\n"
    "            # behind. Both roots are tried: the Flutter plugin re-roots the build\n"
    "            # directory at the repository, the plain Android layout does not.\n"
    "            for report in build/app/test-results/testDebugUnitTest/*.xml \\\n"
    "                          android/app/build/test-results/testDebugUnitTest/*.xml; do\n"
    "              [ -f \"$report\" ] || continue\n"
    "              grep -h -m1 -A3 '<failure' \"$report\" | sed 's/^/    /' || true\n"
    "            done\n"
    "          else\n"
    "            echo 'the wrapper is missing: `flutter build apk --config-only` did not write android/gradlew, so the Kotlin tests cannot run'\n"
    "            exit 1\n"
    "          fi\n"
)

REQUIRED_STEPS = (
    "dart format --output=none --set-exit-if-changed",
    "dart analyze --fatal-infos lib test integration_test",
    "flutter test",
    # The Kotlin gate: that it is present, that it invokes the right task, and that
    # it is still guarded by the android/ condition rather than running everywhere.
    "      - name: Android unit tests (Kotlin)\n",
    ":app:testDebugUnitTest",
    'case "$changed" in\n',
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(WORKFLOW.is_file(), f"missing {WORKFLOW.relative_to(ROOT)}")
text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
original = text

if "  push:\n    branches: [main]\n" in text:
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

# The Kotlin gate goes in after `flutter test`, which keeps the file's order: the
# Dart checks are cheap and run first, the Kotlin one is the seven-minute one.
#
# "Already present" is keyed on the skip diagnostic inside the step, not on the
# step's name. The name was enough while the only thing asked of the step was that
# it exist. Now that the silent skip is the thing being fixed, a workflow carrying
# the silent step has the name and is not done -- keying on the name would leave it
# there and report success, which is the same shape as the hole this script exists
# to catch: something that looks present and never fires.
STEP_NAME = "      - name: Android unit tests (Kotlin)\n"
KOTLIN_DONE = 'echo "changed paths: $(printf'

if KOTLIN_DONE in text:
    print("  kotlin gate: already present")
elif STEP_NAME in text:
    step_lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(step_lines) if line == STEP_NAME)
    end = next(
        (
            i
            for i in range(start + 1, len(step_lines))
            if step_lines[i].startswith("      - name: ")
        ),
        len(step_lines),
    )
    # KOTLIN_STEP opens with the blank line that separates steps; the slot being
    # replaced already sits after that blank line.
    step_lines[start:end] = KOTLIN_STEP.splitlines(keepends=True)[1:]
    text = "".join(step_lines)
    print("  kotlin gate: silent version replaced with one that says what it skipped")
else:
    count = text.count(KOTLIN_ANCHOR)
    check(count == 1, f"flutter-test anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(KOTLIN_ANCHOR, KOTLIN_ANCHOR + KOTLIN_STEP, 1)
        print("  kotlin gate: added after flutter test")

if text != original:
    WORKFLOW.write_text(text, encoding="utf-8")

# 1. Both triggers, same branch as the repository actually uses.
head = text.split("jobs:", 1)[0]
check("pull_request:" in head, "the pull_request trigger disappeared")
check("push:" in head, "the push trigger is missing")
check(head.count("branches: [main]") == 2, "both triggers must target main")

# 2. The gate itself is intact.
for step in REQUIRED_STEPS:
    check(step in text, f"the gate lost a step: {step}")

check(
    "if: ${{ github.event_name == 'pull_request' }}" in text,
    "the PR-only l10n step must stay PR-only",
)

# 3. The android/ guard, run as the shell it will be run as -- on the text that
# is actually in the workflow, not on a copy of it. This is the check that would
# have caught the version of this step that reused the format step's file list:
# that list is filtered to Dart under lib/test/integration_test, so `android/`
# never appears in it and a condition built on it would never fire.
guard_start = [
    index
    for index, line in enumerate(text.splitlines())
    if line.strip() == 'case "$changed" in'
]
check(len(guard_start) == 1, f"the android/ guard appears {len(guard_start)} times (expected 1)")
if len(guard_start) == 1:
    lines = text.splitlines()
    guard_end = next(
        (i for i in range(guard_start[0] + 1, len(lines)) if lines[i].strip() == "esac"),
        None,
    )
    check(guard_end is not None, "the android/ guard has no esac")
    if guard_end is not None:
        # Dedented: the workflow's copy carries the step's indentation.
        guard = "\n".join(
            line.strip() for line in lines[guard_start[0] : guard_end + 1]
        ) + "\n"

        # Run as it runs on the runner: the two SHAs the step reads are given to
        # it, rather than left unset, so what is exercised is the guard and not
        # bash's treatment of an empty variable.
        def guard_run(changed: str, base: str = "0" * 40, head: str = "deadbeef") -> str:
            run = subprocess.run(
                [
                    "bash",
                    "-c",
                    f"changed={shlex.quote(changed)}\n"
                    f"BASE_SHA={shlex.quote(base)}\n"
                    f"HEAD_SHA={shlex.quote(head)}\n" + guard,
                ],
                capture_output=True,
                text=True,
            )
            return run.stdout + run.stderr

        def guard_skips(changed: str) -> bool:
            return "skipping the Kotlin unit tests" in guard_run(changed)

        check(
            not guard_skips(
                "android/app/src/main/kotlin/com/psyche/kelivo/MainActivity.kt\nlib/main.dart"
            ),
            "a push that changed android/ would still skip the Kotlin tests",
        )
        check(
            not guard_skips("android/gradle.properties"),
            "a change to android/gradle.properties would still skip the Kotlin tests",
        )
        check(
            guard_skips("lib/main.dart\ntest/foo_test.dart"),
            "a push that changed only lib/ and test/ would run the Kotlin tests anyway",
        )
        check(
            guard_skips(""),
            "an empty change set would run the Kotlin tests anyway",
        )

        # And the skip is not silent. A guard whose only two outcomes are "ran"
        # and "said nothing" cannot be told from a guard that is broken: every run
        # is green and the log agrees with whichever reading the reader prefers.
        # So the skip reports what it diffed and what it received, and a base that
        # is not a commit -- all zeros on a new branch, which is the shape that
        # would silently skip forever -- is called out as the reason.
        skip_log = guard_run("lib/main.dart")
        check(
            "changed paths: 1" in skip_log,
            "the skip does not report how many paths it received",
        )
        check(
            "    lib/main.dart" in skip_log,
            "the skip does not show the paths it received",
        )
        check(
            "is not a commit in this checkout" in skip_log,
            "an all-zeros base skips without saying it is not a commit",
        )
        check(
            "changed paths:" not in guard_run("android/gradle.properties"),
            "the path that runs the tests also prints the skip diagnostic",
        )

# 4. And the reuse that would have looked right is impossible -- which is what the
# comment above the guard claims.
FORMAT_FILTER = "grep -E '^(lib|test|integration_test)/.*\\.dart$'"


def format_filter_keeps(path: str) -> bool:
    run = subprocess.run(
        ["bash", "-c", f"printf '%s\\n' {shlex.quote(path)} | {FORMAT_FILTER}"],
        capture_output=True,
        text=True,
    )
    return run.stdout.strip() != ""


check(
    not format_filter_keeps("android/app/src/main/kotlin/com/psyche/kelivo/MainActivity.kt"),
    "the format step's filter does keep android/ -- so the note in the step is wrong",
)
check(
    format_filter_keeps("lib/main.dart"),
    "the format step's filter no longer keeps Dart under lib/",
)

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: analyze / test / format, and the android/-guarded Kotlin unit tests, run on every push to main")
print("  (the Kotlin step skips itself when the push does not touch android/)")