#!/usr/bin/env python3
"""Add `Tools.Files.readBinary` - the second method that throws, and the first
one to leave a return value the call sites actually read.

Contract, measured from the four call sites rather than guessed:

  file_converter.js:177   readBinary(outputJpg)    1 arg  -> .size, .contentBase64.length
  openai_draw.js:202      readBinary(tmpPath)      1 arg  -> ?.contentBase64
  siliconflow_draw.js:283 readBinary(trimmedPath)  1 arg  -> && .contentBase64
  xai_draw.js:279         readBinary(trimmedPath)  1 arg  -> && .contentBase64

so the payload must be `{contentBase64, size}`; no call site passes an
`environment`, and no call site tolerates a missing `contentBase64` (all four
either dereference it or throw their own error when it is falsy). Every target
file is a just-produced or already-asserted artifact (`file_converter.js:173`
asserts with `exists`, `openai_draw.js:199` gates on `downloadResult.successful`,
`siliconflow_draw.js:279` / `xai_draw.js:275` assert with `exists`), i.e. 4/4 are
"should exist" reads: a failure is a real error, so this method throws like
Files.deleteFile.

Five contract points are stated in the KDoc, all of them measured:
  * no workspace root / no path binding / no containment check - File(path) only,
    exactly like fileMkdir/fileWrite/fileExists/fileDelete;
  * no `environment` parameter (nothing to read, nothing to pretend to route on);
  * `contentBase64` is single-line base64 with **no** `data:` prefix and no line
    breaks (siliconflow_draw.js:288 and xai_draw.js:286 build their own
    `data:<mime>;base64,`). The implementation uses java.util.Base64's basic
    encoder, which by definition never wraps: the repo already uses that class
    (RootfsCertificates.kt:7), its output is byte-identical to the Android-only
    NO_WRAP variant, and it keeps an Android framework class out of a call path
    that unit tests may one day run on a plain JVM;
  * `size` is the raw byte count; no size/base64 ratio is promised (no call site
    depends on one, and padding makes it inexact);
  * an empty file is a *successful* read: `{contentBase64:"", size:0}`.
  * plus the size risk: whole file in memory, base64 (1.33x), JSON string copy -
    ~3x peak; no limit is enforced here, and a native-bridge payload limit has
    not been verified.

Five anchors, each required to be unique; anything else aborts without writing.
There is no import anchor any more: the read is written fully qualified, so the
import block stays exactly as it was.
The `THROWING_METHODS` set is renamed to `throwingMethods` in the same edit,
because the Files family convention it now carries is no longer a deleteFile
special case.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration ------------------------------
E1_OLD = "    fun fileDelete(path: String, recursive: Boolean)\n"
E1_NEW = E1_OLD + r'''
    /**
     * Reads [path] as base64.
     *
     * Deliberately not workspace-scoped: no workspace root, no path binding and no
     * containment check. [path] is the caller's absolute path, exactly as
     * [fileMkdir] / [fileWrite] / [fileExists] / [fileDelete] treat theirs. There is
     * no `environment` parameter to read, and nothing to pretend to route on.
     *
     * Returned JSON contains:
     *   - `contentBase64`: single-line base64 - no line breaks, no `data:` prefix
     *     (siliconflow_draw.js:288 and xai_draw.js:286 build `data:<mime>;base64,`
     *     by hand, so a line break in the payload would corrupt the data URL);
     *   - `size`: the raw byte count, **not** the base64 length. No ratio between
     *     `size` and `contentBase64` is promised: none of the four call sites
     *     depends on one, and padding makes that arithmetic inexact.
     *
     * An empty file is a **successful** read: `{contentBase64:"", size:0}`. This
     * answers "could it be read", not "is the content useful" - the call sites that
     * want non-empty content check for that themselves.
     *
     * Throws when the file cannot be read: a missing target -> ENOENT; a directory
     * -> EISDIR; anything else surfaces as the underlying java.io failure.
     *
     * **No size limit.** The whole file is read into memory, base64-encoded (1.33x),
     * and shipped as a JSON string (another copy). Peak memory is roughly 3x the file
     * size. Call sites currently only pass images (a few MB), so this is not a
     * practical problem - but it is a known risk, not a guarantee. A native-bridge
     * payload limit has not been verified; if one exists, this doc must be updated.
     */
    fun fileReadBinary(path: String): JSONObject
'''

# --- KelivoWorkspaceHost.kt: implementation -------------------------------
# No import anchor: the read is written fully qualified (`java.util.Base64...`), so
# the import block stays exactly as it was.
E3_OLD = (
    "        if (!target.delete()) {\n"
    '            throw IOException("EIO: failed to delete: ${target.path}")\n'
    "        }\n"
    "    }\n"
)
E3_NEW = E3_OLD + r'''
    override fun fileReadBinary(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as fileMkdir / fileWrite / fileExists /
        // fileDelete: `path` is the caller's absolute path, and there is no workspace
        // root to check it against. A directory is caught before `isFile`, because a
        // directory is not a file either.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        if (!target.isFile) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        val bytes = target.readBytes()
        // Single-line is part of the contract, not a detail, and java.util.Base64's
        // basic encoder is what guarantees it: the call sites build
        // `data:<mime>;base64,<contentBase64>` by hand, so a line break in the payload
        // would silently corrupt the data URL. Same class the repo already uses for
        // certificates (RootfsCertificates.kt:7).
        return JSONObject()
            .put("contentBase64", java.util.Base64.getEncoder().encodeToString(bytes))
            .put("size", bytes.size.toLong())
    }
'''

# --- OperitHostDispatcher.kt: branch, usage site, throwingMethods ----------
E4_OLD = r'''                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''
E4_NEW = r'''                "Tools.Files.readBinary" -> {
                    // args[1] would be `environment`; it is deliberately not read, for the same
                    // reason as deleteFile above: the dispatcher serves a single host and
                    // KelivoHost.fileReadBinary() takes no environment. Reading it here would be
                    // pretending we route on it. No workspace root and no path binding either -
                    // the path reaches File(path) exactly as it does for every other Files method.
                    host.fileReadBinary(args?.optString(0).orEmpty()).toString()
                }
                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''

E5_OLD = (
    "            // Declared in THROWING_METHODS; every other method keeps returning an object.\n"
    "            if (method in THROWING_METHODS) throw t\n"
)
E5_NEW = (
    "            // Declared in throwingMethods; every other method keeps returning an object.\n"
    "            if (method in throwingMethods) throw t\n"
)

E6_OLD = r'''        /**
         * Methods that surface a failure as a JS throw instead of an error object.
         *
         * Files.deleteFile is the first: the packages call it inside try/catch
         * (openai_draw.js:207) and expect the throw, and the native layer converts a
         * Kotlin exception into `JS_ThrowInternalError` (quickjs_jni.cpp:621).
         */
        val THROWING_METHODS = setOf("Tools.Files.deleteFile")
'''
E6_NEW = r'''        /**
         * Methods that surface a failure as a JS throw instead of an error object.
         *
         * This started with Files.deleteFile and now includes Files.readBinary. The
         * Files family convention is: file operations that touch the real filesystem
         * throw on failure, because (a) callers wrap them in try/catch and expect the
         * throw, and (b) returning an error object degrades the failure into a
         * meaningless placeholder at the call site (contentBase64 empty / undefined.length).
         *
         * Exceptions will be individual methods whose callers genuinely want an error
         * object to inspect — not the default.
         */
        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
        )
'''

EDITS = [
    (HOST, E1_OLD, E1_NEW),
    (WSHOST, E3_OLD, E3_NEW),
    (DISPATCH, E4_OLD, E4_NEW),
    (DISPATCH, E5_OLD, E5_NEW),
    (DISPATCH, E6_OLD, E6_NEW),
]


def main() -> None:
    sources = {p: p.read_text(encoding="utf-8") for p, _, _ in EDITS}

    if "fileReadBinary" in "".join(sources.values()):
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

    # Pass 3: the edits have to be there, and the old name has to be gone.
    leftover = [
        p.name
        for p in dict.fromkeys(p for p, _, _ in EDITS)
        if "THROWING_METHODS" in p.read_text(encoding="utf-8")
    ]
    if leftover:
        raise SystemExit(f"old name survived in: {', '.join(leftover)}")
    print("applied: 3 files")


if __name__ == "__main__":
    main()
