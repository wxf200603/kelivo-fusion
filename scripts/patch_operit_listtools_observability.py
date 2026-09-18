#!/usr/bin/env python3
"""patch_operit_listtools_observability.py — stop the tool list from failing quietly.

`listTools()` currently reports two numbers and nothing else:

    listTools: 31 packages
    listTools: 25 entries

Six of the thirty-one packages never reach the output, and the one line that
could say which — `readPackageSource(name)?.let(::parseMetadata) ?: continue` —
collapses two very different failures ("the asset could not be read" and "the
METADATA block is not strict JSON") into the same silent `continue`.

This adds observation only. No parsing behaviour changes, no schema changes:

  * each skip is logged with its package name and its reason,
  * the emitted package names are logged in full,
  * the payload is written to `operit_js_listTools.json` so the raw return can be
    inspected and quoted instead of inferred from a count.

That last artefact is not decoration: the Dart loader is about to be diffed
against this exact payload field by field, and a count cannot be diffed.

Self-checks:

  1. The three anchors are present exactly once each.
  2. `parseMetadata` and `buildToolSchema` are untouched — this commit must not
     be able to change which tools the model sees.
  3. The dump names the same file the diff tooling will read.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"

DUMP_NAME = "operit_js_listTools.json"

SKIP_ANCHOR = (
    "            val meta = readPackageSource(name)?.let(::parseMetadata) ?: continue\n"
)
SKIP_REPLACEMENT = (
    "            val source = readPackageSource(name)\n"
    "            if (source == null) {\n"
    "                diag(\"listTools: skip $name (asset unreadable)\")\n"
    "                continue\n"
    "            }\n"
    "            val meta = parseMetadata(source)\n"
    "            if (meta == null) {\n"
    "                // Reported by name: `?: continue` hid six real packages\n"
    "                // behind a count that only ever looked plausible.\n"
    "                diag(\"listTools: skip $name (METADATA is not strict JSON)\")\n"
    "                continue\n"
    "            }\n"
)

EMIT_ANCHOR = '        diag("listTools: ${out.length()} entries")\n        return out.toString()\n'
EMIT_REPLACEMENT = (
    '        diag("listTools: ${out.length()} entries")\n'
    "        val emitted = (0 until out.length())\n"
    '            .mapNotNull { out.optJSONObject(it)?.optString("package") }\n'
    '            .filter { it.isNotEmpty() }\n'
    '        diag("listTools: emitted=${emitted.joinToString(",")}")\n'
    "        val payload = out.toString()\n"
    "        // Written out as well as counted: the Dart loader is diffed against\n"
    "        // this exact payload, and a count cannot be diffed.\n"
    "        runCatching {\n"
    f'            File(context.filesDir, "{DUMP_NAME}").writeText(payload)\n'
    "        }.onFailure { diag(\"listTools: dump failed: $it\") }\n"
    "        return payload\n"
)

EDITS = (
    ("skip reasons", SKIP_ANCHOR, SKIP_REPLACEMENT),
    ("payload dump", EMIT_ANCHOR, EMIT_REPLACEMENT),
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(RUNTIME.is_file(), f"missing {RUNTIME.relative_to(ROOT)}")
text = RUNTIME.read_text(encoding="utf-8") if RUNTIME.is_file() else ""
original = text

for label, anchor, replacement in EDITS:
    if replacement in text:
        print(f"  {label}: already applied")
        continue
    lines = text.splitlines(keepends=True)
    needle = anchor.splitlines(keepends=True)
    width = len(needle)
    hits = [
        index
        for index in range(len(lines) - width + 1)
        if lines[index:index + width] == needle
    ]
    check(len(hits) == 1, f"{label}: anchor matched {len(hits)} times (expected exactly 1)")
    if len(hits) == 1:
        lines[hits[0]:hits[0] + width] = replacement.splitlines(keepends=True)
        text = "".join(lines)
        print(f"  {label}: instrumented")

if text != original:
    RUNTIME.write_text(text, encoding="utf-8")

# 2. The parsing path itself must be byte-identical to before.
check(
    "private fun parseMetadata(source: String): JSONObject? {" in text,
    "parseMetadata was disturbed",
)
check(
    "private fun buildToolSchema(pkg: String, tool: String, entry: JSONObject): JSONObject {" in text,
    "buildToolSchema was disturbed",
)
check(
    "?.let(::parseMetadata) ?: continue" not in text,
    "the silent skip is still there",
)
for fragment in ("asset unreadable", "METADATA is not strict JSON", DUMP_NAME):
    check(fragment in text, f"missing instrumentation: {fragment}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: listTools now names every skip and dumps its payload")
print(f'  raw return -> <app files>/"{DUMP_NAME}"')