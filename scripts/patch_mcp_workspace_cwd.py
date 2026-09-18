#!/usr/bin/env python3
"""patch_mcp_workspace_cwd.py — Plan A, step 1: hand the shared directory to Dart.

Requirement 5 (`mcp: sync global cwd`) is written by the MCP server after every
command, so the value has to cross the bridge:

  KelivoWorkspaceHost.kt  + `globalCwd`, a read-only view of GlobalWorkspace.cwd
  OperitJsRuntime.kt      + `workspaceCwd` on the `app.operit_js` channel

Why `workspace.cwd` rather than `GlobalWorkspace.sessionCwd()`: the accessor
reports a directory, it does not prepare one. `sessionCwd()` verifies the path
and may fall back to root, which is right before *starting* a command and wrong
for describing where the last one finished — and it would add a second
"loaded global cwd" line to every MCP call.

Both anchors are asserted to match exactly once; a second match means the file
moved under us and the patch would land in the wrong place.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt"
RUNTIME = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
TOOLS = ROOT / "lib/core/services/mcp/server/mcp_workspace_tools.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count != 1:
        return
    if new.strip() in text:
        print(f"  {label}: already applied")
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  {label}: patched")


for path in (HOST, RUNTIME, TOOLS):
    check(path.is_file(), f"missing {path.relative_to(ROOT)}")

patch(
    HOST,
    """    /** Last output per session, for `terminal_getscreen`. */
    private val sessionOutput = ConcurrentHashMap<String, String>()
""",
    """    /** Last output per session, for `terminal_getscreen`. */
    private val sessionOutput = ConcurrentHashMap<String, String>()

    /**
     * The shared working directory, for callers that report it rather than use it.
     *
     * The MCP server mirrors this into the diagnostic log after every command, so
     * "the terminal and the app agree on the directory" is checkable from the log
     * instead of taken on faith. Deliberately not [GlobalWorkspace.sessionCwd]:
     * that one verifies and may fall back, which is right before *starting* a
     * command and wrong for describing where the last one finished.
     */
    val globalCwd: String
        get() = workspace.cwd
""",
    "KelivoWorkspaceHost.globalCwd",
)

patch(
    RUNTIME,
    """                "status" -> result.success(""",
    """                "workspaceCwd" -> result.success(
                    workspaceHost?.globalCwd.orEmpty()
                )
                "status" -> result.success(""",
    "OperitJsRuntime.workspaceCwd",
)

# The bridge is only worth its surface while the MCP server reads it, and the
# Dart side is the only reader. If that call disappears, this hole in the host
# should be closed rather than left open and unused.
if TOOLS.is_file():
    check(
        "'workspaceCwd'" in TOOLS.read_text(encoding="utf-8"),
        "no Dart caller for workspaceCwd; do not add a bridge nobody reads",
    )

host_text = HOST.read_text(encoding="utf-8") if HOST.is_file() else ""
runtime_text = RUNTIME.read_text(encoding="utf-8") if RUNTIME.is_file() else ""

check("val globalCwd: String" in host_text, "host does not expose globalCwd")
check(
    "get() = workspace.cwd" in host_text,
    "globalCwd does not read the shared workspace",
)
check('"workspaceCwd" ->' in runtime_text, "the channel method was not added")
check(
    "workspaceHost?.globalCwd.orEmpty()" in runtime_text,
    "the channel method does not read the host",
)

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the shared working directory is reachable from Dart")
print("  KelivoWorkspaceHost.globalCwd -> GlobalWorkspace.cwd (no verification)")
print("  app.operit_js 'workspaceCwd'  -> the string, empty while unconfigured")