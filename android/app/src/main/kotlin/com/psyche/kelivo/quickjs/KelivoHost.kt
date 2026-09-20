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
     * unmappable characters, not readText(). A lenient decode replaces bad bytes with
     * U+FFFD and hands the damage downstream, where operit_editor.js:2729-2741 does
     * not report a parse error: its catch (2741-2743) carries only a comment and
     * swallows the JSON.parse failure into the regex fallback below. The error that
     * can survive is a missing-field one — manifest.toolpkg_id is required (2762) or
     * manifest.main is required (2765) — an encoding problem wearing a content
     * problem's clothes. Failing here, at the read, is how it stays an encoding problem.
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

    /**
     * Lists the directory at [path].
     *
     * On success returns {"entries": [{"name": "...", "isDirectory": true|false}, ...]}.
     * On failure throws (ENOENT / ENOTDIR / EIO).
     *
     * Deliberately not workspace-scoped: no workspace root, no path binding and no
     * containment check. [path] is the caller's absolute path, exactly as
     * [fileMkdir] / [fileWrite] / [fileExists] / [fileDelete] / [fileReadBinary] /
     * [fileWriteBinary] / [fileRead] treat theirs. There is no `environment`
     * parameter to read, and nothing to pretend to route on: the two call sites
     * pass the literal "android" (operit_editor.js:2700, 2838).
     *
     * An entry carries **only** `name` and `isDirectory`, because those are the only
     * two fields any call site reads: operit_editor.js:2702-2703 tests `name` and
     * filters on `isDirectory`, and 2840-2846 reads both. Nothing reads a size, an
     * mtime or a joined path, and a field the whole repository never reads is a
     * contract with no reader - cheap to add later, expensive to retract. The entry
     * speaks a boolean while [fileInfo] speaks "file"/"directory" as a string: that
     * asymmetry is what the two call families use, not a preference.
     *
     * An empty directory is a **successful** list: {"entries": []}. This answers
     * "what is in there", not "is there anything in there" - the same stance as an
     * empty file being a successful read in [fileRead]. The one call site that cannot
     * work with nothing says so itself, downstream: operit_editor.js:2871-2872 turns
     * zero copied files into "No packable files found".
     *
     * The order of `entries` is whatever java.io.File.listFiles() returns (readdir
     * order). It is **not** sorted, deliberately: neither call site depends on an
     * order (2701 and 2839 both just iterate), so sorting here would be inventing a
     * contract no caller asked for. Do not rely on the order.
     *
     * "." and ".." are **not** produced - File.listFiles() does not include them -
     * so operit_editor.js:2841's defensive filter of those two stays correct.
     *
     * Failure classes, and the one that is new to this family:
     *   - missing path -> ENOENT;
     *   - present but not a directory -> **ENOTDIR**. The family had no word for
     *     this before: EISDIR says the opposite, and ENOENT would be a lie about a
     *     path that is right there. Call sites branch on the message prefix, so the
     *     prefix is part of the contract.
     *   - File.listFiles() returning null after both checks passed -> EIO. This is
     *     also where an unreadable directory lands, because File.listFiles()
     *     collapses a permission failure into the same null - so EACCES cannot be
     *     separated from any other refusal here. Documented, not guessed at.
     *
     * **No size limit**: the whole listing is materialised in memory and shipped as
     * a JSON string, a directory with very many entries being the one input class
     * this method does not bound. No call site lists a directory it does not
     * already expect to be small (a package folder, the external package dir).
     */
    fun fileList(path: String): JSONObject

    /**
     * Returns only {"fileType": "file" | "directory"}.
     *
     * The single call site that reads a field (operit_editor.js:2588) uses
     * .fileType only, and the other (extended_file_tools.js:104) forwards the
     * whole object to the model without reading anything — that is "the caller
     * does not care yet", not "more fields are needed". Fields are cheap to add
     * and expensive to retract: a sizeBytes/lastModifiedMs/name here would be a
     * contract with no reader, so it is not added. When a caller needs one, add
     * it in its own commit with the KDoc updated to say who reads it.
     *
     * `fileType` is exactly "file" or "directory" (lower-case). Do NOT return
     * "folder": operit_editor.js:2794 has a local variable defaulting to "folder"
     * that is never compared against fileType, but 2799 does `=== "directory"`,
     * so a "folder" here would silently send the whole toolpkg-packing path
     * down the wrong branch.
     *
     * No workspace root, no path binding, no containment check: [path] is the
     * caller's absolute path, exactly as [fileList] / [fileRead] / [fileDelete]
     * treat theirs.
     *
     * Throws when the target cannot be inspected: missing -> ENOENT.
     */
    fun fileInfo(path: String): JSONObject
}