#!/usr/bin/env python3
"""patch_mcp_diag_formals.py — the four infos the gate now stops on.

With the l10n artefact and the gitignored stub fixed, `dart analyze
--fatal-infos` is down to four infos, and all four are in code this project owns:

  mcp_http_transport.dart:27:8    prefer_initializing_formals
  mcp_server_engine.dart:69:8     prefer_initializing_formals
  mcp_workspace_tools.dart:16:62  prefer_initializing_formals
  main.dart:96:8                  unnecessary_import (dart:async)

The lint suggests `this._diag`, which cannot be applied as written: a named
parameter may not start with an underscore, and every call site lives in another
library (`mcp_server_service.dart` passes `diag:` twice), so a private parameter
name could never be passed at all.

The fix that keeps both the lint and the call sites happy is the one these two
classes already use for their other wiring: `McpHttpTransport` takes
`this.engine`, `this.token`, `this.port`, and `McpServerEngine` takes
`this.serverName`. So `diag` becomes a public field with `this.diag` in the
parameter list, and the public parameter name is unchanged — call sites do not
move.

Behaviour is untouched: a rename of a field, plus making it visible. Nothing in
the MCP request path reads it differently, which is why the six frozen MCP
acceptance criteria get re-run on device afterwards rather than trusted.

`main.dart:96` (`import 'dart:async' show unawaited;`) is deleted only after
asserting that another `dart:async` import in the same file still provides
`unawaited` — the analyzer's "unnecessary because all of the used elements are
also provided by the import of 'dart:async'" is a claim worth checking before
acting on it.

Self-checks:

  1. Every anchor matched exactly once.
  2. After the rename no `_diag` survives in the three files.
  3. `diag:` is still a public parameter name, so the two call sites still type
     check.
  4. main.dart still imports `dart:async` from somewhere.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "lib/core/services/mcp/server"
MAIN = ROOT / "lib/main.dart"

EDITS: tuple[tuple[Path, str, str, str], ...] = (
    (
        SERVER / "mcp_workspace_tools.dart",
        "  McpWorkspaceTools({void Function(String message)? diag}) : _diag = diag;\n",
        "  McpWorkspaceTools({this.diag});\n",
        "workspace tools constructor",
    ),
    (
        SERVER / "mcp_http_transport.dart",
        "    void Function(String message)? diag,\n",
        "    this.diag,\n",
        "transport parameter",
    ),
    (
        SERVER / "mcp_http_transport.dart",
        "  }) : address = address ?? InternetAddress.loopbackIPv4,\n       _diag = diag;\n",
        "  }) : address = address ?? InternetAddress.loopbackIPv4;\n",
        "transport initialiser",
    ),
    (
        SERVER / "mcp_server_engine.dart",
        "    void Function(String message)? diag,\n",
        "    this.diag,\n",
        "engine parameter",
    ),
    (
        SERVER / "mcp_server_engine.dart",
        "       },\n       _diag = diag;\n",
        "       };\n",
        "engine initialiser",
    ),
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def apply(path: Path, anchor: str, replacement: str, label: str) -> None:
    if not path.is_file():
        check(False, f"missing {path.relative_to(ROOT)}")
        return
    text = path.read_text(encoding="utf-8")
    if replacement in text and anchor not in text:
        print(f"  {label}: already applied")
        return
    count = text.count(anchor)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count == 1:
        path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
        print(f"  {label}: applied")


for path, anchor, replacement, label in EDITS:
    apply(path, anchor, replacement, label)

# 2. The field rename, including the declaration and every internal read.
#
# The `\b` matters: `operit_js_diag.log` appears in doc comments in this very
# file and contains the substring `_diag`, so a plain containment test reported
# a completed rename as still pending and failed the run.
STANDALONE = re.compile(r"\b_diag\b")

for name in ("mcp_http_transport.dart", "mcp_server_engine.dart", "mcp_workspace_tools.dart"):
    path = SERVER / name
    if not path.is_file():
        check(False, f"missing {path.relative_to(ROOT)}")
        continue
    text = path.read_text(encoding="utf-8")
    if not STANDALONE.search(text):
        print(f"  {name}: field already renamed")
        continue
    renamed = re.sub(r"\b_diag\b", "diag", text)
    path.write_text(renamed, encoding="utf-8")
    print(f"  {name}: _diag -> diag")

# main.dart: the duplicate import, removed only if unawaited survives elsewhere.
main_text = MAIN.read_text(encoding="utf-8") if MAIN.is_file() else ""
duplicate = "import 'dart:async' show unawaited;\n"
if duplicate not in main_text:
    print("  main.dart: duplicate import already gone")
else:
    others = len(re.findall(r"^import 'dart:async'", main_text, flags=re.MULTILINE))
    check(others >= 2, f"only {others} dart:async import(s); deleting one would break unawaited")
    if others >= 2:
        MAIN.write_text(main_text.replace(duplicate, "", 1), encoding="utf-8")
        print("  main.dart: dropped the duplicate dart:async import")

# 1 + 3 + 4.
for name in ("mcp_http_transport.dart", "mcp_server_engine.dart", "mcp_workspace_tools.dart"):
    path = SERVER / name
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8")
    check(not STANDALONE.search(text), f"{name}: _diag survived the rename")
    check(
        "this.diag" in text or "({this.diag})" in text or "{this.diag}" in text,
        f"{name}: the constructor does not use an initialising formal",
    )

service = (SERVER / "mcp_server_service.dart").read_text(encoding="utf-8")
check(service.count("diag: _diag,") == 2, "the two call sites must be untouched")

main_text = MAIN.read_text(encoding="utf-8") if MAIN.is_file() else ""
check(
    len(re.findall(r"^import 'dart:async'", main_text, flags=re.MULTILINE)) >= 1,
    "main.dart must still import dart:async",
)
check(duplicate not in main_text, "the duplicate import is still there")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the four infos are addressed without moving a single call site")
print("  next: re-run the six frozen MCP acceptance criteria on device")