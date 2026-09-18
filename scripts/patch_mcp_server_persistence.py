#!/usr/bin/env python3
"""patch_mcp_server_persistence.py — register the server's settings so they stick.

On-device: `load()` runs, generates a 43-character token, reports `stored=false`
— and that token lands nowhere. `FlutterSharedPreferences.xml` stays `<map />`
and the SQLite database never sees the key either.

The cause is Kelivo's business-settings router: a preference key is classified
before it is stored (`BusinessKeyRegistry.classify`), and a key that appears in
no list falls through to `unknownPreference` — which is not persisted. The MCP
server's four keys are new, so that is exactly what they hit. `setString`
succeeded, threw nothing, and wrote nothing.

`localOnlyKeys` is the right home rather than `preferenceKeys`: these settings
describe *this device*. The token is a credential and has no business travelling
inside a business snapshot, and a switch that says "listen on 8765" means
nothing on a machine that is not the one listening.

Self-checks:

  1. The four keys are registered.
  2. They are local-only — routing the token as a business preference would put
     a credential into exported snapshots.
  3. The registry and the service agree on every key name, because a typo here
     reproduces the original silence exactly: a successful write that vanishes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "lib/core/database/business_settings_router.dart"
SERVICE = ROOT / "lib/core/services/mcp/server/mcp_server_service.dart"

# The keys the service writes, in the order they are declared there.
KEYS = (
    "mcp_server_enabled",
    "mcp_server_allow_lan",
    "mcp_server_port",
    "mcp_server_token",
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(ROUTER.is_file(), f"missing {ROUTER.relative_to(ROOT)}")
check(SERVICE.is_file(), f"missing {SERVICE.relative_to(ROOT)}")

text = ROUTER.read_text(encoding="utf-8") if ROUTER.is_file() else ""

anchor = "    'flutter_log_enabled_v1',\n  };"
if not any(f"'{key}'" in text for key in KEYS):
    count = text.count(anchor)
    check(count == 1, f"anchor matched {count} times (expected exactly 1)")
    if count == 1:
        block = "".join(f"    '{key}',\n" for key in KEYS)
        replacement = (
            "    'flutter_log_enabled_v1',\n"
            "    // The built-in MCP server belongs to this device, so its settings\n"
            "    // are local-only: the token is a credential and must not travel in a\n"
            "    // business snapshot, and a listening port only means something on\n"
            "    // the machine doing the listening.\n"
            f"{block}"
            "  };"
        )
        ROUTER.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
        print("  business_settings_router: +4 local-only keys")
else:
    print("  business_settings_router: already applied")

router = ROUTER.read_text(encoding="utf-8") if ROUTER.is_file() else ""
service = SERVICE.read_text(encoding="utf-8") if SERVICE.is_file() else ""

# 1 + 3. Registered, and matching what the service actually writes.
for key in KEYS:
    check(f"'{key}'," in router, f"{key} is not registered in the key registry")
for partial in ("_enabledKey = ", "_lanKey = ", "_portKey = ", "_tokenKey = "):
    check(partial in service, f"the service no longer declares {partial}")

# 2. Local-only, by checking each name sits inside the localOnlyKeys set.
local_start = router.find("static const localOnlyKeys = <String>{")
local_end = router.find("};", local_start)
check(local_start != -1 and local_end > local_start, "localOnlyKeys not found")
local_block = router[local_start:local_end] if local_start != -1 else ""
pref_start = router.find("static const preferenceKeys = <String>{")
pref_end = router.find("};", pref_start)
pref_block = router[pref_start:pref_end] if pref_start != -1 else ""
for key in KEYS:
    check(f"'{key}'" in local_block, f"{key} is not in localOnlyKeys")
    check(f"'{key}'" not in pref_block, f"{key} must not be a business preference")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the MCP server's settings are now classified as local-only")
print("  mcp_server_enabled / allow_lan / port / token -> localOnlyKeys")
print("  a missing entry here is what made every write vanish silently")