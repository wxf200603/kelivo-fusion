#!/usr/bin/env python3
"""patch_mcp_diag_docs.py — document the field that became public.

0d2b475 turned the three `_diag` fields into public `diag` so the constructors
could take them as initialising formals. Every other public member of those
classes already carries a doc comment — `token`, `address`, `port`,
`serverName`, `serverVersion` — and the field that arrived with that commit is
the one without one. So this documents it, and says the part that cannot be
recovered from the field's type: whose sink it is, and where it lands — the
service's, in the same `operit_js_diag.log` the rest of the fusion writes to
(see `McpServerService._mark`, which forwards over the Operit bridge).

It has a second effect that is not incidental: it puts the three files that are
*not* `dart format`-clean back into the set the format check looks at. That
check only examines the files a push changes, so the push before this one — the
one that added the hand-off — changed no Dart file at all and passed with "No
changed Dart files to format-check." Touching these three is how the formatter's
output becomes obtainable in the first place, and the push that carries this is
the first one the hand-off has to run for.

Self-checks:

  1. Each anchor matched exactly once. The three declarations are textually
     identical, so an anchor matching twice would mean the wrong one was edited.
  2. Every one of the three now has a doc comment directly above it.
  3. The added lines fit in 80 columns, so the formatter this is queued behind
     cannot want to re-wrap them — comments are not re-wrapped, but a line that
     wide invites the mistake of assuming otherwise.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "lib/core/services/mcp/server"

DECL = "  final void Function(String message)? diag;\n"

# (file, anchor, replacement). The anchor always ends with the declaration, and
# the replacement is the anchor with the doc comment inserted above it. The
# engine's private `_tools` sits directly above its field, so for that one the
# blank line moves below the comment rather than above it.
EDITS = {
    "mcp_http_transport.dart": (
        "  final int port;\n\n  final void Function(String message)? diag;\n",
        "  final int port;\n\n"
        "  /// Where this transport's log lines go. The service points it at the same\n"
        "  /// `operit_js_diag.log` as the rest of the fusion; null keeps it quiet.\n"
        "  final void Function(String message)? diag;\n",
    ),
    "mcp_server_engine.dart": (
        "  final Map<String, McpServerTool> _tools;\n  final void Function(String message)? diag;\n",
        "  final Map<String, McpServerTool> _tools;\n\n"
        "  /// Where this engine's log lines go. The service points it at the same\n"
        "  /// `operit_js_diag.log` as the rest of the fusion; null keeps it quiet.\n"
        "  final void Function(String message)? diag;\n",
    ),
    "mcp_workspace_tools.dart": (
        "  McpWorkspaceTools({this.diag});\n\n  final void Function(String message)? diag;\n",
        "  McpWorkspaceTools({this.diag});\n\n"
        "  /// Where these tools' log lines go. The service points it at the same\n"
        "  /// `operit_js_diag.log` as the rest of the fusion; null keeps them quiet.\n"
        "  final void Function(String message)? diag;\n",
    ),
}

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


for name, (anchor, replacement) in EDITS.items():
    path = SERVER / name
    check(path.is_file(), f"missing {path.relative_to(ROOT)}")
    if not path.is_file():
        continue

    text = path.read_text(encoding="utf-8")
    if replacement in text:
        print(f"  {name}: already documented")
    else:
        count = text.count(anchor)
        check(count == 1, f"{name}: anchor matched {count} times (expected exactly 1)")
        if count == 1:
            path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
            print(f"  {name}: doc comment added")
        text = path.read_text(encoding="utf-8")

    # The comment has to sit directly above the declaration, and the
    # declaration itself has to survive exactly once.
    check(text.count(DECL) == 1, f"{name}: expected exactly one diag declaration")
    check(
        "\n  /// " in text and "\n  /// " in text.split(DECL)[0][-120:],
        f"{name}: no doc comment directly above the declaration",
    )
    for line in text.splitlines():
        if line.lstrip().startswith("///") and "log lines go" in line:
            check(len(line) <= 80, f"{name}: added comment is {len(line)} columns wide")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the public diagnostic sink is documented in all three classes")