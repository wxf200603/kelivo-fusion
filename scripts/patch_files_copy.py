#!/usr/bin/env python3
"""Map Tools.Files.copy onto KelivoHost.fileCopy.

Measured from the four call sites, not guessed:

  extended_file_tools.js:100  copy(source, destination, recursive, source_env, dest_env)  -> !!result + pass-through
  operit_editor.js:2858        copy(src, dst, false, "android", "android")                -> discarded
  operit_editor.js:2947        copy(src, dst, false, "android", "android")                -> discarded
  operit_editor.js:3069        copy(src, dst, false, "android", "android")                -> discarded

All four pass five arguments; there is no arity split here (the split the previous
survey suspected does not exist - only move has one). What actually varies is which
values may be null.

Sub-decisions, each taken deliberately:

  * the return payload is {} . Nothing reads a field: three sites discard the
    result and the fourth only tests `!!result`, which pins down "a non-null
    object" and nothing else. Same stance as fileInfo: no reader, no field.
  * failure throws. All four call sites are inside try/catch, `!!result` is true
    for an {error} object, and the discarded sites are worse still - a silent
    failure at 2947/3069 would surface as operit_editor's own "file is missing
    after copy" check, i.e. the real cause lost.
  * the two environments are not read, and cross-environment copy is NOT
    implemented. This is the first time in this family that a package promises the
    model something the host does not do: extended_file_tools.js:40-41 declares
    both environments and the package description advertises cross-environment
    copy. Documented as a gap, not silently accepted.
  * a directory source with recursive = false is EISDIR, worded exactly like
    fileDelete's existing EISDIR (recursive=false) - the family's own precedent.
  * an existing destination is overwritten: a file is replaced (non-atomically,
    like fileWrite/fileWriteBinary), a directory is merged into rather than
    cleared. Driven by the two install sites, which delete the target themselves
    first and log "replacing target file before copy" - replacement is the intent.
  * a copy onto the same path is a no-op returning {}: it is the one silently
    destructive outcome available (truncate before read), and the callers already
    treat that case as "nothing to do" (operit_editor.js:2943, 3066).
  * streaming, unlike fileRead/fileReadBinary: a copy has no reason to materialise
    the payload in memory.

Private helpers copyTree/copyFileTo are introduced here rather than inline in
fileCopy because the move round needs the same walk for its cross-device fallback.

Anchors: seven, each required unique inside its own file. Anything else aborts
before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check, which includes error-code
arithmetic as a delta against the pristine file read from `git show HEAD:` - this
commit must add exactly one ENOENT throw, three EISDIR throws and two EIO throws,
and nothing else.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration -------------------------------

H_OLD = "    fun fileInfo(path: String): JSONObject\n}"

H_KDOC = '''    /**
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
}'''

# --- OperitHostDispatcher.kt: branch + throwingMethods + its KDoc -----------

D_BRANCH_OLD = "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n"

D_BRANCH_NEW = '''                "Tools.Files.copy" -> {
                    // args[2] is `recursive`; args[3] and args[4] would be `source_environment`
                    // and `dest_environment`. Neither environment is read: this host serves one
                    // namespace, and extended_file_tools.js:40-41 is exactly where the package
                    // promises the model a cross-environment copy that does not exist. Reading
                    // them here would be pretending we route on them.
                    // `recursive` is the first default in this family that optBoolean gets right
                    // by accident: the package declares it false (extended_file_tools.js:39) and
                    // org.json turns a JSON null into false. Files.zip will NOT have that luck -
                    // its declared default is true - so its branch has to test isNull instead of
                    // copying this line.
                    val a = args ?: JSONArray()
                    host.fileCopy(
                        a.optString(0),
                        a.optString(1),
                        a.optBoolean(2),
                    ).toString()
                }
''' + D_BRANCH_OLD

D_SET_OLD = '''            "Tools.Files.info",
        )'''

D_SET_NEW = '''            "Tools.Files.info",
            "Tools.Files.copy",
        )'''

D_KDOC_OLD = '''         * Files.writeBinary, Files.read, Files.list and Files.info. The Files family
         * convention is: file operations that touch the real filesystem
'''

D_KDOC_NEW = '''         * Files.writeBinary, Files.read, Files.list, Files.info and Files.copy. The
         * Files family convention is: file operations that touch the real filesystem
'''

# --- KelivoWorkspaceHost.kt: imports + implementation + helpers -------------

W_IMP_FILE_OLD = "import java.io.File\n"
W_IMP_FILE_NEW = "import java.io.File\nimport java.io.FileInputStream\n"

W_IMP_FNF_OLD = "import java.io.FileNotFoundException\n"
W_IMP_FNF_NEW = "import java.io.FileNotFoundException\nimport java.io.FileOutputStream\n"

W_IMPL_OLD = '        return JSONObject().put("fileType", if (target.isDirectory) "directory" else "file")\n    }\n'

W_IMPL_NEW = W_IMPL_OLD + '''
    override fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject {
        val src = File(source)
        val dst = File(destination)
        // Same zero-validation stance as every other Files method here: both paths are the
        // caller's absolute paths, and there is no workspace root to check them against.
        if (!src.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $source")
        }
        // A copy onto itself would truncate the source before reading a byte of it. The
        // callers already read this case as "nothing to do" (operit_editor.js:2943, 3066
        // skip the copy and log exactly that), so it returns the empty success payload
        // rather than an invented error code.
        if (src.canonicalOrAbsolute() == dst.canonicalOrAbsolute()) {
            return JSONObject()
        }
        if (src.isDirectory) {
            // The same code and the same wording fileDelete already uses for this shape.
            if (!recursive) {
                throw IOException("EISDIR: is a directory (recursive=false): $source")
            }
            copyTree(src, dst)
        } else {
            copyFileTo(src, dst)
        }
        // {} : no call site reads a field here, and three of the four discard the object.
        return JSONObject()
    }

    /**
     * Depth-first copy. Streaming, so a large file is never materialised the way the
     * [fileRead] / [fileReadBinary] payloads are.
     *
     * Private rather than inline because the move round needs the same walk for its
     * cross-device fallback.
     */
    private fun copyTree(source: File, destination: File) {
        if (source.isDirectory) {
            if (destination.exists() && !destination.isDirectory) {
                throw IOException("EISDIR: destination is a file, not a directory: ${destination.path}")
            }
            // Merge rather than replace: an existing directory keeps whatever the source
            // does not carry. Documented in fileCopy; no call site exercises it.
            if (!destination.isDirectory && !destination.mkdirs()) {
                throw IOException("EIO: cannot create directory: ${destination.path}")
            }
            val children = source.listFiles()
                ?: throw IOException("EIO: cannot list directory: ${source.path}")
            for (child in children) {
                copyTree(child, File(destination, child.name))
            }
            return
        }
        copyFileTo(source, destination)
    }

    private fun copyFileTo(source: File, destination: File) {
        // Checked before the stream is opened, so this never depends on what the platform
        // says when asked to write a directory. An unchecked FileOutputStream here would
        // report it as a FileNotFoundException, i.e. as a missing file - the wrong class.
        if (destination.isDirectory) {
            throw IOException("EISDIR: destination is a directory: ${destination.path}")
        }
        destination.parentFile?.mkdirs()
        FileInputStream(source).use { input ->
            FileOutputStream(destination).use { output -> input.copyTo(output) }
        }
    }

    private fun File.canonicalOrAbsolute(): String =
        runCatching { canonicalPath }.getOrDefault(absolutePath)
'''

EDITS = [
    (WSHOST, W_IMP_FILE_OLD, W_IMP_FILE_NEW, "FileInputStream import"),
    (WSHOST, W_IMP_FNF_OLD, W_IMP_FNF_NEW, "FileOutputStream import"),
    (WSHOST, W_IMPL_OLD, W_IMPL_NEW, "fileCopy implementation + helpers"),
    (HOST, H_OLD, "    fun fileInfo(path: String): JSONObject\n\n" + H_KDOC, "fileCopy declaration"),
    (DISPATCH, D_BRANCH_OLD, D_BRANCH_NEW, "copy branch"),
    (DISPATCH, D_SET_OLD, D_SET_NEW, "throwingMethods member"),
    (DISPATCH, D_KDOC_OLD, D_KDOC_NEW, "throwingMethods KDoc sentence"),
]


def main() -> None:
    staged = {}
    for path in (DISPATCH, HOST, WSHOST):
        staged[path] = path.read_text(encoding="utf-8")

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

    w0 = subprocess.run(
        ["git", "show", f"HEAD:{WSHOST.relative_to(ROOT)}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout

    def delta(needle: str) -> int:
        return w.count(needle) - w0.count(needle)

    checks = [
        ("dispatcher: two occurrences of Tools.Files.copy (branch + set)", d.count('"Tools.Files.copy"'), 2),
        ("dispatcher: host.fileCopy call", d.count("host.fileCopy("), 1),
        ("dispatcher: reading neither environment", d.count("optString(3)") + d.count("optString(4)"), 0),
        ("dispatcher: recursive via optBoolean(2) only", d.count("a.optBoolean(2)"), 1),
        ("dispatcher: throwingMethods has seven members", d.count('\n            "Tools.Files.'), 7),
        ("dispatcher KDoc names all seven", d.count("Files.info and Files.copy"), 1),
        ("dispatcher KDoc reflowed: 'convention is:' stays on one line", d.count("convention is: file operations that touch the real filesystem"), 1),
        ("dispatcher KDoc has no orphan word line", len(re.findall(r"^\s*\*\s*convention\s*$", d, re.M)), 0),
        ("host: fileCopy declared once", h.count("fun fileCopy(source: String, destination: String, recursive: Boolean): JSONObject"), 1),
        ("host: declares fileCopy exactly once", h.count("fun fileCopy"), 1),
        ("host: the empty-object contract is stated", h.count("an empty object"), 1),
        ("host: the cross-environment gap is stated", h.count("cross-environment copy is not"), 1),
        ("host: destination is not a folder to copy into", h.count("not** a directory to drop the source into"), 1),
        ("host: same-path no-op is stated", h.count("no-op returning {}"), 1),
        ("wshost: fileCopy overridden", w.count("override fun fileCopy("), 1),
        ("wshost: copyTree defined, called and recursed", w.count("copyTree("), 3),
        ("wshost: copyFileTo defined and called twice", w.count("copyFileTo("), 3),
        ("wshost: streams through FileInputStream", w.count("FileInputStream(source).use"), 1),
        ("wshost: FileInputStream imported", w.count("import java.io.FileInputStream"), 1),
        ("wshost: FileOutputStream imported", w.count("import java.io.FileOutputStream"), 1),
        ("wshost: adds exactly one ENOENT throw", delta('FileNotFoundException("ENOENT:'), 1),
        ("wshost: adds exactly three EISDIR throws", delta('IOException("EISDIR:'), 3),
        ("wshost: adds exactly two EIO throws", delta('IOException("EIO:'), 2),
        ("wshost: adds no new error-code prefix", delta('"EACCES:'), 0),
    ]
    bad = [(name, got, want) for name, got, want in checks if got != want]
    if bad:
        for name, got, want in bad:
            print(f"FAIL {name}: got {got}, want {want}")
        raise SystemExit("self-check failed after write")

    for path in (DISPATCH, HOST, WSHOST):
        print(f"ok   {path.name}")
    for name, got, want in checks:
        print(f"     {name}: {got}")


if __name__ == "__main__":
    main()