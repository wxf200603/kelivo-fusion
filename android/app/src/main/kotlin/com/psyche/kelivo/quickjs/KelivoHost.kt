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
}