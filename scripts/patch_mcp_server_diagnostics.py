#!/usr/bin/env python3
"""patch_mcp_server_diagnostics.py — make the settings path observable.

On-device evidence: `load()` runs (the log shows `mcp: server listening` and
`mcp: server ready`, produced by the very `start()` it calls), yet nothing it
writes reaches SharedPreferences — `grep -rl mcp_server` over the app directory
comes back empty, and there is no DataStore backend to explain it.

The write path is `await prefs.setString(...)` with no `try`, inside a future
started with `unawaited(...)`. Anything thrown there lands in the zone, and
`FlutterLogger` ships disabled — so it is swallowed with no trace. Before
guessing at a cause, make the failure legible:

  - `load()` reports its outcome (or the exception) through the `diag` channel,
    which is proven to work at this exact moment: the same startup produced
    `mcp: server ready`.
  - `setEnabled()` does the same, because it has the identical write and the
    identical consequence: a switch that silently forgets it was turned on.

Self-checks: both methods now catch, both report, and neither swallows a throw
without a marker.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "lib/core/services/mcp/server/mcp_server_service.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new.strip() in text:
        print(f"  {label}: already applied")
        return
    count = text.count(old)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count != 1:
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  {label}: patched")


check(SERVICE.is_file(), f"missing {SERVICE.relative_to(ROOT)}")

patch(
    SERVICE,
    """  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _enabled = prefs.getBool(_enabledKey) ?? false;
    _allowLan = prefs.getBool(_lanKey) ?? false;
    _port = prefs.getInt(_portKey) ?? defaultPort;
    _token = prefs.getString(_tokenKey) ?? '';
    if (_token.isEmpty) {
      _token = _generateToken();
      await prefs.setString(_tokenKey, _token);
    }
    _loaded = true;
    notifyListeners();
    if (_enabled) await start();
  }""",
    """  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _enabled = prefs.getBool(_enabledKey) ?? false;
      _allowLan = prefs.getBool(_lanKey) ?? false;
      _port = prefs.getInt(_portKey) ?? defaultPort;
      _token = prefs.getString(_tokenKey) ?? '';
      final hadToken = _token.isNotEmpty;
      if (!hadToken) {
        _token = _generateToken();
        await prefs.setString(_tokenKey, _token);
      }
      _loaded = true;
      // Reported through the channel rather than trusting the write: on device
      // this line is what tells a failed persist apart from a failed read.
      unawaited(
        _mark(
          'mcp: settings loaded enabled=$_enabled port=$_port '
          'token=${_token.length}chars stored=$hadToken',
        ),
      );
      notifyListeners();
      if (_enabled) await start();
    } catch (error, stack) {
      // Without this the exception vanished into the zone: the future is
      // started with `unawaited`, and the app's logger ships switched off.
      unawaited(_mark('mcp: load failed: $error'));
      debugPrint('[mcp_server] load failed: $error\\n$stack');
    }
  }""",
    "load(): report instead of swallowing",
)

patch(
    SERVICE,
    """  Future<void> setEnabled(bool value) async {
    if (_enabled == value) return;
    _enabled = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_enabledKey, value);
    notifyListeners();
    if (value) {
      await start();
    } else {
      await stop();
    }
  }""",
    """  Future<void> setEnabled(bool value) async {
    if (_enabled == value) return;
    _enabled = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_enabledKey, value);
    } catch (error) {
      // The switch still applies to this run; only its persistence failed, and
      // that is exactly the kind of half-truth worth naming in the log.
      unawaited(_mark('mcp: setEnabled($value) could not persist: $error'));
    }
    unawaited(_mark('mcp: setEnabled $value'));
    notifyListeners();
    if (value) {
      await start();
    } else {
      await stop();
    }
  }""",
    "setEnabled(): report the persist",
)

service = SERVICE.read_text(encoding="utf-8") if SERVICE.is_file() else ""

check(
    "unawaited(_mark('mcp: load failed: $error'));" in service,
    "load() still swallows its failure",
)
check("mcp: settings loaded" in service, "load() does not report success")
check("final hadToken = _token.isNotEmpty;" in service, "no read-vs-write distinction")
check(
    "mcp: setEnabled($value) could not persist" in service,
    "setEnabled() does not report a failed persist",
)
check(
    service.count("} catch (error") >= 2,
    "fewer catch blocks than instrumented methods",
)

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the settings path now reports what it did")
print("  load()      -> 'mcp: settings loaded ... stored=<bool>' or 'mcp: load failed: ...'")
print("  setEnabled() -> 'mcp: setEnabled <value>' (+ a marker when persisting fails)")