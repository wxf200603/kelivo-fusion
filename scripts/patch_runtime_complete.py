#!/usr/bin/env python3
"""Let a package deliver its result through Operit's global `complete`.

Operit's runtime hands a package's result back by calling a global
`complete(value)`; this port only read the tool function's return value, so
every package that delivers that way - `extended_file_tools`, `file_converter`,
`github`, ... - died with `'complete' is not defined`. Found on the device while
trying to exercise `Tools.Files.exists` (log line: result
extended_file_tools:file_exists -> {"error":"OperitJsError","message":"'complete'
is not defined"}), because `wrapToolExecution` runs `await func(params)` first
and only then calls `complete`.

Two edits:

  1. the bootstrap defines `complete` (and its counterpart `error`);
  2. `executeTool` records a completion flag, so the value a completing tool
     delivers wins over the `undefined` its function returns.

Same anchor discipline as the other scripts/patch_*.py.
"""
from pathlib import Path

RT = Path(__file__).resolve().parent.parent / (
    "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
)

B_OLD = """                root.getChatId = function () {
                    return 'kelivo-shared';
                };
            }
"""
B_NEW = B_OLD + """
            if (typeof root.complete !== 'function') {
                // Operit hands a package's result back through `complete`, not
                // through the function's return value. Record it and let it win
                // over the `undefined` a completing tool returns.
                root.complete = function (value) {
                    root.__operit_done = true;
                    root.__operit_out = (value === undefined ? null : value);
                };
            }
"""

C_OLD = """            append("globalThis.__operit_err = null; globalThis.__operit_out = undefined;")
"""
C_NEW = C_OLD + """            append("globalThis.__operit_done = false;")
"""

D_OLD = """            append("      function(v){ globalThis.__operit_out = (v === undefined ? null : v); },")
"""
D_NEW = """            append("      function(v){ if (!globalThis.__operit_done) globalThis.__operit_out = (v === undefined ? null : v); },")
"""

EDITS = [(B_OLD, B_NEW), (C_OLD, C_NEW), (D_OLD, D_NEW)]


def main() -> None:
    src = RT.read_text(encoding="utf-8")
    if "root.complete = function" in src:
        print("already applied")
        return
    for old, new in EDITS:
        found = src.count(old)
        if found != 1:
            raise SystemExit(f"expected 1 match, found {found}")
        src = src.replace(old, new)
    RT.write_text(src, encoding="utf-8")
    print("applied: OperitJsRuntime.kt")


if __name__ == "__main__":
    main()