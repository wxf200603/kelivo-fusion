#!/usr/bin/env python3
"""Add `Tools.Files.read` - the fourth throwing method, and the first whose first
argument is polymorphic.

Contract, measured from the three call sites rather than guessed:

  code_runner.js:827      read(filePath)                       1 arg, bare string
  file_converter.js:191   read(outputHtml)                     1 arg, bare string
  operit_editor.js:2614   read({ path, environment: "android" }) 1 arg, OBJECT

So `args[0]` has two shapes. The object form is a single site and a single shape:
it carries exactly {path, environment}; operit_editor.js uses positional arguments
for the other twelve Files calls in the same file (exists(path,"android"),
mkdir(path,true,"android"), list(dir,"android"), copy(...,"android","android"), ...),
so even the file that passes an object does not do it anywhere else. Only `.path`
is consumed; the object's `environment` is ignored, exactly like every other
environment in this family.

Failure semantics: **throws** (ENOENT / EISDIR / EACCES / CharacterCodingException),
with the success path returning {"content": "..."}:

  * All three call sites sit under a try/catch. code_runner exports every function
    through `wrap()` (catch -> complete({success:false, message})), file_converter's
    selftest has its own try/catch around the read, and operit_editor's three
    callers are either inside a try/catch or inside debug_install_*'s try ->
    finish({success:false}). A throw cannot take the process down.
  * Returning an error object instead would degrade the reason at every site:
    code_runner.js:828 reads `.content` and reports "无法读取文件: <path>" (ENOENT
    and EACCES become the same sentence), file_converter.js:191 would hit
    `undefined.includes` as a TypeError, and operit_editor.js:2615 would hand
    `undefined` to a parser that reports it as bad JSON.

Sub-decisions, each taken deliberately:

  * strict UTF-8 decoding - CharsetDecoder with REPORT on malformed input and
    unmappable characters, not readText(). A lenient decode replaces bad bytes with
    U+FFFD and lets operit_editor.js:2729-2741 report the damage as a manifest
    *parse* error, i.e. an encoding problem wearing a content problem's clothes.
  * an empty file is a successful read: {content:""}, symmetric with readBinary.
    code_runner.js:828 turns empty content into its own error - that is that tool's
    business.
  * a leading BOM is not stripped: none of the three call sites handles one, so
    stripping would be inventing behaviour. It is stated in the KDoc instead.
  * no size limit, same as readBinary: whole file in memory, shipped as a JSON
    string. Stated, not enforced.

Six anchors, each required to be unique; anything else aborts without writing.
`throwingMethods` gains its fourth member and its KDoc sentence in the same edit.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration ------------------------------
E1_OLD = "    fun fileWriteBinary(path: String, base64: String): JSONObject\n"
E1_NEW = E1_OLD + r'''
    /**
     * Reads [path] as UTF-8 text.
     *
     * On success returns {"content": "<file text>"}.
     * On failure throws (ENOENT / EISDIR / EACCES / CharacterCodingException for
     * bytes that are not valid UTF-8).
     *
     * Deliberately not workspace-scoped: no workspace root, no path binding and no
     * containment check. [path] is the caller's absolute path, exactly as
     * [fileMkdir] / [fileWrite] / [fileExists] / [fileDelete] / [fileReadBinary] /
     * [fileWriteBinary] treat theirs. There is no `environment` parameter to read,
     * and nothing to pretend to route on.
     *
     * Decoding is strict: a CharsetDecoder with REPORT on malformed input and on
     * unmappable characters, not readText(). A lenient decode replaces bad bytes
     * with U+FFFD and hands the damage downstream, where operit_editor.js:2729-2741
     * reports it as a manifest *parse* error - an encoding problem wearing a content
     * problem's clothes. Here it fails at the read, where it happened.
     *
     * An empty file is a **successful** read: {content:""}. This answers "could it
     * be read", not "is the content useful"; code_runner.js:828 turns empty content
     * into its own error, which is that tool's business, not this one's.
     *
     * A leading UTF-8 BOM is **not** stripped: it arrives as U+FEFF at the start of
     * `content`, and a downstream JSON.parse will reject it. None of the three call
     * sites handles a BOM today, so stripping one would be inventing behaviour; it
     * is stated here so the next reader knows what they inherited.
     *
     * **No size limit**, same as [fileReadBinary]: the whole file is read into memory
     * and shipped as a JSON string, so peak memory is roughly twice the file size.
     *
     * The dispatcher accepts either a bare path or the single {path, environment}
     * object that operit_editor.js:2614 passes - only `.path` is read, and that
     * object's own `environment` is ignored like every other one in this family.
     */
    fun fileRead(path: String): JSONObject
'''

# --- KelivoWorkspaceHost.kt: imports + implementation ----------------------
E2_OLD = "import java.nio.charset.StandardCharsets\n"
E2_NEW = (
    "import java.nio.ByteBuffer\n"
    "import java.nio.charset.CodingErrorAction\n"
    + E2_OLD
)

E3_OLD = (
    "        return JSONObject()\n"
    '            .put("successful", true)\n'
    '            .put("details", "${bytes.size} bytes written")\n'
    "    }\n"
)
E3_NEW = E3_OLD + r'''
    override fun fileRead(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as every other Files method here: `path` is the
        // caller's absolute path, and there is no workspace root to check it against.
        // A directory is caught before `isFile`, because a directory is not a file.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        if (!target.isFile) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        val bytes = target.readBytes()
        // Strict UTF-8, on purpose: a lenient decode would replace bad bytes with U+FFFD
        // and let the damage surface downstream as a JSON.parse failure, which reads
        // like a content problem. Reporting it here keeps the encoding problem where it
        // happened. CharacterCodingException is left untranslated for the callers.
        val text = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
        // Not a .size / .encoding / .truncated payload: no call site reads anything but
        // `content` (code_runner.js:828, file_converter.js:191, operit_editor.js:2615).
        return JSONObject().put("content", text)
    }
'''

# --- OperitHostDispatcher.kt: branch + throwingMethods --------------------
E4_OLD = r'''                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''
E4_NEW = r'''                "Tools.Files.read" -> {
                    // args[0] has two shapes: two of the three call sites pass a bare string
                    // (code_runner.js:827, file_converter.js:191) and one passes an object
                    // (operit_editor.js:2614). The object carries exactly {path, environment};
                    // only `.path` is consumed here, and `.environment` is not read - the same
                    // discipline as every other environment in this family. The object form is
                    // an outlier even in its own file: the other twelve Files calls in
                    // operit_editor.js pass environment as a positional string.
                    val a0 = args?.opt(0)
                    val path = when (a0) {
                        is String -> a0
                        is JSONObject -> a0.optString("path")
                        else -> ""
                    }
                    host.fileRead(path).toString()
                }
                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''

E5_OLD = (
    "         * This started with Files.deleteFile and now includes Files.readBinary and\n"
    "         * Files.writeBinary. The\n"
)
E5_NEW = (
    "         * This started with Files.deleteFile and now includes Files.readBinary,\n"
    "         * Files.writeBinary and Files.read. The\n"
)

E6_OLD = r'''        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
            "Tools.Files.writeBinary",
        )
'''
E6_NEW = r'''        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
            "Tools.Files.writeBinary",
            "Tools.Files.read",
        )
'''

EDITS = [
    (HOST, E1_OLD, E1_NEW),
    (WSHOST, E2_OLD, E2_NEW),
    (WSHOST, E3_OLD, E3_NEW),
    (DISPATCH, E4_OLD, E4_NEW),
    (DISPATCH, E5_OLD, E5_NEW),
    (DISPATCH, E6_OLD, E6_NEW),
]


def main() -> None:
    sources = {p: p.read_text(encoding="utf-8") for p, _, _ in EDITS}

    if "fileRead(path: String)" in "".join(sources.values()):
        print("already applied")
        return

    # Pass 1: every anchor has to be unique before anything touches the disk.
    for path, old, _ in EDITS:
        found = sources[path].count(old)
        if found != 1:
            raise SystemExit(f"{path.name}: anchor not unique, found {found}")

    # Pass 2: write.
    for path, old, new in EDITS:
        sources[path] = sources[path].replace(old, new, 1)
    for path in dict.fromkeys(p for p, _, _ in EDITS):
        path.write_text(sources[path], encoding="utf-8")

    # Pass 3: the branch, the object tolerance and the fourth member must be there.
    dispatch = DISPATCH.read_text(encoding="utf-8")
    for needle in (
        '"Tools.Files.read" ->',
        'is JSONObject -> a0.optString("path")',
        '"Tools.Files.read",',
    ):
        if needle not in dispatch:
            raise SystemExit(f"missing after write: {needle}")
    print("applied: 3 files")


if __name__ == "__main__":
    main()