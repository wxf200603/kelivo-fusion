#!/usr/bin/env python3
"""Map Tools.Files.zip onto KelivoHost.fileZip.

Measured, not assumed:

  extended_file_tools.js:53-62   zip_files(source, destination, environment,
                                 include_root_directory) -- the flag's description
                                 says "keep the source directory name as the
                                 top-level folder, **default true**", and it is
                                 scoped to directories ("when zipping a
                                 directory").
  extended_file_tools.js:107-109 the only reader: `!!result`. No field is read.
  operit_editor.js:2879          the only real call site:
                                 `await Tools.Files.zip(stageDir, archivePath,
                                 "android", false)` -- a bare await, result
                                 discarded, environment a string literal, the flag
                                 hardcoded false, and the caller verifies the
                                 archive's existence itself afterwards (:2880).
  operit_editor.js:2870,2873-77  why the caller stages first, and what the root of
                                 the archive must therefore contain
  operit_editor.js:2810-2819     the consumer: unzip, then look for the manifest at
                                 the extraction root

Design decisions, each with its reason:

  * include_root_directory=false means entry names are relative to the source
    directory. That is not a guess: the caller stages a filtered copy so its
    CONTENTS become the archive (:2870), asserts the manifest is at the root of
    that staging directory before zipping (:2873-2877), and the consumer looks for
    the manifest at the extraction root (:2810-2819). Absolute entry names would
    break the ToolPkg install path outright.
  * the flag's declared default is true, so the dispatcher must use
    `isNull(3)` rather than `optBoolean(3)`: org.json turns a missing or null
    argument into false, which would silently invert the documented default. That
    is the one boolean in this family where the two differ, and both patches before
    this one left a note predicting it.
  * an archive written inside its own source is refused up front with
    IllegalArgumentException. ZipOutputStream reads the source while it writes the
    archive, so the packed bytes change while they are packed and the outcome
    depends on filesystem timing. IllegalArgumentException is the family's
    existing stance for malformed input (fileWriteBinary leaves bad base64 as
    exactly this, untranslated).
  * the tree is walked *before* the archive is opened, so an unlistable source
    fails without leaving a half-written archive.
  * a file source ignores the flag: the schema scopes it to directories, and the
    entry is the file's own name.
  * the promise is the smallest one the consumers can rely on: standard ZIP,
    deflate, relative entry names, directory entries ending in "/", entry order not
    promised. Level, zip64, timestamps and external attributes are explicitly NOT
    promised, because two of the three consumers (the platform installer, and
    whatever unzips it on a desktop) are not readable from here.

Anchors: seven, each required unique inside its own file. Anything else aborts
before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check, which also refuses a diff
that removes any line other than the anchors and a diff touching a file outside the
three.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoWorkspaceHost.kt: imports ----------------------------------------

W_IMP_OLD = "import java.io.ByteArrayOutputStream\n"

W_IMP_NEW = "import java.io.BufferedOutputStream\nimport java.io.ByteArrayOutputStream\n"

W_IMP2_OLD = "import java.util.concurrent.atomic.AtomicLong\n"

W_IMP2_NEW = ("import java.util.concurrent.atomic.AtomicLong\n"
              "import java.util.zip.ZipEntry\n"
              "import java.util.zip.ZipOutputStream\n")

# --- KelivoHost.kt: the interface declaration -------------------------------
# This file ends without a trailing newline. The anchor and the replacement both
# end on the closing brace so that quirk is preserved rather than "fixed".

H_OLD = ("    fun fileMove(source: String, destination: String): JSONObject\n"
         "}")

H_KDOC = '''    /**
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
     * an unlistable source or an archive that cannot be written -> EIO. A destination
     * equal to the source is **not** guarded -- no caller produces that shape, and the
     * guard above is the one the round asked for.
     */
    fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject
}'''

# --- OperitHostDispatcher.kt: branch + throwingMethods member + KDoc ---------

D_BRANCH_OLD = "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n"

D_BRANCH_NEW = '''                "Tools.Files.zip" -> {
                    // args[2] would be `environment`; deliberately not read, as in the rest of
                    // this family -- one host, one namespace, nothing to route on.
                    //
                    // args[3] is `include_root_directory`, and this is the ONE boolean in the
                    // family whose declared default is true (extended_file_tools.js:59), so it
                    // cannot be read with optBoolean: org.json answers false for a missing or
                    // null argument and would silently invert the documented behaviour.
                    // isNull(3) is true both for a null and for an index that is not there at
                    // all, which is what the wrapper sends when the caller omits the parameter
                    // (`params.include_root_directory` is then undefined and drops out of the
                    // array) -- so one test covers both shapes.
                    val a = args ?: JSONArray()
                    host.fileZip(
                        a.optString(0),
                        a.optString(1),
                        a.isNull(3) || a.optBoolean(3),
                    ).toString()
                }
''' + D_BRANCH_OLD

D_SET_OLD = '''            "Tools.Files.move",
        )'''

D_SET_NEW = '''            "Tools.Files.move",
            "Tools.Files.zip",
        )'''

D_KDOC_OLD = '''         * Files.writeBinary, Files.read, Files.list, Files.info, Files.copy and
         * Files.move. The Files family convention is: file operations that touch
         * the real filesystem
'''

D_KDOC_NEW = '''         * Files.writeBinary, Files.read, Files.list, Files.info, Files.copy,
         * Files.move and Files.zip. The Files family convention is: file
         * operations that touch the real filesystem
'''

# --- KelivoWorkspaceHost.kt: implementation ---------------------------------

W_ANCHOR_OLD = '''    private fun deleteIfPresent(target: File): Boolean {
        if (!target.exists()) return false
        return runCatching {
            deleteTree(target)
            true
        }.getOrDefault(false)
    }
'''

W_IMPL = W_ANCHOR_OLD + '''
    override fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject {
        val src = File(source)
        val dst = File(destination)
        // Same zero-validation stance as every other Files method here: both paths are the
        // caller's absolute paths, and there is no workspace root to check them against.
        if (!src.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $source")
        }
        // Parameter validation, not a filesystem answer: ZipOutputStream reads the source
        // while it writes the archive, so an archive written inside its own source is
        // self-referential -- the bytes being packed change while they are packed, and the
        // outcome depends on filesystem timing (a truncated archive, one that grows as it is
        // read, or an IO error that looks like "the file ended early"). Refused up front.
        // IllegalArgumentException is the family's stance for malformed input rather than a
        // filesystem refusal: fileWriteBinary leaves a bad base64 payload as exactly this,
        // untranslated, for the caller to name.
        val srcPath = src.canonicalOrAbsolute()
        val dstParentPath = dst.parentFile?.canonicalOrAbsolute().orEmpty()
        if (dstParentPath == srcPath || dstParentPath.startsWith("$srcPath/")) {
            throw IllegalArgumentException(
                "destination is inside source: $destination under $source",
            )
        }
        // The tree is walked before the archive is opened. Two reasons: a source that cannot
        // be listed fails without leaving a half-written archive behind, and this is where the
        // entry names are decided.
        val entries = ArrayList<Pair<String, File>>()
        if (src.isDirectory) {
            // `includeRootDirectory` is the package's own flag, declared default true. With it
            // the entries are prefixed by the source directory's name; without it they are
            // relative to the source, which is what the packer needs -- operit_editor.js:2870
            // stages a filtered copy precisely so that its CONTENTS become the archive,
            // :2873-2877 asserts the manifest is at the root of that staging directory, and
            // the consumer looks for the manifest at the extraction root (:2810-2819). An
            // absolute entry name would break the ToolPkg install path.
            val prefix = if (includeRootDirectory) src.name + "/" else ""
            if (includeRootDirectory) entries.add(prefix to src)
            collectZipEntries(src, prefix, entries)
        } else {
            // A file source has no directory to keep: the schema scopes the flag to "when
            // zipping a directory", so it is ignored and the entry is the file's own name.
            entries.add(src.name to src)
        }
        dst.parentFile?.mkdirs()
        try {
            ZipOutputStream(BufferedOutputStream(FileOutputStream(dst))).use { zip ->
                for ((name, file) in entries) {
                    zip.putNextEntry(ZipEntry(name))
                    // An explicit entry, ending in "/", is how an empty directory survives the
                    // round trip; leaving it out would make it vanish on extraction.
                    if (!file.isDirectory) {
                        FileInputStream(file).use { input -> input.copyTo(zip) }
                    }
                    zip.closeEntry()
                }
            }
        } catch (t: IOException) {
            // The archive is the damaged side on every failure past this point, so the message
            // names it. EIO is the family's code for a filesystem refusal; the wording is
            // specific to this operation rather than reusing the copy round's, which would
            // describe a different one.
            throw IOException("EIO: cannot write archive: ${dst.path}: ${t.message}", t)
        }
        // {} : the only caller discards it (operit_editor.js:2879) and the wrapper only tests
        // `!!result` (extended_file_tools.js:109).
        return JSONObject()
    }

    /**
     * Depth-first collection of [source]'s entries: relative names with `/` separators,
     * directories included (with a trailing `/`) so that empty ones survive.
     *
     * Siblings are sorted by name. The order is not part of what the archive promises, but a
     * stable one makes a round trip readable and a failure reproducible.
     */
    private fun collectZipEntries(source: File, prefix: String, out: MutableList<Pair<String, File>>) {
        val children = source.listFiles()
            ?: throw IOException("EIO: cannot list directory: ${source.path}")
        for (child in children.sortedBy { it.name }) {
            val name = prefix + child.name
            if (child.isDirectory) {
                out.add("$name/" to child)
                collectZipEntries(child, "$name/", out)
            } else {
                out.add(name to child)
            }
        }
    }
'''

EDITS = [
    (WSHOST, W_IMP_OLD, W_IMP_NEW, "BufferedOutputStream import"),
    (WSHOST, W_IMP2_OLD, W_IMP2_NEW, "java.util.zip imports"),
    (HOST, H_OLD, "    fun fileMove(source: String, destination: String): JSONObject\n\n"
     + H_KDOC, "fileZip declaration"),
    (WSHOST, W_ANCHOR_OLD, W_IMPL, "fileZip implementation"),
    (DISPATCH, D_BRANCH_OLD, D_BRANCH_NEW, "zip branch"),
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

    diff = git("diff", "--", ".", *[str(p.relative_to(ROOT)) for p in TOUCHED])
    removed = [ln[1:] for ln in diff.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    anchor_lines = {ln for _p, old, _n, _l in EDITS for ln in old.splitlines()}
    stray_removals = [ln for ln in removed if ln.strip() and ln not in anchor_lines]
    changed_files = set(git("diff", "--name-only").split())

    checks = [
        # dispatcher
        ("dispatcher: two occurrences of Tools.Files.zip (branch + set)", d.count('"Tools.Files.zip"'), 2),
        ("dispatcher: host.fileZip call", d.count("host.fileZip("), 1),
        ("dispatcher: reads the flag with isNull", d.count("a.isNull(3) || a.optBoolean(3)"), 1),
        ("dispatcher: never uses bare optBoolean(3) for it", d.count("a.optBoolean(3)"), 1),
        ("dispatcher: does not read args[2] (the environment)", d.count("optString(2)"), 0),
        ("dispatcher: throwingMethods has nine members", d.count('\n            "Tools.Files.'), 9),
        ("dispatcher KDoc names all nine", d.count("Files.move and Files.zip"), 1),
        ("dispatcher KDoc reflowed, convention sentence intact", d.count("The Files family convention is: file"), 1),
        ("dispatcher KDoc keeps the tail of that sentence", d.count("operations that touch the real filesystem"), 1),
        # host (interface)
        ("host: fileZip declared", h.count("fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject"), 1),
        ("host: declares fileZip exactly once", h.count("fun fileZip"), 1),
        ("host: the payload is {} and the readers are named", h.count("returns **an empty object**, {} . The only real call site discards it"), 1),
        ("host: the promise block names deflate", h.count("entries are deflated"), 1),
        ("host: the not-promised list is there", h.count("compression level, zip64, timestamps and external attributes are **not**"), 1),
        ("host: order is explicitly not promised", h.count("order of entries is not promised"), 1),
        ("host: the flag's declared default is recorded", h.count("whose declared default\n     * is **true**"), 1),
        ("host: false means relative, with the reason", h.count("entry names are relative to [source], so its contents become the"), 1),
        ("host: cites the staging rationale", h.count("operit_editor.js:2870 stages a filtered copy"), 1),
        ("host: cites the consumer's manifest lookup", h.count(":2810-2819"), 1),
        ("host: empty directories documented", h.count("empty subdirectories included"), 1),
        ("host: file source ignores the flag", h.count("A **file** source ignores [includeRootDirectory]"), 1),
        ("host: parent mkdirs stance recorded", h.count("destination's missing parent directories **are** created"), 1),
        ("host: environment not read", h.count("`environment` is not read: extended_file_tools.js:59"), 1),
        ("host: IllegalArgumentException documented", h.count("a destination **inside** the source\n     * -> IllegalArgumentException"), 1),
        ("host: the unguarded equal-path residual is on the record", h.count("A destination\n     * equal to the source is **not** guarded"), 1),
        ("host: fileMove declaration still exactly one", h.count("fun fileMove(source: String, destination: String): JSONObject"), 1),
        ("host: the no-trailing-newline quirk preserved", 1 if h.endswith("}") else 0, 1),
        # host (implementation)
        ("wshost: fileZip overridden", w.count("override fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject"), 1),
        ("wshost: imports BufferedOutputStream", delta("import java.io.BufferedOutputStream"), 1),
        ("wshost: imports both zip classes", delta("import java.util.zip."), 2),
        ("wshost: uses ZipOutputStream and ZipEntry", w.count("ZipOutputStream("), 1),
        ("wshost: writes a ZipEntry per entry", w.count("zip.putNextEntry(ZipEntry(name))"), 1),
        ("wshost: empty directories keep their trailing slash entry", w.count('out.add("$name/" to child)'), 1),
        ("wshost: the walk collects before the archive opens", w.count("val entries = ArrayList<Pair<String, File>>()"), 1),
        ("wshost: sibling sort for a stable order", w.count("children.sortedBy { it.name }"), 1),
        ("wshost: the inside-source guard", w.count("destination is inside source: $destination under $source"), 1),
        ("wshost: adds one IllegalArgumentException (the guard)", delta("throw IllegalArgumentException("), 1),
        ("wshost: destination parents are created", delta("dst.parentFile?.mkdirs()"), 1),
        ("wshost: adds one EIO for the archive", delta('"EIO: cannot write archive:'), 1),
        ("wshost: adds one EIO for an unlistable source", delta('"EIO: cannot list directory:'), 1),
        ("wshost: adds one helper", delta("private fun collectZipEntries("), 1),
        ("wshost: adds no new error-code prefix", delta('"EACCES:'), 0),
        ("wshost: adds no ENOTDIR", delta('"ENOTDIR:'), 0),
        ("wshost: does not touch the move implementation", delta("override fun fileMove("), 0),
        # diff shape
        ("diff: exactly the three files", len(changed_files), 3),
        ("diff: only the seven anchors were replaced", len(stray_removals), 0),
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