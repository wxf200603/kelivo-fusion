#!/usr/bin/env python3
"""Surface a package load failure instead of a silent "tool not found".

`executeTool` dropped the module eval result (`rt.eval(...)`) and added the
package to `loaded` unconditionally, so a package that threw while it was
evaluated left `module.exports` empty and every later call reported
`tool not found: <name>` - a missing-tool message for a broken package.

Two failure shapes, and checking `success` alone misses the second:

  1. the native layer caught a JS throw -> `EvalResult.success == false`;
  2. the payload is not JSON (empty / truncated) -> `parseEvalResult` calls
     `JSONObject(resultJson)` and throws `JSONException`.

Only `rt.eval(...)` is guarded; `readPackageSource` is a different failure and
is reported before this point.

Anchors: `rt.eval(buildString` and `globalThis.__pkgs[` each appear **twice**
(the load eval and the per-call eval), so neither can be a unique anchor. This
script guards on the two strings that ARE unique - the loader's `var module =`
line and `loaded.add(pkg)` - and aborts without writing if either is not
exactly once.

Same discipline as the other scripts/patch_*.py.
"""
from pathlib import Path

RT = Path(__file__).resolve().parent.parent / (
    "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
)

DECL_OLD = "    private val loaded = mutableSetOf<String>()\n"
DECL_NEW = DECL_OLD + (
    "\n"
    "    /**\n"
    "     * Packages whose load already failed, with the reason, so a repeat call\n"
    "     * reports it instead of re-running the eval and degrading to a\n"
    "     * \"tool not found\" message.\n"
    "     */\n"
    "    private val failedLoads = mutableMapOf<String, String>()\n"
)

BLOCK_OLD = r'''            rt.eval(buildString {
                append("var module = { exports: {} }; var exports = module.exports;\n")
                append(source)
                append("\n;globalThis.__pkgs = globalThis.__pkgs || {};")
                append("globalThis.__pkgs[").append(JSONObject.quote(pkg)).append("] = module.exports; undefined;")
            }, "$pkg.js")
            rt.executePendingJobs()
            loaded.add(pkg)
'''

BLOCK_NEW = r'''            // A package that threw while it was evaluated leaves module.exports
            // empty, and every later lookup then says "tool not found" - which
            // reads like a missing tool, not a broken package. Load once and
            // remember why it failed.
            failedLoads[pkg]?.let { return err(it) }

            // Only the eval is guarded; a missing source is reported earlier.
            // Two shapes, and checking `success` alone would miss the second:
            //   1. native caught a JS throw -> EvalResult.success == false;
            //   2. the payload is not JSON (empty / truncated) -> parse throws.
            val loadAttempt = runCatching {
                rt.eval(buildString {
                    append("var module = { exports: {} }; var exports = module.exports;\n")
                    append(source)
                    append("\n;globalThis.__pkgs = globalThis.__pkgs || {};")
                    append("globalThis.__pkgs[").append(JSONObject.quote(pkg)).append("] = module.exports; undefined;")
                }, "$pkg.js")
            }
            val loadFailure = loadAttempt.fold(
                onSuccess = { result ->
                    if (result.success) {
                        null
                    } else {
                        listOfNotNull(result.errorMessage, result.errorStack, result.errorDetailsJson)
                            .joinToString(" | ")
                            .ifBlank { "eval returned success=false" }
                    }
                },
                onFailure = { error -> "${error.javaClass.simpleName}: ${error.message}" },
            )
            if (loadFailure != null) {
                val message = "package $pkg failed to load: $loadFailure"
                failedLoads[pkg] = message
                return err(message)
            }
            rt.executePendingJobs()
            loaded.add(pkg)
'''

CLEAR_OLD = "        loaded.clear()\n"
CLEAR_NEW = CLEAR_OLD + "        failedLoads.clear()\n"

GUARDS = [
    "var module = { exports: {} }; var exports = module.exports;",
    "loaded.add(pkg)",
]
EDITS = [(DECL_OLD, DECL_NEW), (BLOCK_OLD, BLOCK_NEW), (CLEAR_OLD, CLEAR_NEW)]


def main() -> None:
    src = RT.read_text(encoding="utf-8")
    if "failedLoads" in src:
        print("already applied")
        return
    for guard in GUARDS:
        found = src.count(guard)
        if found != 1:
            raise SystemExit(f"anchor not unique: {guard!r} found {found}")
    for old, new in EDITS:
        found = src.count(old)
        if found != 1:
            raise SystemExit(f"expected 1 match, found {found}")
        src = src.replace(old, new)
    RT.write_text(src, encoding="utf-8")
    print("applied: OperitJsRuntime.kt")


if __name__ == "__main__":
    main()