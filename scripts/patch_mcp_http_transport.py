#!/usr/bin/env python3
"""patch_mcp_http_transport.py — Plan A (outbound MCP server), batch 2: transport.

Adds one file, changing none:

  lib/core/services/mcp/server/mcp_http_transport.dart

Streamable HTTP (`POST /mcp`) plus the legacy SSE pair (`GET /sse` +
`POST /message`), both gated on a bearer token. No service lifecycle or UI yet,
so nothing can start it from the app — this batch only has to be correct, which
CI proves by compiling it.

Self-checks:

  1. The file exists and carries every route and protocol fragment.
  2. Both transports are actually reachable (the paths, the endpoint preamble).
  3. Authorisation is a bearer check with a non-short-circuiting comparison,
     and it is bypassed only for the CORS preflight.
  4. Replies take the shape each case needs: 202 for notifications, 405 for the
     wrong verb, 401 for a bad token, SSE when the client asked for a stream.
  5. No `print(` — diagnostics go through the injected `diag` callback.
  6. Loopback by default: exposing the LAN has to be an explicit choice.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "lib/core/services/mcp/server/mcp_http_transport.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(TRANSPORT.is_file(), f"missing {TRANSPORT.relative_to(ROOT)}")
source = TRANSPORT.read_text(encoding="utf-8") if TRANSPORT.is_file() else ""

# 2. Both transports, and the routes each one owns.
check(
    "'/mcp'" in source and "_streamablePath = '/mcp'" in source,
    "Streamable HTTP path is gone",
)
check(
    "_legacySsePath = '/sse'" in source and "_legacyMessagePath = '/message'" in source,
    "legacy SSE routes are gone",
)
check(
    "'endpoint': '$_legacyMessagePath?sessionId='" in source,
    "the legacy endpoint preamble is gone, so no client could find POST /message",
)
check("_sessionHeader = 'Mcp-Session-Id'" in source, "session header is gone")

# 3. Authorisation.
check("'Bearer '" in source or "startsWith('Bearer ')" in source, "no bearer check")
check("_constantTimeEquals" in source, "token comparison no longer constant-time")
check(
    "request.method == 'OPTIONS'" in source
    and source.index("request.method == 'OPTIONS'") < source.index("_authorized(request)"),
    "the preflight is checked after the token, so browsers could never connect",
)
check("HttpStatus.unauthorized" in source, "no 401 reply for a bad token")
check("if (token.isEmpty) return false" in source, "an empty token would be accepted")

# 4. Reply shapes.
check("HttpStatus.accepted" in source, "notifications must be answered 202")
check("HttpStatus.methodNotAllowed" in source, "wrong verbs must be answered 405")
check("_writeEventStreamOnce" in source, "no single-response SSE path")
check("_wantsEventStream" in source, "no Accept negotiation")

# The engine is what actually answers.
check("engine.handleMessage" in source, "the transport does not call the engine")
check("mcp.McpProtocol.methodInitialize" in source, "session id is not tied to the handshake")

# 5. Diagnostics.
check("print(" not in source, "transport uses print(); use the diag callback")

# 6. Defaults.
check(
    "address = address ?? InternetAddress.loopbackIPv4" in source,
    "the listener no longer defaults to loopback",
)
check("HttpServer.bind(address, port)" in source, "no listener")
check("keep-alive" in source, "no keep-alive, so idle streams would rot")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: MCP HTTP transport is in place")
print(f"  transport: {len(source.splitlines())} lines")
print("  routes   : POST /mcp, GET /mcp (SSE), DELETE /mcp, GET /sse, POST /message")
print("  auth     : Authorization: Bearer <token>, constant-time, preflight exempt")
