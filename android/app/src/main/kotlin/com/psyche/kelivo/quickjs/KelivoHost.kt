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

    /**
     * Copies [source] to [destination].
     *
     * On success returns **an empty object**, {} .
     *
     * No call site reads a field from this result: three of the four discard it
     * outright (operit_editor.js:2858, 2947, 3069 - bare `await`s), and the fourth
     * only tests `!!result` before passing the whole object to the model
     * (extended_file_tools.js:100). The only shape the callers pin down is "a
     * non-null object", because `!!result` is false for `undefined`. A field
     * nothing reads is a contract with no reader, so none is invented here.
     *
     * On failure throws: missing source -> ENOENT; a directory source with
     * [recursive] = false -> EISDIR; a filesystem refusal -> EIO.
     *
     * **No workspace root, no path binding, no containment check**: [source] and
     * [destination] are the caller's absolute paths, exactly as [fileMkdir] /
     * [fileWrite] / [fileDelete] / [fileReadBinary] / [fileWriteBinary] /
     * [fileRead] / [fileList] / [fileInfo] treat theirs. [destination] is also
     * **not** a directory to drop the source into - that is cp's rule, not this
     * one. It names the result, which is why every call site builds it with
     * path_join(...) instead of passing a folder.
     *
     * **The two environments are ignored, and cross-environment copy is not
     * implemented.** This is the one place where a package promises the model
     * something the host does not do: extended_file_tools.js:40-41 declares
     * `source_environment` and `dest_environment`, and the package description
     * advertises "复制文件/目录（支持跨环境复制）" / "copy ... (supports
     * cross-environment copy)". The dispatcher reads neither argument, because
     * there is nothing to route on - this host serves one namespace, in which
     * "android" means "the device". Documented as a gap rather than silently
     * accepted, so the discrepancy is on the record instead of in a model's
     * expectation.
     *
     * [recursive] mirrors the package's own declared default
     * (extended_file_tools.js:39, "default: false"): a directory source without it
     * is an EISDIR, not a half-copy. No call site in this repository ever passes
     * `true` - all three operit_editor sites copy single files - so the recursive
     * path is exercised only by the acceptance driver.
     *
     * An existing destination is **overwritten**, deliberately:
     *   - a file destination is replaced, non-atomically, the same stance as
     *     [fileWrite] with append=false and [fileWriteBinary];
     *   - a directory destination is **merged into**, not cleared first: entries
     *     the source does not carry survive. There is no pruning, and no call site
     *     copies onto an existing directory, so that is a documented choice rather
     *     than a measured requirement.
     * Replacement is the intended reading: both install paths delete the target
     * themselves immediately before copying and log "replacing target file before
     * copy" (operit_editor.js:2946/2947 and 3068/3069).
     *
     * A copy onto the same path is a **no-op returning {}**, not an error: reading
     * and writing the same file would truncate it before it was read, which is the
     * one silently destructive outcome this method could produce. The callers
     * already read that case as "nothing to do" (operit_editor.js:2943 and 3066
     * skip the copy and log exactly that).
     *
     * Copies are **streamed**, not buffered: unlike [fileRead] and
     * [fileReadBinary], a copy has no reason to hold the payload in memory.
     */
    fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject

    /**
     * Moves [source] to [destination]. Recursive by definition: the signature offers no
     * non-recursive reading, so a directory always moves whole.
     *
     * On success returns **an empty object**, {} , and that {} means exactly one thing:
     * **the file is at the destination and the source is gone. It never means "we
     * tried".** The only caller in the tree depends on precisely that. daily_life.js:1048
     * moves a screenshot out of the app's own storage into a user-given path and then logs
     * "截图已保存到: <path>" (:1050) without checking the result -- that line is true only
     * if this returns {} once the bytes are actually at [destination].
     *
     * **Across devices is the ordinary case here, not the corner.** The screenshot lands
     * in the app's own directory (daily_life.js:1039) and the destination is usually under
     * /sdcard, i.e. across the FUSE/ext4 boundary, where rename(2) cannot work at all. So
     * the implementation renames when it can and falls back to copy-then-delete when it
     * cannot. That fallback is **not atomic**: between its two halves both copies exist. A
     * failure is reported with the side it damaged rather than rolled back into a lie --
     * an incomplete copy removes the destination it wrote (unless that destination was
     * already a directory, which may hold entries the source never carried); a failed
     * source deletion leaves a complete destination beside a possibly partial source.
     *
     * No workspace root, no path binding, no containment check: both paths are the
     * caller's absolute paths, exactly as [fileCopy] / [fileDelete] treat theirs. A file
     * onto an existing directory, or a directory onto an existing file, is EISDIR and is
     * refused before anything is written.
     *
     * `environment` is not read, and **cross-environment moves are not implemented**:
     * extended_file_tools.js:30 declares the argument and this host serves one namespace,
     * so there is nothing to route on. The package does not advertise the capability the
     * way copy_file does, so the gap is smaller than [fileCopy]'s -- but it is a gap, and
     * it is recorded as one rather than quietly ignored.
     *
     * Moving onto an existing directory **merges into it rather than clearing it**:
     * entries the source does not carry survive. Both that and one more asymmetry are
     * inherited from rename(2) rather than chosen here -- a rename onto a non-empty
     * directory fails, so the merge can only happen on the copy route, and the copy route
     * also creates missing parents (copyFileTo calls `parentFile?.mkdirs()`) where the
     * rename route does not.
     *
     * Throws on failure: missing source -> ENOENT; file onto directory or the reverse ->
     * EISDIR; a filesystem refusal -> EIO, with the message naming the incomplete side.
     */
    fun fileMove(source: String, destination: String): JSONObject

    /**
     * Writes the contents of [source] into a ZIP archive at [destination].
     *
     * On success returns **an empty object**, {} . The only real call site discards it
     * (operit_editor.js:2879 is a bare `await`) and the package wrapper only tests
     * `!!result` (extended_file_tools.js:109), so no field is invented here.
     *
     * **What the archive promises.** A standard ZIP: entries are deflated, their names
     * are relative paths with `/` separators, a directory entry ends in `/`, and the
     * order of entries is not promised (it is a stable depth-first walk with siblings
     * sorted by name, which is convenient to read but not part of the contract). The
     * compression level, zip64, timestamps and external attributes are **not**
     * promised: two of the three consumers cannot be read from here -- the platform's
     * ToolPkg installer, and whatever unzips the archive on a desktop -- so the
     * promise is kept to the smallest set they can all rely on.
     *
     * **Recursive by definition**: the package declares no `recursive` parameter, so
     * a directory is always packed whole, empty subdirectories included (they are
     * written as their own entries; without that they would not exist after
     * unzipping).
     *
     * [includeRootDirectory] mirrors the package's own flag, whose declared default
     * is **true** (extended_file_tools.js:59, "keep the source directory name as the
     * top-level folder"):
     *   - `true`: entries are prefixed with [source]'s directory name, so the archive
     *     contains one top-level folder;
     *   - `false`: entry names are relative to [source], so its contents become the
     *     archive. This is the shape the only caller needs, and the reason is on the
     *     record: operit_editor.js:2870 stages a filtered copy of the package "so the
     *     whole directory is not packed into the toolpkg", :2873-2877 requires the
     *     manifest to be at the root of that staging directory before zipping, and the
     *     consumer unzips the `.toolpkg` and looks for the manifest at the extraction
     *     root (:2810-2819). An absolute entry name would break that path outright.
     *
     * A **file** source ignores [includeRootDirectory] -- the package scopes the flag
     * to directories -- and produces a single entry named after the file.
     *
     * No workspace root, no path binding, no containment check: both paths are the
     * caller's absolute paths, exactly as [fileCopy] / [fileMove] treat theirs. The
     * destination's missing parent directories **are** created, the same stance as
     * [fileWrite] and [fileWriteBinary].
     *
     * `environment` is not read: extended_file_tools.js:59 declares it and this host
     * serves one namespace, so there is nothing to route on.
     *
     * Throws on failure: missing source -> ENOENT; a destination **inside** the source
     * -> IllegalArgumentException (the archive would be packed from bytes that change
     * while they are packed, so it is refused rather than left to filesystem timing);
     * an unlistable source or an archive that cannot be written -> EIO.
     *
     * **A failure can leave a partial archive at [destination].** This method does not delete
     * it, the same stance as [fileCopy] and [fileMove], which do not roll back either -- the
     * difference is that a half-written archive is inert garbage rather than somebody's data,
     * which is why not deleting it is acceptable at all. It is not acceptable for it to be
     * silent, hence this paragraph.
     *
     * A destination **equal** to the source is not guarded, and its behaviour is
     * **undefined**: the guard above covers the shape the round asked for (the source is an
     * ancestor of the destination's parent, or that parent itself), and this shape has no
     * observed caller -- the only one reads a staging directory while writing its archive
     * into a separate temp build directory.
     */
    fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject

    /**
     * Extracts a ZIP archive into [destination], answering `{}`.
     *
     * Signature and answer are the measured ones: the only call site
     * (`operit_editor.js:2810`, the `.toolpkg` install path) discards the result, and the
     * package wrapper only tests `!!result` (`extended_file_tools.js:111-113`), so no field is
     * invented for either of them to ignore.
     *
     * **Nothing is written when an entry name is unsafe.** The entry table is read first and
     * every name is checked -- a `..` segment, an absolute name, or a symbolic-link entry --
     * and the call is refused with `IllegalArgumentException("unsafe entry name: <name>")`
     * before the destination is touched at all. The device's own `/system/bin/unzip` refuses
     * those names too, but only as it reaches them, so an archive with a benign member first
     * leaves that member behind and drops what follows (probed: a benign / hostile / benign
     * archive extracts the first member, then exits 1). The archive here is a seekable file,
     * so this implementation can be stricter than the reference tool and does not leave a
     * partial destination behind. A symbolic-link entry belongs to the same family as `..`:
     * a `.toolpkg` has no legitimate use for one, and a link target is the same escape wearing
     * different clothes.
     *
     * [destination] is created if it does not exist (`mkdirs`), which is what the model-facing
     * path needs: `extended_file_tools.js:112` passes the caller's path through untested,
     * while the one real caller creates the directory itself one line before calling
     * (`operit_editor.js:2809`). A [destination] that exists as a **file** is refused with
     * `IllegalArgumentException("EISDIR: destination is a file, not a directory: <dst>")`,
     * which is [fileMove]'s sentence for the same shape.
     *
     * **A source inside its own destination is refused**, with
     * `IllegalArgumentException("source is inside destination: <src> under <dst>")`. That is
     * the reverse of [fileZip]'s guard rather than a copy of it: there the packed tree
     * contains the archive, here the destination contains the archive being read, and reading
     * a file while overwriting files around it is the same self-reference in the other
     * direction.
     *
     * An **empty archive** is not an error: the destination is created and `{}` is answered,
     * the same stance [fileReadBinary] and [fileWriteBinary] take on empty input.
     *
     * **Not promised:** permission bits, timestamps, zip64, encrypted archives, or any
     * property of the extracted files beyond their contents. The only consumer that was read
     * needs the manifest to appear at the extraction root (`operit_editor.js:2814`) and the
     * main entry to exist under it (`:2820-2822`), so that is the contract; entry order,
     * compression method and attributes are not.
     */
    fun fileUnzip(source: String, destination: String): JSONObject

    /**
     * Downloads [url] to [destination], answering a `FileOperationData`-shaped object.
     *
     * **A failure is answered, not thrown.** The reference implementation returns
     * `FileOperationData(operation = "download", path, successful = false, details)` on every
     * failure path (`StandardFileSystemTools.kt:4326-4495`), and every in-repo caller branches
     * on `successful` / reads `details` (`zhipu_draw.js:165-168` and eight siblings), so this
     * member is deliberately **not** in the dispatcher's `throwingMethods` -- it sits with
     * [fileRead] / [fileList] / [fileInfo], not with [fileDelete] / [fileWriteBinary]. The
     * answered keys are `operation`, `env`, `path`, `successful`, `details`; the last two are
     * the ones the JS reads.
     *
     * Only `http://` and `https://` are accepted; anything else is refused with the reference
     * tool's own sentence (`"URL must start with http:// or https://"`). The parent directory of
     * [destination] is created when missing and an existing file is overwritten -- neither more
     * nor less than the reference tool. A [headers] object is applied as request properties, and
     * a malformed one is ignored rather than refused (fail-open, matching `:4298-4312`).
     *
     * Implemented with `java.net.HttpURLConnection` and no new dependency: the Android module
     * carries no HTTP client at all (0 hits for `HttpURLConnection` / `okhttp` / `retrofit` /
     * `ktor` / `volley`), and the manifest already allows cleartext (`AndroidManifest.xml:5`
     * INTERNET, `:50 usesCleartextTraffic="true"`).
     *
     * **Not implemented on purpose: the options overload.** `files.d.ts:242` also declares
     * `download({ url?, visit_key?, link_number?, image_number?, destination, environment?,
     * headers? })`; its `visit_key` / `link_number` / `image_number` form is backed upstream by a
     * browser-visit cache (`StandardWebVisitTool.getCachedVisitResult`, `:4340`) that this host
     * has no equivalent for, and nothing under `assets/operit_packages/` calls that form (0
     * hits). It is therefore absent here **and said so**, rather than left as a form that looks
     * usable and is not: a call with a blank url answers the reference tool's own sentence. This
     * is a recorded gap -- see the download round's handoff note.
     *
     * **Not promised:** progress reporting, segmented download, retries, resume, size limits,
     * timeout tuning, or any property of the bytes beyond "the response body was written to
     * [destination]".
     */
    fun fileDownload(
        url: String,
        destination: String,
        environment: String?,
        headers: JSONObject?,
    ): JSONObject
}