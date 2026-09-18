#!/usr/bin/env python3
"""patch_android_hjson.py — declare hjson, and record where its licence came from.

The six tool packages that `listTools` silently drops are the six whose METADATA
is HJSON rather than JSON (`name: code_runner` instead of `"name": "code_runner"`),
so `org.json.JSONObject` rejects them. The upstream parses the same blocks with
`org.hjson.JsonValue`, which is what this starts paying for: the dependency, its
licence, and the compliance note. The parsing change itself is the next commit,
so this one moves no behaviour.

Three things, all verifiable here:

  * `android/app/build.gradle.kts` gains `org.hjson:hjson:3.0.0`, written out
    rather than referenced: this project has no version catalog (there is no
    `libs.versions.toml` anywhere in it), which is also why the neighbouring
    Shizuku and xz lines are spelled out. The version is the one the upstream
    declares -- `ref/ex/Operit-main/gradle/libs.versions.toml:45` `hjson = "3.0.0"`,
    `:174` `{ group = "org.hjson", name = "hjson" }`.
  * `third_party/hjson/LICENSE` is the MIT text, fetched verbatim from the URL the
    artifact's own POM declares (`hjson-3.0.0.pom` -> "The MIT License (MIT)" ->
    https://github.com/hjson/hjson-java/blob/master/LICENSE). It carries two
    copyright lines, EclipseSource 2013/2014 and Christian Zangl 2015-2016, and
    check 2 below pins the file to the bytes that were fetched rather than to a
    transcription.
  * `docs/merge/04-许可证合规.md` gets the entry in all three lists it keeps: the
    component-licence table, the `third_party/` checklist, and the tree.

Deliberately not in this commit, though the same document is open in front of us:
its `third_party/quickjs/LICENSE` line describes a file that does not exist (the
directory is empty), it promises a `NOTICE` that is absent, and it names the tool
packages `assets/packages/*.js` where the code and the tree say
`assets/operit_packages/`. Those are three separate drifts with three separate
fixes, and mixing them into a commit about one dependency would bury them.

Self-checks:

  1. The version appears once, in that dependency, and the neighbouring
     dependencies are still there -- declaring hjson must not disturb them.
  2. `third_party/hjson/LICENSE` is present, is 1126 bytes, and every marker of
     the MIT text is in it, so the file is the fetched licence and not a summary.
  3. The compliance document names hjson in the table, the checklist and the tree,
     and the three entries it already had are intact.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "android/app/build.gradle.kts"
DOC = ROOT / "docs/merge/04-许可证合规.md"
LICENSE = ROOT / "third_party/hjson/LICENSE"

DEP_ANCHOR = '    implementation("org.tukaani:xz:1.10")\n'
DEP_ADD = (
    DEP_ANCHOR
    + "    // HJSON: ToolPkg METADATA is HJSON, not JSON, so org.json alone drops six\n"
    "    // real packages (MIT licensed; see third_party/hjson/LICENSE).\n"
    '    implementation("org.hjson:hjson:3.0.0")\n'
)

TABLE_ANCHOR = "| llama.cpp | MIT | 保留声明 |\n"
TABLE_ADD = (
    TABLE_ANCHOR
    + "| hjson（ToolPkg METADATA 解析，`org.hjson:hjson:3.0.0`） | **MIT** | 保留版权与许可声明 |\n"
)

CHECKLIST_ANCHOR = "   third_party/quickjs/LICENSE     (MIT)\n"
CHECKLIST_ADD = CHECKLIST_ANCHOR + "   third_party/hjson/LICENSE       (MIT)\n"

TREE_ANCHOR = "    └── quickjs/LICENSE        ← MIT 原文\n"
TREE_ADD = (
    "    ├── quickjs/LICENSE        ← MIT 原文\n"
    "    └── hjson/LICENSE          ← MIT 原文\n"
)

LICENSE_MARKERS = (
    "The MIT License (MIT)\n",
    "Copyright (c) 2013, 2014 EclipseSource\n",
    "Copyright (c) 2015-2016 Christian Zangl\n",
    "Permission is hereby granted, free of charge",
    "THE SOFTWARE IS PROVIDED \"AS IS\"",
    "OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE\n",
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def edit(path: Path, anchor: str, replacement: str, marker: str, label: str) -> None:
    """Applies one anchored edit, or reports it as already applied."""
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
        print(f"  {label}: added")


edit(BUILD, DEP_ANCHOR, DEP_ADD, "org.hjson:hjson:3.0.0", "gradle dependency")
edit(DOC, TABLE_ANCHOR, TABLE_ADD, "| hjson（ToolPkg METADATA 解析", "doc: licence table")
edit(DOC, CHECKLIST_ANCHOR, CHECKLIST_ADD, "third_party/hjson/LICENSE", "doc: checklist")
# Each marker has to identify *its own* edit. The document keeps three lists that
# all name hjson, so `hjson/LICENSE` is already present the moment the checklist
# above is written -- and the tree edit was skipped on the first run for exactly
# that reason, which check 3 then reported. This marker is the tree line itself.
edit(DOC, TREE_ANCHOR, TREE_ADD, "    ├── quickjs/LICENSE", "doc: tree")

# 1. One declaration, and its neighbours untouched.
build = BUILD.read_text(encoding="utf-8") if BUILD.is_file() else ""
check(build.count('implementation("org.hjson:hjson:3.0.0")') == 1, "hjson is not declared exactly once")
for neighbour in (
    'implementation("dev.rikka.shizuku:api:13.1.5")',
    'implementation("org.tukaani:xz:1.10")',
    'testImplementation("junit:junit:4.13.2")',
    'testImplementation("org.robolectric:robolectric:4.16.1")',
):
    check(neighbour in build, f"a neighbouring dependency disappeared: {neighbour}")

# 2. The licence is the fetched text, byte for byte.
check(LICENSE.is_file(), "third_party/hjson/LICENSE is missing")
if LICENSE.is_file():
    raw = LICENSE.read_bytes()
    text = raw.decode("utf-8")
    check(len(raw) == 1126, f"the licence is {len(raw)} bytes, not the 1126 that were fetched")
    for marker in LICENSE_MARKERS:
        check(marker in text, f"the licence is missing: {marker!r}")

# 3. All three lists in the document carry it, and the old entries survive.
doc = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
check(doc.count("hjson") >= 3, f"the document mentions hjson {doc.count('hjson')} times (expected 3)")
for kept in (
    "third_party/operit/LICENSE      (LGPL-3.0)",
    "third_party/kelivo/LICENSE      (AGPL-3.0)",
    "third_party/quickjs/LICENSE     (MIT)",
    "| llama.cpp | MIT | 保留声明 |",
    "    ├── quickjs/LICENSE        ← MIT 原文",
):
    check(kept in doc, f"the document lost a line: {kept!r}")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: hjson is declared, its licence is recorded verbatim, and the document says where")