#!/usr/bin/env python3
"""patch_mcp_server_service.py — Plan A, step 2: the server's lifetime + token.

Adds the owner of the outbound server and wires it into startup:

  lib/core/services/mcp/server/mcp_server_service.dart   (new)
  lib/main.dart                                           + import + load()

Why main.dart has to import it at all: "enabled" is a stored preference, so a
user who left the server on expects to find it on after a restart. The setting
is only a promise if startup honours it.

Self-checks:

  1. The service exists and carries the start / stop / token surface.
  2. main.dart both imports it and calls `load()` — a call without the import
     fails to compile, but a leftover one of either would be easy to miss.
  3. The transport is built with the token, so no path listens without one.
  4. Loopback stays the default and the LAN is the opt-in, mirrored from the
     transport's own guarantee.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "lib/core/services/mcp/server/mcp_server_service.dart"
MAIN = ROOT / "lib/main.dart"

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


check(SERVICE.is_file(), f"missing {SERVICE.relative_to(ROOT)}")
check(MAIN.is_file(), f"missing {MAIN.relative_to(ROOT)}")

patch(
    MAIN,
    "import 'core/services/operit/operit_js_tools_service.dart';",
    "import 'core/services/mcp/server/mcp_server_service.dart';\n"
    "import 'core/services/operit/operit_js_tools_service.dart';",
    "main.dart: import",
)

patch(
    MAIN,
    "unawaited(OperitJsToolsService.instance.warmUp());",
    "unawaited(OperitJsToolsService.instance.warmUp());\n"
    "        // Restored here rather than on first visit to the settings page: a\n"
    "        // user who left the server on expects it back after a restart.\n"
    "        unawaited(McpServerService.instance.load());",
    "main.dart: load()",
)

service = SERVICE.read_text(encoding="utf-8") if SERVICE.is_file() else ""
main = MAIN.read_text(encoding="utf-8") if MAIN.is_file() else ""

check(
    "class McpServerService extends ChangeNotifier" in service,
    "the service is not a ChangeNotifier the settings page can listen to",
)
check(
    "static final McpServerService instance" in service,
    "no single instance, so two callers could start two listeners",
)
check("Future<bool> start()" in service, "no start()")
check("Future<void> stop()" in service, "no stop()")
check("Future<String> regenerateToken()" in service, "no token rotation")
check("Random.secure()" in service, "the token is not drawn from a CSPRNG")
check("_tokenBytes = 32" in service, "token entropy changed")
check(
    "token: _token," in service,
    "the transport is not given the token, so it could listen unauthenticated",
)
check(
    "InternetAddress.loopbackIPv4" in service,
    "loopback is no longer the default interface",
)
check(
    "_allowLan" in service and "InternetAddress.anyIPv4" in service,
    "no explicit LAN opt-in",
)
check(
    "if (_token.isEmpty)" in service,
    "a start without a token is no longer prevented",
)

check(
    "mcp_server_service.dart'" in main,
    "main.dart does not import the service",
)
check(
    "McpServerService.instance.load()" in main,
    "main.dart does not restore the server at startup",
)

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the MCP server has an owner and a lifetime")
print("  start/stop, persisted on/off, LAN opt-in, port guard, token rotation")
print("  main.dart: warmUp() then load(), so a restart restores what was on")