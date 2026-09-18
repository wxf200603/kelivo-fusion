#!/usr/bin/env python3
"""patch_mcp_server.py — Plan A (outbound MCP server), batch 1: engine + tools.

Adds two files and changes no existing one, so this script is assertions plus
self-checks rather than a rewriter:

  lib/core/services/mcp/server/mcp_server_engine.dart
  lib/core/services/mcp/server/mcp_workspace_tools.dart

Self-checks, in the order they would bite:

  1. Both files exist and carry every fragment the design depends on.
  2. Every `mcp_client` protocol constant used really is declared in the
     dependency — a typo there costs a CI round trip and cannot be caught
     locally (no Dart SDK in this container).
  3. The four tool names and the two required markers from the acceptance
     criteria (requirement 5) are present.
  4. No `print(`: release builds do not expose Dart's stdout, so diagnostics
     must go through the `diag` channel into `operit_js_diag.log`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "lib/core/services/mcp/server/mcp_server_engine.dart"
TOOLS = ROOT / "lib/core/services/mcp/server/mcp_workspace_tools.dart"
PROTOCOL = ROOT / "dependencies/mcp_client/lib/src/protocol/protocol.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(ENGINE.is_file(), f"missing {ENGINE.relative_to(ROOT)}")
check(TOOLS.is_file(), f"missing {TOOLS.relative_to(ROOT)}")

engine = ENGINE.read_text(encoding="utf-8") if ENGINE.is_file() else ""
tools = TOOLS.read_text(encoding="utf-8") if TOOLS.is_file() else ""
protocol = PROTOCOL.read_text(encoding="utf-8") if PROTOCOL.is_file() else ""

# 2. Protocol constants must exist in the dependency, and be used by the engine.
for constant in (
    "defaultVersion",
    "methodInitialize",
    "methodListTools",
    "methodCallTool",
):
    check(
        f"static const String {constant}" in protocol,
        f"protocol.dart declares no {constant}; the engine would not compile",
    )
    check(
        f"mcp.McpProtocol.{constant}" in engine,
        f"engine does not use mcp.McpProtocol.{constant}",
    )

# `ping` has no constant in the library, so the engine must spell it out.
check("'ping'" in engine, "engine no longer answers ping")

# The engine's shape: handshake, tool listing, one tool call, batch handling.
for fragment in (
    "_initializeResult",
    "_listToolsResult",
    "Future<Map<String, dynamic>> _callTool",
    "if (message is List)",
    "if (id == null)",
):
    check(fragment in engine, f"engine missing {fragment}")

# The tool surface: one adapter per super_admin terminal tool.
for name in ("terminal", "terminal_wait", "terminal_getscreen", "terminal_input"):
    check(f"name: '{name}'" in tools, f"tools missing '{name}'")

# 4. Requirement 5's markers.
check("mcp: incoming tool call" in tools, "missing the incoming-call marker")
check("mcp: sync global cwd" in tools, "missing the cwd-sync marker")

# The bridge contract the tools rely on.
for fragment in (
    "'pkg': _package",
    "'tool': tool",
    "'argsJson':",
    "'workspaceCwd'",
    "OperitJsToolsService.instance",
):
    check(fragment in tools, f"tools missing bridge fragment {fragment}")

# 5. No print() anywhere in the new code.
for path, text in ((ENGINE, engine), (TOOLS, tools)):
    check("print(" not in text, f"{path.name} uses print(); use the diag channel")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: MCP server engine + workspace tools are in place")
print(f"  engine: {len(engine.splitlines())} lines")
print(f"  tools : {len(tools.splitlines())} lines")
print(f"  tools exposed: terminal, terminal_wait, terminal_getscreen, terminal_input")
