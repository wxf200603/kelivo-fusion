#!/usr/bin/env python3
"""patch_operit_metadata_hjson.py — read ToolPkg METADATA as HJSON, like the upstream.

Six of the thirty-one bundled packages declare their METADATA without quotes
(`name: code_runner`), which is HJSON, so `JSONObject(source.substring(...))`
threw and `parseMetadata` returned null. That is the whole of the 31 -> 25 gap:
the six are `automatic_ui_subagent`, `code_runner`, `operit_editor`, `time`,
`various_search` and `workflow`.

The upstream's shape, adopted here, is at `ref/ex/Operit-main/.../PackageManager.kt`:

    :2467   val metadataPattern = \"\"\"/\\*\\s*METADATA\\s*([\\s\\S]*?)\\*/\"\"\".toRegex()
    :2468   val match = metadataPattern.find(jsContent)
    :2471   match.groupValues[1].trim()
    :2258   org.json.JSONObject(JsonValue.readHjson(metadataString).toString())

One deliberate difference, and it is the reason this is not a copy: the upstream
returns `"{}"` when there is no block, because its caller only ever wants a map.
Callers here need `null` to mean "nothing to list", which is what the per-name
skip log reports -- `?: continue` hid six real packages once already. So the
extraction and the parse are the upstream's, and the return type stays
`JSONObject?` with the empty/unparseable cases returning null.

`skipString` existed only to walk the braces by hand and goes with them; a
regular expression does not need to skip strings, and a helper left behind would
be dead code that looks load-bearing.

The skip message is reworded, because after this commit "not strict JSON" is no
longer a reason anything can be skipped for. `scripts/patch_operit_listtools_
observability.py` pins that message in its own checks, so it moves too -- a
script whose assertions no longer hold is worse than no script.

Self-checks:

  1. The expression is the upstream's, character for character, and appears once.
  2. `JsonValue.readHjson` is used, exactly once, and `skipString` is gone with
     every reference to it -- no dead helper left behind.
  3. The null contract survives: two `return null` paths and no `"{}"` fallback,
     which is the one place this must not imitate the upstream.
  4. The old wording is gone from both files that carried it.
  5. Nothing else in the file moved: the neighbouring methods and the companion's
     constants are still there.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
OBSERVABILITY = ROOT / "scripts/patch_operit_listtools_observability.py"

OLD_SKIP = '                diag("listTools: skip $name (METADATA is not strict JSON)")\n'
NEW_SKIP = (
    '                diag("listTools: skip $name (no METADATA block, or it will not'
    ' parse as HJSON)")\n'
)

IMPORT_ANCHOR = "import org.json.JSONArray\n"
IMPORT_ADD = "import org.hjson.JsonValue\n" + IMPORT_ANCHOR

OLD_PARSE = (
    "    // Extracts the JSON object from the leading METADATA block (see parseMetadata).\n"
    "    private fun parseMetadata(source: String): JSONObject? {\n"
    "        val marker = source.indexOf(\"METADATA\")\n"
    "        if (marker < 0) return null\n"
    "        val open = source.indexOf('{', marker)\n"
    "        if (open < 0) return null\n"
    "        var depth = 0\n"
    "        var i = open\n"
    "        while (i < source.length) {\n"
    "            when (source[i]) {\n"
    "                '\"' -> i = skipString(source, i)\n"
    "                '{' -> depth++\n"
    "                '}' -> {\n"
    "                    depth--\n"
    "                    if (depth == 0) {\n"
    "                        return runCatching { JSONObject(source.substring(open, i + 1))"
    " }.getOrNull()\n"
    "                    }\n"
    "                }\n"
    "            }\n"
    "            i++\n"
    "        }\n"
    "        return null\n"
    "    }\n"
    "\n"
    "    private fun skipString(s: String, start: Int): Int {\n"
    "        var i = start + 1\n"
    "        while (i < s.length) {\n"
    "            when (s[i]) {\n"
    "                '\\\\' -> i++\n"
    "                '\"' -> return i\n"
    "            }\n"
    "            i++\n"
    "        }\n"
    "        return s.length - 1\n"
    "    }\n"
)

NEW_PARSE = (
    "    // Extracts the METADATA object at the top of a package. The block is HJSON, not\n"
    "    // JSON -- `name: code_runner` without quotes is valid there -- so it goes through\n"
    "    // org.hjson rather than org.json alone. Extraction and parse are the upstream's\n"
    "    // (PackageManager.kt:2467 and :2258); the return type is not, because callers\n"
    "    // here report \"no block\" separately from an empty one. See METADATA_PATTERN.\n"
    "    private fun parseMetadata(source: String): JSONObject? {\n"
    "        val match = METADATA_PATTERN.find(source) ?: return null\n"
    "        val block = match.groupValues[1].trim()\n"
    "        if (block.isEmpty()) return null\n"
    "        return runCatching { JSONObject(JsonValue.readHjson(block).toString()) }.getOrNull()\n"
    "    }\n"
)

COMPANION_ANCHOR = '        const val DIAG_FILE = "operit_js_diag.log"\n'
COMPANION_ADD = (
    COMPANION_ANCHOR
    + "\n"
    + "        /**\n"
    + "         * The upstream's METADATA expression, character for character:\n"
    + "         * `PackageManager.kt:2467`. Raw string on purpose -- the backslashes are\n"
    + "         * the regular expression's, not escapes.\n"
    + "         */\n"
    + '        val METADATA_PATTERN = """/\\*\\s*METADATA\\s*([\\s\\S]*?)\\*/""".toRegex()\n'
)

OBSERVABILITY_OLD = 'for fragment in ("asset unreadable", "METADATA is not strict JSON", DUMP_NAME):'
OBSERVABILITY_NEW = (
    "# The skip message was reworded by the hjson commit: \"not strict JSON\" stopped\n"
    "# being a reason anything could be skipped for once HJSON parsed.\n"
    'for fragment in (\n'
    '    "asset unreadable",\n'
    '    "no METADATA block, or it will not parse as HJSON",\n'
    "    DUMP_NAME,\n"
    "):"
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def edit(path: Path, anchor: str, replacement: str, marker: str, label: str) -> None:
    if not path.is_file():
        check(False, f"missing {path.relative_to(ROOT)}")
        return
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"  {label}: already applied")
        return
    count = text.count(anchor)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count == 1:
        path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")
        print(f"  {label}: applied")


edit(RUNTIME, IMPORT_ANCHOR, IMPORT_ADD, "import org.hjson.JsonValue", "import")
edit(RUNTIME, OLD_PARSE, NEW_PARSE, "METADATA_PATTERN.find(source)", "parseMetadata")
edit(RUNTIME, OLD_SKIP, NEW_SKIP, "no METADATA block", "skip message")
# The marker is the declaration, not the name: the parseMetadata edit above already
# put `METADATA_PATTERN` into this file, so a marker of the bare name would report
# this edit as applied and skip it. Check 1 would then fail with the pattern
# missing, which is exactly how the same mistake surfaced in the previous script.
edit(RUNTIME, COMPANION_ANCHOR, COMPANION_ADD, 'val METADATA_PATTERN = """', "companion pattern")
edit(OBSERVABILITY, OBSERVABILITY_OLD, OBSERVABILITY_NEW, "no METADATA block", "observability script")

