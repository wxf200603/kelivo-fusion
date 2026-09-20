#!/usr/bin/env python3
"""Map Tools.Files.info onto KelivoHost.fileInfo.

The contract was measured in the previous round and is not re-derived here:

  operit_editor.js:2588        get_android_file_type -> result.fileType.trim().toLowerCase()
  extended_file_tools.js:104   file_info             -> forwards the whole object, reads nothing

That is the whole reader set. Where the three consumers of get_android_file_type
compare, they compare against exactly two strings:

  2799  sourceType === "directory"
  2802  sourceType === "file"  && manifest.json/hjson
  2805  sourceType === "file"  && *.toolpkg
  2919  sourceType !== "file"  3225  sourceType !== "file"  3244  envType !== "file"

So the value domain is {"file", "directory"}, lower-case, and nothing else.

Sub-decisions, each taken deliberately:

  * the payload is only {"fileType": ...}. The site that reads a field reads one
    field; the site that reads nothing is "does not care yet", not "wants more".
    A sizeBytes/lastModifiedMs/name here would be a contract with no reader.
  * "folder" is never returned. operit_editor.js:2794 has a local variable
    defaulting to "folder", which is exactly the trap: it is never compared
    against fileType, while 2799 is `=== "directory"`. Returning "folder" would
    silently send the toolpkg-packing path down the wrong branch.
  * failure is ENOENT and nothing else. EACCES and EIO are NOT introduced:
    File.isDirectory() on Android reads the parent's directory entry rather than
    the target's own mode, so a permission failure at this point was never
    observed here, and an unobserved error code would be invented, not measured.
  * no environment parameter, same discipline as the family. Note this is the
    round where that costs something to know: the second call site passes
    `params.environment`, a variable its own schema marks optional, so it can be
    undefined - there is no enum to route on even in principle.

`throwingMethods` gains its sixth member, and its KDoc sentence finally names all
six. The list round deliberately left Files.info out of that sentence because the
member did not exist yet; this commit is where the sentence becomes true.

Anchors: five, each required unique inside its own file. Anything else aborts
before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check (member counts, the
interface declaration and the override both present, "fileType" spelled once in
the implementation, EIO: still three times - deleteTree x2 + fileList x1 - so this
commit demonstrably adds no new error code to that file).
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

H_OLD = "    fun fileList(path: String): JSONObject\n}"

H_KDOC = '''    /**
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
}'''

# --- OperitHostDispatcher.kt: branch + throwingMethods + its KDoc -----------

D_BRANCH_OLD = "                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)\n"

D_BRANCH_NEW = '''                "Tools.Files.info" -> {
                    // args[1] would be `environment`; deliberately not read, for the same
                    // reason as the rest of this family - the dispatcher serves a single
                    // host and KelivoHost.fileInfo() takes no environment. The second call
                    // site is what makes that concrete rather than ceremonial:
                    // extended_file_tools.js:104 passes `params.environment`, a variable its
                    // own schema marks optional, so it can be undefined. There is no enum
                    // here to route on even in principle.
                    host.fileInfo(args?.optString(0).orEmpty()).toString()
                }
''' + D_BRANCH_OLD

D_SET_OLD = '''            "Tools.Files.list",
        )'''

D_SET_NEW = '''            "Tools.Files.list",
            "Tools.Files.info",
        )'''

D_KDOC_OLD = '''         * Files.writeBinary, Files.read and Files.list. The Files family convention
         * is: file operations that touch the real filesystem
'''

D_KDOC_NEW = '''         * Files.writeBinary, Files.read, Files.list and Files.info. The Files family
         * convention is: file operations that touch the real filesystem
'''

# --- KelivoWorkspaceHost.kt: implementation ---------------------------------

W_IMPL_OLD = '        return JSONObject().put("entries", entries)\n    }\n'

W_IMPL_NEW = W_IMPL_OLD + '''
    override fun fileInfo(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as every other Files method here: `path` is the
        // caller's absolute path, and there is no workspace root to check it against.
        if (!target.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        // Exactly two classes, on purpose. No EACCES and no EIO: File.isDirectory() on
        // Android resolves the parent's directory entry rather than the target's own
        // mode, so a permission failure at this point was never observed - and an
        // unobserved error code would be invented rather than measured. exists() runs
        // first because isDirectory() is also false for a path that is not there.
        // "directory" is the exact word: operit_editor.js:2799 compares
        // `=== "directory"`, and its own local default of "folder" is never compared
        // against fileType at all - returning "folder" would break that chain silently.
        return JSONObject().put("fileType", if (target.isDirectory) "directory" else "file")
    }
'''

EDITS = [
    (HOST, H_OLD, "    fun fileList(path: String): JSONObject\n\n" + H_KDOC, "fileInfo declaration"),
    (WSHOST, W_IMPL_OLD, W_IMPL_NEW, "fileInfo implementation"),
    (DISPATCH, D_BRANCH_OLD, D_BRANCH_NEW, "info branch"),
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

    # Error-code arithmetic is a DELTA against the pristine file, read from git: the
    # words "EIO:" and "EACCES" also occur in prose, so counting raw occurrences
    # measures comments, not behaviour. What must hold is that this commit adds
    # exactly one ENOENT throw and no new code at all.
    w0 = subprocess.run(
        ["git", "show", f"HEAD:{WSHOST.relative_to(ROOT)}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout

    def delta(needle: str) -> int:
        return w.count(needle) - w0.count(needle)

    checks = [
        ("dispatcher: two occurrences of Tools.Files.info (branch + set)", d.count('"Tools.Files.info"'), 2),
        ("dispatcher: host.fileInfo call", d.count("host.fileInfo("), 1),
        ("dispatcher: throwingMethods has six members", d.count('\n            "Tools.Files.'), 6),
        ("dispatcher KDoc names all six", d.count("Files.list and Files.info"), 1),
        ("dispatcher KDoc reflowed: 'convention is:' stays on one line", d.count("convention is: file operations that touch the real filesystem"), 1),
        ("dispatcher KDoc has no orphan word line", len(re.findall(r"^\s*\*\s*convention\s*$", d, re.M)), 0),
        ("dispatcher: does not name fileType", d.count("fileType"), 0),
        ("host: fileInfo declared", h.count("fun fileInfo(path: String): JSONObject"), 1),
        ("host: declares fileInfo exactly once", h.count("fun fileInfo"), 1),
        ("host: the exact return contract sentence", h.count('Returns only {"fileType": "file" | "directory"}.'), 1),
        ("host: folder warned three times (do-not-return + the trap + the consequence)", h.count('"folder"'), 3),
        ("host: ENOENT is the only failure named", h.count("missing -> ENOENT"), 1),
        ("wshost: fileInfo overridden", w.count("override fun fileInfo(path: String): JSONObject"), 1),
        ("wshost: fileType spelled once", w.count('"fileType"'), 1),
        ("wshost: directory/file pair once", w.count('"directory" else "file"'), 1),
        ("wshost: adds exactly one ENOENT throw", delta('FileNotFoundException("ENOENT:'), 1),
        ("wshost: adds no EIO throw", delta('IOException("EIO:'), 0),
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