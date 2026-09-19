#!/usr/bin/env python3
"""patch_metadata_hjson_test.py — pin the HJSON METADATA contract, and ask the runner how to run it.

Two halves, and the second one is a question rather than a step.

The test half. `parseMetadata` is private, so it becomes `@VisibleForTesting
internal` -- the standard Android/Kotlin way to say "production function, also
reachable from the test source set", and `internal fun` is already the house style
here (`MainActivity.kt:521,533,543`, `OAuthHandler.kt:64`,
`IncomingShareHandler.kt:130,143`). No abstraction is invented for testability;
the function under test is the one production calls.

The fixture is the six packages' METADATA blocks **as they are in the assets**,
extracted here with the same expression the parser uses, not retyped -- and it is
the *whole* block, `/* METADATA` marker included, because that is what
`parseMetadata` is handed. The first CI run of this test proved the difference:
fixtures holding only the inside of the block (the capture group) came back null
from `parseMetadata` and failed all six assertions. That is the point of the
test: quoting is what makes these blocks HJSON, so a fixture written by hand
could quietly stop being HJSON and the test would keep passing. Each of the six
is named in its own test method, so a regression has to break six assertions
with names in them rather than one count.

The CI half used to live here. The step that runs this test was added as a probe,
asked the runner the question it could only answer itself -- java 17.0.20.1 is
present, `--config-only` writes the gitignored wrapper back, and
`:app:testDebugUnitTest` then runs 118 tests -- and became a gate. It moved to
`patch_ci_push_gate.py`, the script whose job is letting the checks that exist
actually run, which also asserts that the gate stays guarded: only pushes that
touch android/ pay its ~7 minutes.

Self-checks:

  1. The function is `internal` and annotated, still called by production, and
     still private in spirit: the annotation and the modifier are on one function.
  2. Six fixtures came out of the assets, and none of them is JSON: the check
     feeds each block to `json.loads` and fails if it parses, because a block
     `org.json` would accept proves nothing about the HJSON path. It also
     refuses a quoted `"name"` key, which the parser's expression relies on
     being bare -- and it refuses a fixture the parser's own expression does not
     match, which is the one thing that makes `parseMetadata` return null.
  3. The generated test names all six packages in its method names and asserts
     `name` against the value that package's own block declares, rather than
     against the file name -- automatic_ui_subagent declares
     `"Automatic_ui_subagent"`, and an assertion written from the file name
     would have been red on its first run.
  4. `$` is escaped exactly as `${'$'}` in the generated raw strings, because a
     raw Kotlin string treats a bare `$` as a template and would not compile.
  5. The workflow is neither written nor asserted here: this script owns the test
     and the annotation only. The Kotlin gate it used to add is asserted where it
     now lives, in `patch_ci_push_gate.py`.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntime.kt"
ASSETS = ROOT / "assets/operit_packages"
TEST = ROOT / "android/app/src/test/kotlin/com/psyche/kelivo/quickjs/OperitJsRuntimeMetadataTest.kt"

PACKAGES = (
    "automatic_ui_subagent",
    "code_runner",
    "operit_editor",
    "time",
    "various_search",
    "workflow",
)

# The same expression the runtime uses, so a fixture cannot drift from the parser.
METADATA_PATTERN = re.compile(r"/\*\s*METADATA\s*([\s\S]*?)\*/")

SIGNATURE = "    private fun parseMetadata(source: String): JSONObject? {"
ANNOTATED = (
    "    @VisibleForTesting\n"
    "    internal fun parseMetadata(source: String): JSONObject? {"
)

IMPORT_ANCHOR = "import android.util.Log\n"
IMPORT_ADD = IMPORT_ANCHOR + "import androidx.annotation.VisibleForTesting\n"


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def declared_name(block: str) -> str | None:
    """The value the block itself gives for `name`, quoted or not.

    The assertion has to expect what the block says rather than the asset's file
    name: automatic_ui_subagent declares `"Automatic_ui_subagent"`, so an assertion
    written from the file name would be red on its very first run.
    """
    match = re.search(r"^\s*name\s*:\s*(.+?)\s*$", block, re.M)
    return None if match is None else match.group(1).strip().strip('"')


# ---------------------------------------------------------------- the fixtures
blocks: dict[str, str] = {}
declared_names: dict[str, str] = {}
for name in PACKAGES:
    source_path = ASSETS / f"{name}.js"
    check(source_path.is_file(), f"missing asset {source_path.relative_to(ROOT)}")
    if not source_path.is_file():
        continue
    source = source_path.read_text(encoding="utf-8")
    match = METADATA_PATTERN.search(source)
    check(match is not None, f"{name}: no METADATA block in the asset")
    if match is None:
        continue
    block = match.group(0).strip()
    blocks[name] = block
    # The fixture has to be the whole block, marker included: `parseMetadata` is
    # handed JavaScript source and looks for `/* METADATA` itself. Feeding it only
    # the inside (group 1) returns null, which is exactly what the first CI run of
    # this test reported -- six AssertionErrors on the `assertNotNull`.
    check(
        METADATA_PATTERN.search(block) is not None,
        f"{name}: the fixture does not match the parser's own expression, so "
        "parseMetadata would return null for it",
    )
    # What the test guards is "org.json alone drops this block", so that is what is
    # checked -- not a proxy like "the name's value carries no quotes". Three of the
    # six quote it (`name: "workflow"`) and are still not JSON, because their keys
    # are unquoted, which is the property org.json trips over.
    try:
        json.loads(block)
    except ValueError:
        pass
    else:
        check(False, f"{name}: the block is valid JSON, so org.json alone would keep it")
    check(
        not re.search(r'^\s*"name"\s*:', block, re.M),
        f"{name}: the block's name key is quoted, so the block is not HJSON",
    )
    declared = declared_name(block)
    check(declared is not None, f"{name}: the block declares no name")
    if declared is not None:
        declared_names[name] = declared

# ------------------------------------------------------------------ the runtime
if RUNTIME.is_file():
    text = RUNTIME.read_text(encoding="utf-8")
    if ANNOTATED in text:
        print("  runtime: already annotated")
    else:
        count = text.count(SIGNATURE)
        check(count == 1, f"parseMetadata signature matched {count} times")
        if count == 1:
            text = text.replace(SIGNATURE, ANNOTATED, 1)
            print("  runtime: parseMetadata is internal and annotated")
    if IMPORT_ADD not in text:
        count = text.count(IMPORT_ANCHOR)
        check(count == 1, f"import anchor matched {count} times")
        if count == 1:
            text = text.replace(IMPORT_ANCHOR, IMPORT_ADD, 1)
            print("  runtime: import added")
    else:
        print("  runtime: import already present")
    RUNTIME.write_text(text, encoding="utf-8")

# ----------------------------------------------------------------- the test file
def kotlin_raw(block: str) -> str:
    """A Kotlin raw string with `$` escaped, since a bare one starts a template.

    The newlines around the block are real ones, and they also keep the closing
    `\"\"\"` off the block's last character: a raw string cannot end with a quote.
    """
    return '"""\n' + block.replace("$", "${'$'}") + '\n"""'


if blocks:
    methods = "\n\n".join(
        f"    @Test\n"
        f"    fun {name}_metadata_is_hjson() {{\n"
        f"        val parsed = runtime.parseMetadata({name.upper()})\n"
        f"        assertNotNull(\"the block did not parse at all\", parsed)\n"
        f"        assertEquals(\"{declared_names[name]}\", parsed!!.optString(\"name\"))\n"
        f"    }}"
        for name in PACKAGES
        if name in blocks
    )
    constants = "\n\n".join(
        f"        val {name.upper()} = {kotlin_raw(blocks[name])}" for name in PACKAGES if name in blocks
    )
    generated = (
        "package com.psyche.kelivo.quickjs\n"
        "\n"
        "import io.flutter.plugin.common.BinaryMessenger\n"
        "import java.nio.ByteBuffer\n"
        "import org.junit.Assert.assertEquals\n"
        "import org.junit.Assert.assertNotNull\n"
        "import org.junit.Test\n"
        "import org.junit.runner.RunWith\n"
        "import org.robolectric.RobolectricTestRunner\n"
        "import org.robolectric.RuntimeEnvironment\n"
        "import org.robolectric.annotation.Config\n"
        "\n"
        "/**\n"
        " * The six packages whose METADATA is HJSON, not JSON: their keys are unquoted, so\n"
        " * `org.json` alone rejects them and `listTools` drops them. Every fixture below is\n"
        " * the block copied out of `assets/operit_packages/<name>.js` by\n"
        " * `scripts/patch_metadata_hjson_test.py` -- the same expression the parser uses --\n"
        " * rather than retyped, because quoting is what makes the block HJSON and a fixture\n"
        " * typed by hand could stop being HJSON while the test stayed green. Each fixture is\n"
        " * the whole `/* METADATA ... */` block rather than the inside of one, because the\n"
        " * marker is what `parseMetadata` searches the source for: without it, all six come\n"
        " * back null.\n"
        " *\n"
        " * If the parse ever goes back to `JSONObject(text)` alone, all six fail: none of\n"
        " * these blocks is JSON. That is the regression this exists to catch, and it is why\n"
        " * each package is named in its own test rather than counted.\n"
        " *\n"
        " * Each assertion expects the name its own block declares rather than the asset's\n"
        " * file name, which is why automatic_ui_subagent expects the upstream's\n"
        " * `Automatic_ui_subagent`: capitalised in the asset, not typed that way here.\n"
        " */\n"
        "@RunWith(RobolectricTestRunner::class)\n"
        "@Config(sdk = [28], manifest = Config.NONE)\n"
        "class OperitJsRuntimeMetadataTest {\n"
        "    private val runtime = OperitJsRuntime(RuntimeEnvironment.getApplication(), Messenger())\n"
        "\n"
        "    /** `MethodChannel` only stores the messenger; nothing is dispatched here. */\n"
        "    private class Messenger : BinaryMessenger {\n"
        "        override fun send(channel: String, message: ByteBuffer?) = Unit\n"
        "\n"
        "        override fun send(\n"
        "            channel: String,\n"
        "            message: ByteBuffer?,\n"
        "            callback: BinaryMessenger.BinaryReply?,\n"
        "        ) = Unit\n"
        "\n"
        "        override fun setMessageHandler(\n"
        "            channel: String,\n"
        "            handler: BinaryMessenger.BinaryMessageHandler?,\n"
        "        ) = Unit\n"
        "    }\n"
        "\n"
        "    private companion object {\n"
        f"{constants}\n"
        "    }\n"
        "\n"
        f"{methods}\n"
        "}\n"
    )
    TEST.parent.mkdir(parents=True, exist_ok=True)
    TEST.write_text(generated, encoding="utf-8")
    print(f"  test: written with {len(blocks)} fixtures")
else:
    check(TEST.is_file(), "no fixtures were extracted and no test file exists")

runtime = RUNTIME.read_text(encoding="utf-8") if RUNTIME.is_file() else ""
test = TEST.read_text(encoding="utf-8") if TEST.is_file() else ""

# 1. Production still calls it, once, through the internal function.
check(ANNOTATED in runtime, "the runtime function is not internal+annotated")
check(runtime.count("parseMetadata(source)") >= 1, "production no longer calls parseMetadata")
check("import androidx.annotation.VisibleForTesting" in runtime, "the annotation is not imported")

# 2. Six real fixtures, and each one is something org.json alone rejects.
check(len(blocks) == 6, f"only {len(blocks)} fixtures came out of the assets")
for name, block in blocks.items():
    try:
        json.loads(block)
    except ValueError:
        continue
    check(False, f"{name}: the fixture is valid JSON, so org.json alone would keep it")

# 3. Named per package, each asserting the name its own block declares.
for name in PACKAGES:
    check(f"fun {name}_metadata_is_hjson()" in test, f"no test method names {name}")
    check(
        f'assertEquals("{declared_names.get(name, "")}", parsed!!.optString("name"))' in test,
        f"no assertion names {name} by its declared name",
    )

# 4. Raw strings are escaped.
check("${'$'}" in test or "$" not in "".join(blocks.values()), "a bare $ survived into a raw string")
for name, block in blocks.items():
    escaped = block.replace("$", "${'$'}")
    check(escaped in test, f"{name}: the fixture in the test is not the asset's block")

# The workflow is neither written nor asserted here any more. The step that runs
# this test became a gate, and it lives in `patch_ci_push_gate.py` -- the script
# whose job is letting the checks that exist actually run -- together with the
# android/ guard that decides when it runs. This script now owns two things: the
# test, and the annotation that makes it callable.

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: six named fixtures pin the HJSON path; the gate that runs them lives in patch_ci_push_gate.py")