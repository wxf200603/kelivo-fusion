#!/usr/bin/env python3
"""Give the on-device self test a `#call` prefix.

Both existing prefixes end at callTool("super_admin", ...), but a Tools.Files.*
method is reachable only through the package that calls it, which is never
super_admin. `#call` takes lines of `<pkg>:<tool> {json}` and runs each through
[callTool], whose arguments and raw result already land in operit_js_diag.log.

Same anchor discipline as the other scripts/patch_*.py.
"""
from pathlib import Path

RT = Path(__file__).resolve().parent.parent / (
    "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
)

D_OLD = """        if (text.startsWith(PTY_PREFIX)) {
            runPtySelfTest()
            return
        }
"""
D_NEW = D_OLD + """
        // `#call` runs `<pkg>:<tool> {json}` lines through [callTool].
        if (text.startsWith(CALL_PREFIX)) {
            runCallSelfTest(text.removePrefix(CALL_PREFIX))
            return
        }
"""

H_OLD = """    /**
     * Exercises the interactive path, one call per step.
"""
H_NEW = """    /** Runs each `<pkg>:<tool> {json}` line in [spec] through [callTool]. */
    private fun runCallSelfTest(spec: String) {
        for (line in spec.lines()) {
            val l = line.trim()
            if (l.isEmpty()) continue
            val i = l.indexOf(' ')
            val target = (if (i < 0) l else l.substring(0, i)).trim()
            val args = (if (i < 0) "{}" else l.substring(i + 1)).trim().ifBlank { "{}" }
            val c = target.indexOf(':')
            if (c <= 0 || c == target.length - 1) {
                diag("callselftest: bad target '$target'")
                continue
            }
            val started = System.currentTimeMillis()
            val out = runCatching {
                callTool(target.substring(0, c), target.substring(c + 1), args)
            }.getOrElse { "threw: ${it.message}" }
            diag("callselftest $target -> ${out.take(600)} (${System.currentTimeMillis() - started}ms)")
        }
    }

""" + H_OLD

C_OLD = """        /** Marker prefix that runs the multi-step interactive (PTY) self test. */
        const val PTY_PREFIX = "#pty"
"""
C_NEW = C_OLD + """
        /** Marker prefix that calls `pkg:tool {json}` lines directly. */
        const val CALL_PREFIX = "#call"
"""

EDITS = [(D_OLD, D_NEW), (H_OLD, H_NEW), (C_OLD, C_NEW)]


def main() -> None:
    src = RT.read_text(encoding="utf-8")
    if 'const val CALL_PREFIX = "#call"' in src:
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