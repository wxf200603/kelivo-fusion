#!/usr/bin/env python3
"""Map Tools.Files.move onto KelivoHost.fileMove.

Measured, not assumed:

  extended_file_tools.js:24-31   move_file(source, destination, environment)
                                 -- ONE optional environment, and the description
                                 promises no cross-environment move (copy_file's does)
  extended_file_tools.js:95-98   the only reader: `!!result` truthiness, plus a
                                 pass-through of `data` to the model. No field is
                                 read anywhere, so the payload is {}.
  daily_life.js:1039             the source is the platform screenshot path, i.e.
                                 the app's own storage
  daily_life.js:1047-1050        mkdir the destination dir, move, then LOG
                                 "截图已保存到: <path>" without checking anything

That last line is the contract this round exists to keep: {} must mean "the file
is at the destination and the source is gone", never "we tried".

Design decisions, each with its reason:

  * renameTo is tried first; a `false` sends every failure down one copy-then-
    delete route. java.io.File discards the errno, so "why" is not knowable at
    this level, and the two causes that matter (a filesystem boundary, ENOTEMPTY
    on a non-empty destination directory) both have to end up on that route
    anyway -- the merge in the second case can only happen there.
  * same-path move returns {} without touching the disk. NOT style: the fallback
    would be copyFileTo(src, src), which truncates the source before reading it,
    and the deleteTree after it removes the only copy.
  * file onto an existing directory, and directory onto an existing file, are
    EISDIR *before* anything runs. Both shapes are refused by rename(2) and by
    the copy helpers alike, and checking them here is what keeps the "copy
    incomplete" message honest: from here on, that message means something may
    have been written.
  * the copy half removes the destination it wrote, EXCEPT when the destination
    was already a directory -- it can hold entries the source never carried, and
    deleting those would be worse than the condition being reported.
  * the delete half never rolls the destination back: by then the source may
    already be partially removed, so deleting the destination would destroy the
    only complete copy left. The message says which side is damaged.

Anchors: five, each required unique inside its own file. Anything else aborts
before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check. The self-check also
refuses a diff that removes any line other than the five anchors, and refuses a
diff touching a file outside the three, because "insert only" is the shape this
patch promises.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration -------------------------------
# Note: this file ends without a trailing newline. The anchor and the replacement
# both end on the closing brace so that quirk is preserved rather than "fixed".

H_OLD = ("    fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject\n"
         "}")

H_KDOC = '''    /**
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
}'''

# --- OperitHostDispatcher.kt: branch + throwingMethods member + KDoc ---------

D_BRANCH_OLD = "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n"

D_BRANCH_NEW = '''                "Tools.Files.move" -> {
                    // args[2] would be `environment`; deliberately not read, for the same
                    // reason as the rest of this family - one host, one namespace, nothing to
                    // route on. Note this package does NOT advertise a cross-environment move
                    // the way copy_file advertises a cross-environment copy
                    // (extended_file_tools.js:25-31), so nothing here promises what the host
                    // cannot do; the gap is only that the argument is ignored.
                    val a = args ?: JSONArray()
                    host.fileMove(
                        a.optString(0),
                        a.optString(1),
                    ).toString()
                }
''' + D_BRANCH_OLD

D_SET_OLD = '''            "Tools.Files.copy",
        )'''

D_SET_NEW = '''            "Tools.Files.copy",
            "Tools.Files.move",
        )'''

D_KDOC_OLD = '''         * Files.writeBinary, Files.read, Files.list, Files.info and Files.copy. The
         * Files family convention is: file operations that touch the real filesystem
'''

D_KDOC_NEW = '''         * Files.writeBinary, Files.read, Files.list, Files.info, Files.copy and
         * Files.move. The Files family convention is: file operations that touch
         * the real filesystem
'''

# --- KelivoWorkspaceHost.kt: implementation ---------------------------------

W_ANCHOR_OLD = '''    private fun File.canonicalOrAbsolute(): String =
        runCatching { canonicalPath }.getOrDefault(absolutePath)
'''

W_IMPL = W_ANCHOR_OLD + '''
    override fun fileMove(source: String, destination: String): JSONObject {
        val src = File(source)
        val dst = File(destination)
        // Same zero-validation stance as every other Files method here: both paths are the
        // caller's absolute paths, and there is no workspace root to check them against.
        if (!src.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $source")
        }
        // Internal guard, not part of the KDoc: no caller can see this, and without it the
        // fallback is a suicide path. copyFileTo(src, src) opens the source for write, so the
        // source is truncated before a byte of it is read, and the deleteTree that follows
        // removes the only copy. A rename onto the same path is a no-op, so returning {}
        // without touching the disk is the whole job.
        if (src.canonicalOrAbsolute() == dst.canonicalOrAbsolute()) {
            return JSONObject()
        }
        // Both shapes are refused by rename(2) and by the copy helpers alike, so refusing them
        // here costs nothing and buys the honesty of the message below: past this point,
        // "copy incomplete" means something may have been written.
        if (src.isDirectory && dst.exists() && !dst.isDirectory) {
            throw IOException("EISDIR: destination is a file, not a directory: ${dst.path}")
        }
        if (!src.isDirectory && dst.isDirectory) {
            throw IOException("EISDIR: destination is a directory: ${dst.path}")
        }
        if (src.renameTo(dst)) {
            return JSONObject()
        }
        // renameTo answers true or false and nothing else: java.io.File discards the errno, so
        // why it failed is not knowable here. Two ordinary causes are a filesystem boundary
        // (/sdcard is FUSE, /data is ext4) and a non-empty destination directory (ENOTEMPTY),
        // and there is no third signal to route on - nor would a narrower trigger help, since
        // the merge that the second cause needs can only happen on this route anyway. Every
        // failure therefore takes one route, copy then delete, which is not atomic: between
        // the halves both copies exist. The halves fail differently, so they report
        // differently.
        val dstWasDirectory = dst.exists() && dst.isDirectory
        try {
            if (src.isDirectory) copyTree(src, dst) else copyFileTo(src, dst)
        } catch (t: Throwable) {
            // Remove what the copy wrote. A destination that was already a directory is left
            // alone instead: it can hold entries the source never carried, and deleting those
            // would be a worse outcome than the one being reported. Everything else - a
            // destination we created, or a file that was already truncated when the write
            // began - is removed rather than left behind looking complete.
            val removed = !dstWasDirectory && deleteIfPresent(dst)
            throw IOException(
                "EIO: rename-path failed, copy incomplete (" +
                    (if (removed) "destination removed" else "destination not removed") +
                    "): ${t.message}",
                t,
            )
        }
        try {
            deleteTree(src)
        } catch (t: Throwable) {
            // The destination is complete and is deliberately NOT rolled back: by this point
            // the source may already be partially removed, so deleting the destination would
            // destroy the only complete copy left. The message names that side.
            throw IOException(
                "EIO: rename-path failed, source removal incomplete " +
                    "(source may be partially removed, destination is complete): ${t.message}",
                t,
            )
        }
        // {} : the file is at the destination and the source is gone.
        return JSONObject()
    }

    /** Removes [target] if it is there, and answers whether anything was removed. */
    private fun deleteIfPresent(target: File): Boolean {
        if (!target.exists()) return false
        return runCatching {
            deleteTree(target)
            true
        }.getOrDefault(false)
    }
'''

EDITS = [
    (HOST, H_OLD, "    fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject\n\n"
     + H_KDOC, "fileMove declaration"),
    (WSHOST, W_ANCHOR_OLD, W_IMPL, "fileMove implementation"),
    (DISPATCH, D_BRANCH_OLD, D_BRANCH_NEW, "move branch"),
    (DISPATCH, D_SET_OLD, D_SET_NEW, "throwingMethods member"),
    (DISPATCH, D_KDOC_OLD, D_KDOC_NEW, "throwingMethods KDoc sentence"),
]

TOUCHED = {DISPATCH, HOST, WSHOST}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def main() -> None:
    staged = {p: p.read_text(encoding="utf-8") for p in TOUCHED}

    # Pass 1: every anchor unique in its own file, before anything touches disk.
    for path, old, new, label in EDITS:
        n = staged[path].count(old)
        if n != 1:
            raise SystemExit(f"{path.name}: {label}: expected 1 anchor, found {n}")
        staged[path] = staged[path].replace(old, new)

    # Pass 2: write.
    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")

    # Pass 3: self-check.
    d = DISPATCH.read_text(encoding="utf-8")
    h = HOST.read_text(encoding="utf-8")
    w = WSHOST.read_text(encoding="utf-8")

    w0 = git("show", f"HEAD:{WSHOST.relative_to(ROOT)}")

    def delta(needle: str) -> int:
        return w.count(needle) - w0.count(needle)

    # "insert only": no line may disappear except the five anchor lines, and no file
    # outside the three may move at all.
    diff = git("diff", "--", ".", *[str(p.relative_to(ROOT)) for p in TOUCHED])
    removed = [ln[1:] for ln in diff.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    anchor_lines = {ln for _p, old, _n, _l in EDITS for ln in old.splitlines()}
    stray_removals = [ln for ln in removed if ln.strip() and ln not in anchor_lines]
    changed_files = set(git("diff", "--name-only").split())

    checks = [
        # dispatcher
        ("dispatcher: two occurrences of Tools.Files.move (branch + set)", d.count('"Tools.Files.move"'), 2),
        ("dispatcher: host.fileMove call", d.count("host.fileMove("), 1),
        ("dispatcher: does not read args[2] (the environment)", d.count("optString(2)"), 0),
        ("dispatcher: throwingMethods has eight members", d.count('\n            "Tools.Files.'), 8),
        ("dispatcher KDoc names all eight", d.count("Files.copy and"), 1),
        ("dispatcher KDoc line 2 reflowed", d.count("Files.writeBinary, Files.read, Files.list, Files.info, Files.copy and"), 1),
        ("dispatcher KDoc keeps the convention sentence intact", d.count("convention is: file operations that touch"), 1),
        ("dispatcher KDoc has no orphan word line", len([1 for ln in d.splitlines() if ln.strip() == "* Files.move."]), 0),
        # host (interface)
        ("host: fileMove declared", h.count("fun fileMove(source: String, destination: String): JSONObject"), 1),
        ("host: declares fileMove exactly once", h.count("fun fileMove"), 1),
        ("host: the payload is {} ", h.count("On success returns **an empty object**, {} , and that {} means exactly one thing:"), 1),
        ("host: the sentence the round is built on", h.count("the file is at the destination and the source is gone"), 1),
        ("host: and its second half", h.count('It never means "we'), 1),
        ("host: names daily_life:1050 as the reader it must satisfy", h.count("截图已保存到: <path>"), 1),
        ("host: across devices is the ordinary case", h.count("Across devices is the ordinary case here, not the corner."), 1),
        ("host: fallback declared non-atomic", h.count("That fallback is **not atomic**"), 1),
        ("host: cross-environment not implemented", h.count("cross-environment moves are not implemented"), 1),
        ("host: merge documented", h.count("merges into it rather than clearing it"), 1),
        ("host: parent-mkdirs asymmetry documented", h.count("parentFile?.mkdirs()"), 1),
        ("host: fileCopy declaration still exactly one", h.count("fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject"), 1),
        ("host: the no-trailing-newline quirk preserved", 1 if h.endswith("}") else 0, 1),
        # host (implementation)
        ("wshost: fileMove overridden", w.count("override fun fileMove(source: String, destination: String): JSONObject"), 1),
        ("wshost: renameTo tried once", w.count("src.renameTo(dst)"), 1),
        ("wshost: rename success returns early", w.count("if (src.renameTo(dst)) {"), 1),
        ("wshost: the same-path guard exists", w.count("src.canonicalOrAbsolute() == dst.canonicalOrAbsolute()"), 2),
        ("wshost: copy-incomplete message, removed variant", w.count('"destination removed"'), 1),
        ("wshost: copy-incomplete message, not-removed variant", w.count('"destination not removed"'), 1),
        ("wshost: the shared message prefix", w.count('"EIO: rename-path failed, copy incomplete ("'), 1),
        ("wshost: source-removal message", w.count('"(source may be partially removed, destination is complete): ${t.message}"'), 1),
        ("wshost: copyTree call sites (fileCopy + fileMove)", w.count("copyTree(src, dst)"), 2),
        ("wshost: copyFileTo call sites (fileCopy + fileMove)", w.count("copyFileTo(src, dst)"), 2),
        ("wshost: never dispatches back through fileCopy", w.count("fileCopy("), 1),
        ("wshost: adds exactly two rename-path throws", delta('"EIO: rename-path failed'), 2),
        ("wshost: adds exactly two EISDIR throws", delta('IOException("EISDIR:'), 2),
        ("wshost: adds one helper", delta("private fun deleteIfPresent("), 1),
        ("wshost: adds no new error-code prefix", delta('"EACCES:'), 0),
        ("wshost: adds no ENOTDIR", delta('"ENOTDIR:'), 0),
        ("wshost: adds no EXDEV text", delta("EXDEV"), 0),
        # diff shape
        ("diff: exactly the three files", len(changed_files), 3),
        ("diff: only the five anchors were replaced", len(stray_removals), 0),
    ]
    bad = [(name, got, want) for name, got, want in checks if got != want]
    if bad:
        for name, got, want in bad:
            print(f"FAIL {name}: got {got}, want {want}")
        for ln in stray_removals:
            print(f"     stray removal: {ln}")
        for f in sorted(changed_files):
            print(f"     changed file: {f}")
        raise SystemExit("self-check failed after write")

    for path, _old, _new, label in EDITS:
        print(f"ok   {path.name} ({label})")
    for name, got, want in checks:
        print(f"     {name}: {got}")


if __name__ == "__main__":
    main()