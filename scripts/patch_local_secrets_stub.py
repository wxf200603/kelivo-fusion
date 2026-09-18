#!/usr/bin/env python3
"""patch_local_secrets_stub.py — make a fresh clone compile.

`lib/secrets/fallback.dart` is gitignored (.gitignore:63) because it is where a
developer's own key lives, but two files import it unconditionally
(model_provider.dart:13, chat_api_helpers.dart:5). So `dart analyze` fails on
every fresh checkout and in CI — 4 of the 8 issues the new gate reports are this
one missing file:

    error - lib/core/providers/model_provider.dart:13:8 - Target of URI doesn't
            exist: 'package:Kelivo/secrets/fallback.dart'

It is a stub, not a secret store: the value is an empty-ish placeholder and the
fallback is optional by design. So the fix is not to inject a key in CI (that
would give CI and a local checkout different semantics) but to commit the stub
and copy it into place, the same way in both environments:

  tool/stubs/fallback.dart      committed, auditable, empty key
  tool/setup_local_secrets.sh   copies it to the gitignored path
  AGENTS.md                     says to run it after cloning
  pr-check.yml                  runs it before analyze

The real value never enters the repository, and .gitignore keeps protecting the
developer's own copy.

Self-checks:

  1. The stub is exactly the agreed text and its key is empty.
  2. No `sk-` string is written anywhere by this script — the whole point is
     that no key is committed.
  3. The setup script is executable and references the committed stub.
  4. CI runs the setup before analyze; AGENTS.md tells a human the same thing.
"""
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "tool/stubs/fallback.dart"
SETUP = ROOT / "tool/setup_local_secrets.sh"
AGENTS = ROOT / "AGENTS.md"
WORKFLOW = ROOT / ".github/workflows/pr-check.yml"

STUB_TEXT = (
    "// Local stub. Replace with your own key if you need the fallback.\n"
    "const String siliconflowFallbackKey = '';\n"
)

SETUP_TEXT = """#!/usr/bin/env bash
# Creates lib/secrets/fallback.dart from the committed stub.
#
# lib/secrets/ is gitignored, because that is where a developer's own key lives.
# A fresh clone therefore has no such file, and `dart analyze` fails on the
# unconditional imports in model_provider.dart and chat_api_helpers.dart. Run
# this once after cloning; the tree then compiles with an empty fallback.
#
# Overwrite lib/secrets/fallback.dart with your own key if you want the fallback
# to actually fire. Nothing here ever puts a key in version control.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
stub="$here/stubs/fallback.dart"
target="$here/../lib/secrets/fallback.dart"

if [ ! -f "$stub" ]; then
  echo "missing $stub" >&2
  exit 1
fi

mkdir -p "$(dirname "$target")"
cp "$stub" "$target"
echo "wrote $target from $stub"
"""

AGENTS_ANCHOR = (
    "The analyzer excludes `dependencies/flutter_math_fork/**` and "
    "`dependencies/flutter_tts/**`.\n"
    "\n"
    "## Useful commands\n"
)
AGENTS_REPLACEMENT = (
    "The analyzer excludes `dependencies/flutter_math_fork/**` and "
    "`dependencies/flutter_tts/**`.\n"
    "\n"
    "`lib/secrets/fallback.dart` is gitignored, so a fresh clone does not compile: "
    "two files import it unconditionally. Run `tool/setup_local_secrets.sh` after "
    "cloning to copy the committed stub (`tool/stubs/fallback.dart`, empty key) into "
    "place; overwrite it with your own key if you need the fallback to fire.\n"
    "\n"
    "## Useful commands\n"
)

COMMANDS_ANCHOR = (
    "flutter pub get                             # install dependencies\n"
    "flutter gen-l10n                            # regenerate l10n files\n"
    "dart run build_runner build                 # regenerate Drift code\n"
)
COMMANDS_REPLACEMENT = COMMANDS_ANCHOR + (
    "tool/setup_local_secrets.sh                 # create lib/secrets/fallback.dart\n"
)

CI_ANCHOR = (
    "      - name: dart analyze (root package only)\n"
    "        run: dart analyze --fatal-infos lib test integration_test\n"
)
CI_REPLACEMENT = (
    "      - name: Create the gitignored local secrets file\n"
    "        # lib/secrets/ is gitignored, so a fresh checkout cannot compile until\n"
    "        # the committed stub is copied into place -- the same command a\n"
    "        # developer runs after cloning.\n"
    "        run: tool/setup_local_secrets.sh\n"
    "\n"
    + CI_ANCHOR
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def write(path: Path, text: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        print(f"  {path.relative_to(ROOT)}: already present")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"  {path.relative_to(ROOT)}: written")


def patch(path: Path, anchor: str, replacement: str, label: str) -> None:
    if not path.is_file():
        check(False, f"missing {path.relative_to(ROOT)}")
        return
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        print(f"  {label}: already applied")
        return
    count = text.count(anchor)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count == 1:
        path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
        print(f"  {label}: applied")


write(STUB, STUB_TEXT)
write(SETUP, SETUP_TEXT)
if SETUP.is_file():
    SETUP.chmod(SETUP.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

patch(AGENTS, AGENTS_ANCHOR, AGENTS_REPLACEMENT, "AGENTS.md note")
patch(AGENTS, COMMANDS_ANCHOR, COMMANDS_REPLACEMENT, "AGENTS.md commands")
patch(WORKFLOW, CI_ANCHOR, CI_REPLACEMENT, "ci setup step")

# 1 + 2. The stub carries an empty key, and no key is written anywhere.
stub_text = STUB.read_text(encoding="utf-8") if STUB.is_file() else ""
check("const String siliconflowFallbackKey = '';" in stub_text, "the stub key must be empty")
for text, name in ((stub_text, "stub"), (SETUP.read_text(encoding="utf-8"), "setup script")):
    check("sk-" not in text, f"{name} must not contain a key")

# 3. Executable, and pointing at the committed stub.
if SETUP.is_file():
    mode = SETUP.stat().st_mode
    check(bool(mode & stat.S_IXUSR), "the setup script must be executable")
    body = SETUP.read_text(encoding="utf-8")
    check("stubs/fallback.dart" in body, "the setup script must copy the committed stub")
    check("lib/secrets/fallback.dart" in body, "the setup script must target the gitignored path")

# 4. CI runs it before analyze, and AGENTS.md says so for humans.
workflow = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
check(workflow.count("tool/setup_local_secrets.sh") == 1, "expected one CI setup step")
check(
    workflow.find("tool/setup_local_secrets.sh") < workflow.find("dart analyze"),
    "the setup step must run before analyze",
)
agents = AGENTS.read_text(encoding="utf-8") if AGENTS.is_file() else ""
check("tool/setup_local_secrets.sh" in agents, "AGENTS.md must tell a fresh clone about it")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: a fresh clone can compile, and no key is in version control")
print("  tool/stubs/fallback.dart -> lib/secrets/fallback.dart (still gitignored)")