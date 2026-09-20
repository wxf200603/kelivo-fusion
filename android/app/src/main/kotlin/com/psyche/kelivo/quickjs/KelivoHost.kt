package com.psyche.kelivo.quickjs

import org.json.JSONObject

/**
 * The host capability surface required by the ported Operit JS tool packages.
 *
 * The contract below was **measured empirically**, not guessed: see
 * `docs/merge/05-super_admin契约验证.md` and `scripts/mock_host_test.js`,
 * where `assets/operit_packages/super_admin.js` was executed under Node with a
 * mock host to capture exactly which methods it calls and which return fields
 * it reads.
 *
 * Implementations are expected to be backed by Kelivo's existing workspace
 * primitives:
 *   - [terminalCreate] / [terminalScreen] / [terminalInput] -> PtySessions
 *   - [terminalExec]                                       -> ExecRunner + ProotCommand
 *   - [shell]                                              -> Shizuku / root
 *   - [fileMkdir] / [fileWrite]                            -> workspace file API
 *
 * NOTE: no implementation ships yet. Stage 2 of the roadmap wires these to the
 * existing `com.psyche.kelivo.workspace` classes.
 */
interface KelivoHost {

    /** Creates (or reuses) a terminal session and returns its id. */
    fun terminalCreate(sessionName: String): String

    /**
     * Runs a command and blocks until it finishes or [timeoutMs] elapses.
     *
     * Returned JSON **must** contain at least:
     * `output`, `exitCode`, `sessionId`, `timedOut`
     * (super_admin.js reads these field names directly).
     */
    fun terminalExec(sessionId: String, command: String, timeoutMs: Long?): JSONObject

    /**
     * Returns the visible screen of a terminal session.
     * Returned JSON **must** contain: `sessionId`, `rows`, `cols`, `content`.
     */
    fun terminalScreen(sessionId: String): JSONObject

    /** Writes raw input / a control key into a terminal session. */
    fun terminalInput(sessionId: String, args: JSONObject)

    /**
     * Executes a shell command with system privileges (Shizuku / root).
     * Returned JSON **must** contain: `output`, `exitCode`.
     */
    fun shell(command: String): JSONObject

    /** Creates a directory (recursively when [recursive] is true). */
    fun fileMkdir(path: String, recursive: Boolean)

    /** Writes [content] to [path], appending when [append] is true. */
    fun fileWrite(path: String, content: String, append: Boolean)

    /** Checks whether a file or directory exists at [path]. */
    fun fileExists(path: String, environment: String?): JSONObject

    /**
     * Deletes [path], throwing when it cannot be done.
     *
     * Throwing is deliberate and specific to this call: the packages invoke
     * `Tools.Files.deleteFile` inside try/catch (`openai_draw.js:207`) and
     * treat a failure as an exception, and the native layer turns a Kotlin
     * exception into `JS_ThrowInternalError` (`quickjs_jni.cpp:621`).
     *
     * missing target -> ENOENT; directory with [recursive] = false -> EISDIR;
     * a `delete()` that returns false -> EIO.
     */
    fun fileDelete(path: String, recursive: Boolean)

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
}