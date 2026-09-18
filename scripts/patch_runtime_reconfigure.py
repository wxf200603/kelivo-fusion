#!/usr/bin/env python3
"""Keep the Operit tools alive when the JS runtime re-attaches.

Device evidence (operit_js_diag.log, 2026-09-18 18:44, this build):

    call configure -> configure: usable=true          <- configured on launch
    call listTools -> 25 entries
    attach()                                          <- runtime re-attached
    callTool super_admin:terminal -> {"error":"OperitJsError",
                                      "message":"runtime not configured"}
    ... every later call the same, for the whole session

Why the runtime re-attached is not the point: switching the model in a
conversation is enough, and from then on every Operit tool refuses until the
app is restarted. The caller cannot recover either, because
tool_handler_service only warms up while `!isReady`:

    if (!operitJs.isReady && !operitJs.isWarming) unawaited(operitJs.warmUp());

`_ready` stays true across the re-attach, so `configure` is never sent again.

The refusal is emitted before anything runs:

    private fun executeTool(...) {
        val rt = runtime ?: return err("runtime not configured")

so answering it with one re-configure plus one retry cannot double-execute a
side effect. That property is asserted below, because if that line ever moves,
this retry stops being safe and should fail loudly instead of guessing.
"""
from pathlib import Path

service = Path("lib/core/services/operit/operit_js_tools_service.dart")
native = Path("android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt")
src = service.read_text()

# 1) Say what happens on a re-attach.
old1 = '''  /// Every package reachable here exposes terminal/root tools, so a missing
  /// approval channel **fails closed**: silently executing would hand the model
  /// an unapproved root shell, which is precisely what the gate exists to
  /// prevent. An unavailable [approvalService] is therefore an error, never a
  /// bypass.
'''
new1 = '''  /// Every package reachable here exposes terminal/root tools, so a missing
  /// approval channel **fails closed**: silently executing would hand the model
  /// an unapproved root shell, which is precisely what the gate exists to
  /// prevent. An unavailable [approvalService] is therefore an error, never a
  /// bypass.
  ///
  /// The native runtime can also re-attach underneath us, which drops the
  /// workspace it was pointed at; that refusal is answered by re-configuring
  /// and retrying once, so a conversation survives a model switch.
'''

# 2) Re-configure and retry when the bridge says it is not configured.
old2 = '''      final raw = await _channel.invokeMethod<String>('callTool', {
        'pkg': route.packageName,
        'tool': route.tool,
        'argsJson': jsonEncode(args),
      });
      if (raw == null || raw.isEmpty) return _errorResult('empty result');

      // The native side returns the tool's JSON result verbatim; pass it
      // through unchanged so the model sees the same shape Operit produces.
      final decoded = jsonDecode(raw);
      return decoded;
'''
new2 = '''      var raw = await _callTool(route.packageName, route.tool, args);

      // A runtime that re-attached since the last [warmUp] has dropped the
      // workspace, so it answers every call with "runtime not configured"
      // until the app restarts. Re-configuring costs one round trip and keeps
      // the tools alive; [warmUp] also refreshes the schemas and routes, which
      // the new runtime may serve differently.
      if (_notConfigured(raw)) {
        await _mark('callTool: runtime not configured, re-configuring');
        await warmUp();
        raw = await _callTool(route.packageName, route.tool, args);
      }
      if (raw == null || raw.isEmpty) return _errorResult('empty result');

      // The native side returns the tool's JSON result verbatim; pass it
      // through unchanged so the model sees the same shape Operit produces.
      return jsonDecode(raw);
'''

# 3) The two helpers the retry needs.
old3 = '''  // --------------------------------------------------------------- internals

  /// Mirrors progress into the native diagnostic log (`operit_js_diag.log`
'''
new3 = '''  // --------------------------------------------------------------- internals

  /// One native tool call, with the request shape kept in a single place.
  Future<String?> _callTool(
    String pkg,
    String tool,
    Map<String, dynamic> args,
  ) =>
      _channel.invokeMethod<String>('callTool', {
        'pkg': pkg,
        'tool': tool,
        'argsJson': jsonEncode(args),
      });

  /// True when the bridge refused to run the tool because its runtime has no
  /// workspace: the native side emits this before executing anything, so the
  /// caller may safely [warmUp] and try again.
  static bool _notConfigured(String? raw) =>
      raw != null && raw.contains('runtime not configured');

  /// Mirrors progress into the native diagnostic log (`operit_js_diag.log`
'''

for index, (old_text, new_text) in enumerate(
    [(old1, new1), (old2, new2), (old3, new3)], start=1
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

# ---- self checks ----------------------------------------------------------------

# Exactly one retry, exactly one place that recognises the refusal.
if src.count("await _callTool(") != 2:
    raise SystemExit(f"expected 2 call sites, found {src.count('await _callTool(')}")
if src.count("_notConfigured(") != 2:
    raise SystemExit(f"expected 1 definition + 1 use, found {src.count('_notConfigured(')}")
if src.count("raw.contains('runtime not configured')") != 1:
    raise SystemExit("the refusal message should be matched in exactly one place")

# The retry is only safe while the native side refuses *before* it runs
# anything. Assert both halves of that: the message, and its position.
native_src = native.read_text()
if 'err("runtime not configured")' not in native_src:
    raise SystemExit("native refusal message changed; the guard would go stale")
if "val rt = runtime ?: return err(" not in native_src:
    raise SystemExit(
        "the native side no longer refuses before running the tool, so "
        "retrying could double-execute a side effect",
    )

service.write_text(src)

print("patched", service)
print("retry sites:", src.count("await _callTool("))
print("guard uses:", src.count("_notConfigured("))
