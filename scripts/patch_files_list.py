#!/usr/bin/env python3
"""Map Tools.Files.list onto KelivoHost.fileList.

The contract is measured from the two call sites, not guessed:

  operit_editor.js:2700  list(dir, "android")  -> listing.entries, entry.name, entry.isDirectory
  operit_editor.js:2838  list(dir, "android")  -> the same three

No data was written yet, so `fileList` is genuinely new: no dispatcher branch, no
interface member, no implementation.

Sub-decisions, each taken deliberately:

  * an entry carries exactly {name, isDirectory} - the two fields any call site
    reads (2702-2703 and 2840-2846). No size / mtime / path: a field nothing reads
    is a contract with no reader.
  * an empty directory is a SUCCESS: {"entries": []}. Both call sites write
    `listing?.entries ?? []`, so "no entries" and "null" and "empty array" are
    indistinguishable there - which is exactly why a failure must THROW instead of
    returning an object: `?? []` would turn a refused readdir into a silently
    empty directory and the two callers would report success having done nothing.
  * the order is File.listFiles() order, not sorted. Neither call site depends on
    an order, so sorting would be inventing a contract.
  * failure classes: ENOENT (missing), ENOTDIR (present, not a directory - new to
    this family), EIO (listFiles() returned null after both checks). EACCES cannot
    be separated from EIO here, because File.listFiles() collapses a permission
    failure into the same null; that is documented rather than guessed at.
  * no environment parameter: both call sites pass the literal "android", and the
    dispatcher serves a single host. Nothing to route on, so nothing is read.
  * args[0] is not polymorphic here (unlike Files.read): both call sites pass a
    bare path string, so no object shape is accepted - accepting one would be
    inventing an interface.

`throwingMethods` gains its fifth member. Its KDoc sentence is updated to name
Files.list ONLY: Files.info lands in its own commit, and a set description that
names a member which is not in the set yet would be a lie.

Anchors: six, each required unique inside its own file. Anything else aborts
before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check (member counts, the
interface declaration and the override both present, the ENOTDIR prefix present
exactly once in each of the two files that must carry it and absent from the
dispatcher, JSONArray imported).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"

# --- KelivoHost.kt: the interface declaration -------------------------------

H_OLD = "    fun fileRead(path: String): JSONObject\n}"

H_KDOC = '''    /**
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
}'''

# --- OperitHostDispatcher.kt: branch + throwingMethods + its KDoc -----------

D_BRANCH_OLD = "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n"

D_BRANCH_NEW = '''                "Tools.Files.list" -> {
                    // args[1] would be `environment`; deliberately not read, for the same
                    // reason as deleteFile / readBinary / writeBinary / read: the dispatcher
                    // serves a single host and KelivoHost.fileList() takes no environment.
                    // Unlike read, args[0] is not polymorphic here - both call sites pass a
                    // bare path string (operit_editor.js:2700, 2838) - so no object shape is
                    // accepted; accepting one would be inventing an interface.
                    host.fileList(args?.optString(0).orEmpty()).toString()
                }
''' + D_BRANCH_OLD

D_SET_OLD = '''            "Tools.Files.read",
        )'''

D_SET_NEW = '''            "Tools.Files.read",
            "Tools.Files.list",
        )'''

D_KDOC_OLD = '''         * This started with Files.deleteFile and now includes Files.readBinary,
         * Files.writeBinary and Files.read. The
         * Files family convention is: file operations that touch the real filesystem
'''

D_KDOC_NEW = '''         * This started with Files.deleteFile and now includes Files.readBinary,
         * Files.writeBinary, Files.read and Files.list. The Files family convention
         * is: file operations that touch the real filesystem
'''

# --- KelivoWorkspaceHost.kt: import + implementation ------------------------

W_IMP_OLD = "import org.json.JSONObject\n"

W_IMP_NEW = "import org.json.JSONArray\nimport org.json.JSONObject\n"

W_IMPL_OLD = '        return JSONObject().put("content", text)\n    }\n'

W_IMPL_NEW = W_IMPL_OLD + '''
    override fun fileList(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as every other Files method here: `path` is the
        // caller's absolute path, and there is no workspace root to check it against.
        // Existence is checked before the directory test, so a missing path reads as
        // ENOENT rather than ENOTDIR.
        if (!target.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        // ENOTDIR is new to this file's vocabulary: ENOENT would be a lie about a
        // path that is right there, and EISDIR says the opposite of what is true.
        // Call sites branch on the prefix, so the prefix is spelled out.
        if (!target.isDirectory) {
            throw FileNotFoundException("ENOTDIR: not a directory: $path")
        }
        // Past both checks, a null from listFiles() is the platform refusing the
        // readdir - which is also where an unreadable directory surfaces, because
        // File.listFiles() collapses a permission failure into the same null. That is
        // why this is EIO and not EACCES: the two are not separable here. The wording
        // matches deleteTree's existing EIO (the same readdir refusal, line 927).
        val children = target.listFiles()
            ?: throw IOException("EIO: cannot list directory: $path")
        val entries = JSONArray()
        children.forEach { child ->
            entries.put(
                JSONObject()
                    .put("name", child.name)
                    .put("isDirectory", child.isDirectory),
            )
        }
        return JSONObject().put("entries", entries)
    }
'''

EDITS = [
    (WSHOST, W_IMP_OLD, W_IMP_NEW, "import line"),
    (WSHOST, W_IMPL_OLD, W_IMPL_NEW, "fileList implementation"),
    (HOST, H_OLD, "    fun fileRead(path: String): JSONObject\n\n" + H_KDOC, "fileList declaration"),
    (DISPATCH, D_BRANCH_OLD, D_BRANCH_NEW, "list branch"),
    (DISPATCH, D_SET_OLD, D_SET_NEW, "throwingMethods member"),
    (DISPATCH, D_KDOC_OLD, D_KDOC_NEW, "throwingMethods KDoc sentence"),
]


def main() -> None:
    texts = {}
    for path in (DISPATCH, HOST, WSHOST):
        texts[path] = path.read_text(encoding="utf-8")

    # Pass 1: every anchor unique in its own file, before anything touches disk.
    staged = dict(texts)
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

    checks = [
        ("dispatcher: two occurrences of Tools.Files.list (branch + set)", d.count('"Tools.Files.list"'), 2),
        ("dispatcher: host.fileList call", d.count("host.fileList("), 1),
        # 12-space indent + newline: only the set's members sit at that depth. A
        # bare '"Tools.Files.' would also match the 16-space branches.
        ("dispatcher: throwingMethods has five members", d.count('\n            "Tools.Files.'), 5),
        ("dispatcher: does not name ENOTDIR", d.count("ENOTDIR"), 0),
        ("host: fileList declared", h.count("fun fileList(path: String): JSONObject"), 1),
        ("host: list branch not duplicated in interface", h.count("fun fileList"), 1),
        ("wshost: fileList overridden", w.count("override fun fileList(path: String): JSONObject"), 1),
        ("wshost: JSONArray imported", w.count("import org.json.JSONArray"), 1),
        ("wshost: JSONArray used", w.count("JSONArray()"), 1),
        ("wshost: ENOTDIR prefix once", w.count("ENOTDIR:"), 1),
        ("wshost: EIO: prefix three times (deleteTree x2 pre-existing + fileList x1)", w.count("EIO:"), 3),
        ("host: ENOTDIR documented twice (throw list + the new-code note)", h.count("ENOTDIR"), 2),
        ("host: EIO documented once", h.count("EIO)"), 1),
        ("dispatcher KDoc names Files.list", d.count("Files.read and Files.list"), 1),
        ("dispatcher KDoc does NOT name Files.info yet", d.count("Files.info"), 0),
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