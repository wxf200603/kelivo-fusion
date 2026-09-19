#!/usr/bin/env python3
"""Let the on-device self test drive `NativeInterface.__call` with no package
in between.

`#call <pkg>:<tool> {json}` routes through the package layer, and the package
layer cannot produce the two cases the deleteFile contract is about:

  github.js:799          deleteFile(params.path, true)              recursive hardcoded
  file_converter.js:211  deleteFile(testDir, true)                  recursive hardcoded
  openai_draw.js:208     deleteFile(tmpPath)                        path is an internal tmp
  operit_editor.js:2599  deleteFile(path, true, "android")          inside a cleanup helper
  operit_editor.js:2716  deleteFile(candidatePath, false, "android")same
  extended_file_tools    no delete tool; github:delete_file deletes a remote

so `recursive=false` -- and therefore EISDIR -- is unreachable from any of the
31 packages, and so is ENOENT for a path the test chooses.

`host:<method>` closes that gap by evaluating
`NativeInterface.__call("<method>", "<args>")` in the runtime directly. The
argument text is passed through verbatim, which means it has to be the JSON
array `OperitHostDispatcher.kt:40` hands to `JSONArray(argsJson)`:

    #call host:Tools.Files.deleteFile ["/sdcard/operit-selftest",false]

SELF-TEST ONLY. Nothing is registered under this prefix, no package exports it,
and it goes away as soon as a package ships a delete whose arguments come from
the outside.

Two anchors, each required to be unique. Both are counted before either edit is
written, so an anchor that stops being unique aborts without touching the tree.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"

A_OLD = "            val c = target.indexOf(':')\n"
A_NEW = (
    "            // `host:<method>` skips the package layer and calls\n"
    "            // `NativeInterface.__call` directly.\n"
    "            //\n"
    "            // SELF-TEST ONLY: no tool is registered under this prefix and no\n"
    "            // package exports it. It exists because the cases this contract is\n"
    "            // about cannot be produced through the package layer -- every\n"
    "            // deleteFile call site hardcodes `recursive` (github.js:799,\n"
    "            // file_converter.js:211) or keeps the path inside a cleanup helper\n"
    "            // (openai_draw.js:208, operit_editor.js:2599/2716), so EISDIR\n"
    "            // (directory + recursive=false) and ENOENT for a path the test\n"
    "            // picks are unreachable from a package. Remove it the day one\n"
    "            // exposes a delete whose arguments come from the outside.\n"
    "            //\n"
    "            // The argument text reaches __call verbatim, so it is the JSON\n"
    "            // array OperitHostDispatcher.kt:40 parses with `JSONArray(...)`:\n"
    "            //\n"
    "            //     #call host:Tools.Files.deleteFile [\"/sdcard/t\",false]\n"
    "            //\n"
    "            // An expected failure arrives here as a `THREW: ...` line: the\n"
    "            // dispatcher rethrows for this method (THROWING_METHODS).\n"
    "            if (target.startsWith(HOST_PREFIX)) {\n"
    "                val method = target.removePrefix(HOST_PREFIX)\n"
    "                // `continue`, not `return`: one marker file carries several\n"
    "                // cases, and a return would silently drop the rest.\n"
    "                val rt = runtime ?: continue\n"
    "                val eval = rt.eval(\n"
    '                    "NativeInterface.__call(" +\n'
    '                        JSONObject.quote(method) + ", " +\n'
    '                        JSONObject.quote(args) + ")",\n'
    '                    "hostcall.js",\n'
    "                )\n"
    "                val out =\n"
    "                    if (eval.success) {\n"
    "                        eval.valueJson.orEmpty()\n"
    "                    } else {\n"
    '                        "THREW: ${eval.errorMessage}"\n'
    "                    }\n"
    '                diag("hostselftest $method -> $out")\n'
    "                continue\n"
    "            }\n"
    "\n"
    + A_OLD
)

B_OLD = (
    "        /** Marker prefix that calls `pkg:tool {json}` lines directly. */\n"
    '        const val CALL_PREFIX = "#call"\n'
)
B_NEW = B_OLD + (
    "\n"
    "        /**\n"
    "         * Marker prefix that drives `NativeInterface.__call` with no package in\n"
    "         * between. SELF-TEST ONLY -- see [runCallSelfTest].\n"
    "         */\n"
    '        const val HOST_PREFIX = "host:"\n'
)

EDITS = [
    (RUNTIME, A_OLD, A_NEW),
    (RUNTIME, B_OLD, B_NEW),
]


def main() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    if "HOST_PREFIX" in text:
        print("already applied")
        return

    # Counted and applied on the evolving text, written only after every anchor
    # has been accepted -- the first version of this script read the same
    # original text for both edits and wrote twice, so the second write threw
    # the first one away. The two anchors sit in different regions, so an
    # insertion from one cannot change the other's count.
    for path, old, new in EDITS:
        found = text.count(old)
        if found != 1:
            raise SystemExit(f"{path.name}: anchor not unique, found {found}")
        text = text.replace(old, new, 1)

    RUNTIME.write_text(text, encoding="utf-8")
    print(f"applied: 1 file, {len(EDITS)} anchors")


if __name__ == "__main__":
    main()
