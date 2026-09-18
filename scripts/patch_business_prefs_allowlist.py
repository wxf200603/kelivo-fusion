#!/usr/bin/env python3
"""patch_business_prefs_allowlist.py — register the MCP server as a localOnly writer.

`business_shared_preferences_static_gate_test.dart` freezes the set of files that
may reference `SharedPreferences`. It grew a seventh entry when the built-in MCP
server was added, and that entry is not an exception being carved out — it is a
hole being filled.

The chain, all of it verifiable in this tree:

  * `business_settings_router.dart:35-38` registers the four `mcp_server_*` keys
    as `localOnly`: the token is a credential and must not travel in a business
    snapshot, and a listening port only means something on the machine doing the
    listening.
  * `business_preferences.dart:274-280` — the routing layer's own facade — throws
    `ArgumentError('Not a business preference')` for a `localOnly` key. That is
    by design: the facade handles business settings, which are the snapshot-able
    ones. So a `localOnly` key has exactly one route, and it is a direct write.
  * Every other `localOnly` writer is already on the list: `settings_provider.dart`,
    `hotkey_provider.dart`, `main.dart`. The list is not merely a set of
    exceptions, it is the register of legitimate direct writers.

So the MCP service is not doing something anomalous for which an exception must
be granted. It is doing the only thing a `localOnly` key permits, and it was
never registered. Adding it is what keeps the list honest: the alternative would
be to loosen `localOnly`'s meaning (let the facade accept it) or to push a
credential into snapshot-able settings, and both are worse than an accurate list.

Deliberately not in this commit: making the gate check only non-`localOnly`
references. That is the more fundamental repair — a `localOnly` key can never go
through the routing layer, so the gate should not be asserting that it does — but
it changes what the test means, and it belongs in its own commit.

Self-checks:

  1. The gate is not weakened: the recursive scan and the `orderedEquals`
     assertion are still there, so this remains a gate and not a note.
  2. The allowlist holds exactly the six previous entries plus the MCP service,
     and nothing else moved.
  3. The justification is present in the file, not only in this docstring.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "test/business_shared_preferences_static_gate_test.dart"

MCP_PATH = "lib/core/services/mcp/server/mcp_server_service.dart"
# The whole line, indent included: the first version of this script carried only
# the quoted path, so the entry it wrote landed at column 0 while its neighbours
# all sit at eight spaces. The check at the bottom is what caught it.
MCP_LINE = f"        '{MCP_PATH}',\n"

ANCHOR = (
    "        'lib/core/providers/settings_provider.dart',\n"
    "        'lib/desktop/window_size_manager.dart',\n"
)

JUSTIFICATION = (
    "        // The built-in MCP server's settings are `localOnly` keys, which are not\n"
    "        // business settings and by design do not go through the routing layer:\n"
    "        // `BusinessPreferences` throws `ArgumentError` for them, so a direct write\n"
    "        // is the only route such a key has. Every other `localOnly` writer\n"
    "        // (settings_provider.dart, hotkey_provider.dart, main.dart) is already on\n"
    "        // this list; this file is a legitimate holder that was simply never added.\n"
)

# Scoped to the `allowed` block on purpose. The file's second test also expects a
# `'lib/...'` path (the routing filter), so a file-wide scan for entries counts a
# path that is not on this list — which is what the first version of this check
# did, and why it reported a correct seven-entry list as wrong.
ALLOWED_BLOCK_RE = re.compile(r"const allowed = <String>\{(.*?)\n      \};", re.DOTALL)
ENTRY_RE = re.compile(r"'(lib/[^']+)'")

EXPECTED = sorted(
    [
        "lib/core/database/business_migration_engine.dart",
        "lib/core/providers/hotkey_provider.dart",
        "lib/core/providers/settings_provider.dart",
        "lib/core/services/mcp/server/mcp_server_service.dart",
        "lib/desktop/window_size_manager.dart",
        "lib/features/migration/hive_to_sqlite_migration_service.dart",
        "lib/main.dart",
    ]
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(GATE.is_file(), f"missing {GATE.relative_to(ROOT)}")
text = GATE.read_text(encoding="utf-8") if GATE.is_file() else ""
original = text

if MCP_LINE in text:
    print("  allowlist entry: already applied")
else:
    count = text.count(ANCHOR)
    check(count == 1, f"allowlist anchor matched {count} times (expected exactly 1)")
    if count == 1:
        text = text.replace(ANCHOR, JUSTIFICATION + MCP_LINE + ANCHOR, 1)
        print("  allowlist entry: added with its justification")

if text != original:
    GATE.write_text(text, encoding="utf-8")

# 1. Still a gate.
for line in (
    "await for (final entity in Directory('lib').list(recursive: true))",
    "references.sort();",
    "expect(references, orderedEquals(allowed.toList()..sort()));",
):
    check(line in text, f"the gate lost its scan or its assertion: {line}")

# 2. Exactly the seven entries, and nothing else moved.
block = ALLOWED_BLOCK_RE.search(text)
check(block is not None, "the `allowed` block is no longer where it was")
entries = sorted(ENTRY_RE.findall(block.group(1))) if block else []
check(entries == EXPECTED, f"the allowlist is {entries} (expected {EXPECTED})")

# 3. The reason travels with the entry.
for fragment in ("localOnly", "ArgumentError", "hotkey_provider.dart, main.dart"):
    check(fragment in text, f"the justification is missing: {fragment}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the MCP server is registered as a localOnly writer, with its reason")