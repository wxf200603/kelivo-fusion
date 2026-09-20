#!/usr/bin/env python3
"""Add `Tools.Files.writeBinary` - the third throwing method, and the first that
writes to the real filesystem.

Contract, measured from the three call sites rather than guessed:

  file_converter.js:170    writeBinary(inputPng, pngBase64)              2 args, result ignored
  minimax_draw.js:528      writeBinary(filePath, normalizeBase64(...))   2 args, reads .successful/.details
  openai_draw.js:235       writeBinary(filePath, normalizeBase64(...))   2 args, reads .successful/.details

Failure semantics: **throws**, with the success path returning an object. Not a
choice between the two - both halves are required:

  * All three call sites sit under a try/catch (file_converter.js:164-182 is the
    selftest's own; minimax_draw.js:588-603 and openai_draw.js:259-274 are the
    package wrappers that turn an exception into complete({success:false, ...}),
    so a throw cannot take the process down.
  * file_converter.js:170 ignores the result entirely, so returning an error
    object there would be silent - and the next line (convert_file) would report
    the failure as "Input file not found", blaming the input for a write failure.
  * The other two read `.details` only when `!successful`. Our generic error
    object has neither `successful` nor `details`, so returning one would print
    "保存图片失败: undefined" and lose the reason; an exception carries it into
    the wrapper's message.
  * On success an object is mandatory: `if (!writeResult.successful)` turns
    `undefined` into `true`, so a void success would make both draw packages
    throw "保存图片失败: undefined" on a perfectly good write.

Sub-decisions, each taken deliberately:

  * java.util.Base64.getDecoder() (basic), NOT getMimeDecoder(): the MIME decoder
    silently drops characters outside the alphabet, i.e. writes damaged bytes.
    Malformed input leaves as IllegalArgumentException, untranslated.
  * No `data:` prefix is stripped: all three call sites normalise first
    (minimax_draw.js:373-383 and the same helper in openai_draw.js), so a prefixed
    payload fails loudly in the strict decoder instead of being half-decoded.
  * parentFile?.mkdirs(), same as fileWrite.
  * no temp file + rename: this is a non-atomic overwrite, stated in the KDoc.
  * an empty base64 writes a zero-byte file rather than failing - "no bytes" is
    not "cannot write", symmetric with readBinary's empty file.

Five anchors, each required to be unique; anything else aborts without writing.
`throwingMethods` gains its third member in the same edit.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration ------------------------------
E1_OLD = "    fun fileReadBinary(path: String): JSONObject\n"
E1_NEW = E1_OLD + r'''
    /**
     * Writes [base64] (decoded) to [path], overwriting it.
     *
     * On success returns {"successful": true, "details": "<n> bytes written"}.
     * On failure throws (ENOENT / EISDIR / EACCES / IllegalArgumentException for
     * malformed base64 / IOException for write errors).
     *
     * Callers read .successful only on the success path — they must not rely on
     * .details being meaningful when successful: the two draw wrappers read
     * .details only when !successful, and this method never returns !successful
     * (it throws instead). The field exists so a caller that still does
     * `if (!r.successful) throw ...` does not mis-fire on the success path.
     *
     * Deliberately not workspace-scoped: no workspace root, no path binding and no
     * containment check. [path] is the caller's absolute path, exactly as
     * [fileMkdir] / [fileWrite] / [fileExists] / [fileDelete] / [fileReadBinary]
     * treat theirs. There is no `environment` parameter to read, and nothing to
     * pretend to route on.
     *
     * [base64] is bare base64: no `data:` prefix and no whitespace. Each call site
     * normalises its own input first (minimax_draw.js:373, and the same helper in
     * openai_draw.js), so a prefixed payload is not stripped here - the strict
     * decoder rejects it loudly instead of writing half-decoded bytes.
     *
     * Parent directories are created when missing (same as [fileWrite]), the write
     * is a non-atomic overwrite (no temp file + rename), and an empty [base64]
     * writes a zero-byte file rather than failing: "no bytes" is not "cannot
     * write", the same way an empty file is a successful read in [fileReadBinary].
     */
    fun fileWriteBinary(path: String, base64: String): JSONObject
'''

# --- KelivoWorkspaceHost.kt: implementation -------------------------------
E2_OLD = (
    "        return JSONObject()\n"
    '            .put("contentBase64", java.util.Base64.getEncoder().encodeToString(bytes))\n'
    '            .put("size", bytes.size.toLong())\n'
    "    }\n"
)
E2_NEW = E2_OLD + r'''
    override fun fileWriteBinary(path: String, base64: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as fileMkdir / fileWrite / fileExists / fileDelete /
        // fileReadBinary: `path` is the caller's absolute path, and there is no workspace
        // root to check it against. A directory is caught before anything is decoded, so
        // EISDIR never depends on the payload being valid.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        // The strict (basic) decoder on purpose: the MIME decoder silently ignores
        // characters outside the alphabet, which would write damaged bytes to disk and
        // report success. Malformed input leaves here as IllegalArgumentException,
        // untranslated - the callers name it in their own failure message.
        val bytes = java.util.Base64.getDecoder().decode(base64)
        target.parentFile?.mkdirs()
        target.writeBytes(bytes)
        // Not void: both draw packages do `if (!writeResult.successful)`, so `undefined`
        // would read as a failure on the success path.
        return JSONObject()
            .put("successful", true)
            .put("details", "${bytes.size} bytes written")
    }
'''

# --- OperitHostDispatcher.kt: branch + throwingMethods --------------------
E3_OLD = r'''                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''
E3_NEW = r'''                "Tools.Files.writeBinary" -> {
                    // args[2] would be `environment`; it is deliberately not read, for the same
                    // reason as deleteFile and readBinary above: the dispatcher serves a single
                    // host and KelivoHost.fileWriteBinary() takes no environment. No workspace
                    // root and no path binding either - the path reaches File(path) exactly as
                    // it does for every other Files method.
                    host.fileWriteBinary(
                        args?.optString(0).orEmpty(),
                        args?.optString(1).orEmpty(),
                    ).toString()
                }
                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''

E4_OLD = (
    "         * This started with Files.deleteFile and now includes Files.readBinary. The\n"
)
E4_NEW = (
    "         * This started with Files.deleteFile and now includes Files.readBinary and\n"
    "         * Files.writeBinary. The\n"
)

E5_OLD = r'''        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
        )
'''
E5_NEW = r'''        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
            "Tools.Files.writeBinary",
        )
'''

EDITS = [
    (HOST, E1_OLD, E1_NEW),
    (WSHOST, E2_OLD, E2_NEW),
    (DISPATCH, E3_OLD, E3_NEW),
    (DISPATCH, E4_OLD, E4_NEW),
    (DISPATCH, E5_OLD, E5_NEW),
]


def main() -> None:
    sources = {p: p.read_text(encoding="utf-8") for p, _, _ in EDITS}

    if "fileWriteBinary" in "".join(sources.values()):
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

    # Pass 3: the new branch and the third set member have to be there.
    dispatch = DISPATCH.read_text(encoding="utf-8")
    if '"Tools.Files.writeBinary" ->' not in dispatch:
        raise SystemExit("branch missing after write")
    if '"Tools.Files.writeBinary",' not in dispatch:
        raise SystemExit("throwingMethods member missing after write")
    print("applied: 3 files")


if __name__ == "__main__":
    main()