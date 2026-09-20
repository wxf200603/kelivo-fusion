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
}