runtime = RUNTIME.read_text(encoding="utf-8") if RUNTIME.is_file() else ""
observability = OBSERVABILITY.read_text(encoding="utf-8") if OBSERVABILITY.is_file() else ""

# 1. The upstream's expression, once.
expression = (
    'val METADATA_PATTERN = """/\\*\\s*METADATA\\s*([\\s\\S]*?)\\*/""".toRegex()'
)
check(runtime.count(expression) == 1, "the pattern is not the upstream's expression, once")

# 2. HJSON is used, and nothing is left pointing at the hand-rolled walk.
check(runtime.count("JsonValue.readHjson(") == 1, "readHjson is not used exactly once")
check("skipString" not in runtime, "skipString is still referenced")
check("source.substring(" not in runtime, "the substring extraction is still there")

# 3. The null contract, and no fallback borrowed from the upstream.
check(runtime.count("private fun parseMetadata(source: String): JSONObject?") == 1, "parseMetadata changed shape")
parse_body = runtime.split("private fun parseMetadata")[1].split("private fun ")[0]
check(parse_body.count("return null") == 2, "parseMetadata lost a null path")
check('"{}"' not in parse_body, "the upstream's empty-map fallback was copied in")

# 4. The old wording is no longer *pinned*. It survives exactly once in the
# observability script, as the replacement text of the edit that script made --
# that is history and a replay needs it. What must not survive is a check that
# asserts the old wording is what the tree says.
check("not strict JSON" not in runtime, "the runtime still carries the old skip wording")
check(
    observability.count("METADATA is not strict JSON") == 1,
    "the old wording is either gone from the script or pinned in more than one place"
    f" (found {observability.count('METADATA is not strict JSON')})",
)
check("no METADATA block" in observability, "the script does not pin the new wording")

# 5. The neighbours are intact.
for kept in (
    "private fun buildToolSchema(",
    "private fun readPackageSource(",
    'const val ASSET_DIR = "operit_packages"',
    'const val DIAG_FILE = "operit_js_diag.log"',
    "private companion object {",
):
    check(kept in runtime, f"a neighbouring declaration disappeared: {kept}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: METADATA is parsed as HJSON by the upstream's expression, and null still means skip")