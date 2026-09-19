#!/usr/bin/env python3
"""Add `Tools.Files.deleteFile` - the first method that throws instead of
returning an error object.

Contract, measured from the call sites rather than guessed:

  openai_draw.js:208      deleteFile(tmpPath)                              1 arg
  file_converter.js:211   deleteFile(testDir, true)                        2 args
  github.js:799           deleteFile(params.path, true, params.environment) 3 args
  operit_editor.js:2599   deleteFile(path, true, "android")                3 args
  operit_editor.js:2716   deleteFile(candidatePath, false, "android")      3 args

so `recursive` and `environment` must be optional; no call site reads a return
value (`Promise<void>`); and `openai_draw.js:207-211` wraps the call in
try/catch with an empty handler, i.e. the caller expects a *throw*. The native
layer can deliver one: `quickjs_jni.cpp:621` turns a Kotlin exception from
`onCall` into `JS_ThrowInternalError`.

`environment` is deliberately not read: the current dispatcher serves a single
host and `KelivoHost.fileDelete` takes no environment.

Six anchors, each required to be unique; anything else aborts without writing.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
HOST = KT / "quickjs/KelivoHost.kt"
WSHOST = KT / "workspace/KelivoWorkspaceHost.kt"
DISPATCH = KT / "quickjs/OperitHostDispatcher.kt"

E1_OLD = "    fun fileExists(path: String, environment: String?): JSONObject\n"
E1_NEW = E1_OLD + (
    "\n"
    "    /**\n"
    "     * Deletes [path], throwing when it cannot be done.\n"
    "     *\n"
    "     * Throwing is deliberate and specific to this call: the packages invoke\n"
    "     * `Tools.Files.deleteFile` inside try/catch (`openai_draw.js:207`) and\n"
    "     * treat a failure as an exception, and the native layer turns a Kotlin\n"
    "     * exception into `JS_ThrowInternalError` (`quickjs_jni.cpp:621`).\n"
    "     *\n"
    "     * missing target -> ENOENT; directory with [recursive] = false -> EISDIR;\n"
    "     * a `delete()` that returns false -> EIO.\n"
    "     */\n"
    "    fun fileDelete(path: String, recursive: Boolean)\n"
)

E2_OLD = "import java.io.File\n"
E2_NEW = (
    "import java.io.File\n"
    "import java.io.FileNotFoundException\n"
    "import java.io.IOException\n"
)

E3_OLD = (
    "    override fun fileExists(path: String, environment: String?): JSONObject =\n"
    '        JSONObject().apply { put("exists", File(path).exists()) }\n'
)
E3_NEW = E3_OLD + (
    "\n"
    "    override fun fileDelete(path: String, recursive: Boolean) {\n"
    "        val target = File(path)\n"
    "        // Both checks run before any delete(). File.delete() returns true for an\n"
    "        // empty directory, so deleting first would remove it silently; and it\n"
    "        // returns false for a missing target as well as for a non-empty one.\n"
    "        if (!target.exists()) {\n"
    '            throw FileNotFoundException("ENOENT: no such file or directory: $path")\n'
    "        }\n"
    "        if (target.isDirectory && !recursive) {\n"
    '            throw IOException("EISDIR: is a directory (recursive=false): $path")\n'
    "        }\n"
    "        deleteTree(target)\n"
    "    }\n"
    "\n"
    "    /**\n"
    "     * Depth-first delete. Every delete() is checked, so a partially removed\n"
    "     * tree is never reported as success.\n"
    "     */\n"
    "    private fun deleteTree(target: File) {\n"
    "        if (target.isDirectory) {\n"
    "            val children = target.listFiles()\n"
    '                ?: throw IOException("EIO: cannot list directory: ${target.path}")\n'
    "            for (child in children) {\n"
    "                deleteTree(child)\n"
    "            }\n"
    "        }\n"
    "        if (!target.delete()) {\n"
    '            throw IOException("EIO: failed to delete: ${target.path}")\n'
    "        }\n"
    "    }\n"
)

E4_OLD = r'''                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''
E4_NEW = r'''                "Tools.Files.deleteFile" -> {
                    // args[2] (environment) intentionally not read: the signature has it, but the
                    // current dispatcher serves a single host and KelivoHost.fileDelete() takes no
                    // environment. Reading or validating here would be pretending we route on it.
                    // When a second host (proot/linux) lands, add the routing here — and only
                    // after the full enum is recovered from the native/proot side, not from the
                    // descriptive android/linux text in package METADATA.
                    host.fileDelete(
                        args?.optString(0).orEmpty(),
                        args?.optBoolean(1) ?: false,
                    )
                    null
                }

                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
'''

E5_OLD = r'''            errorJson(method, t)
'''
E5_NEW = r'''            // Declared in THROWING_METHODS; every other method keeps returning an object.
            if (method in THROWING_METHODS) throw t
            errorJson(method, t)
'''

E6_OLD = r'''    private fun notSupported(method: String): String = JSONObject()
'''
E6_NEW = r'''    private companion object {
        /**
         * Methods that surface a failure as a JS throw instead of an error object.
         *
         * Files.deleteFile is the first: the packages call it inside try/catch
         * (openai_draw.js:207) and expect the throw, and the native layer converts a
         * Kotlin exception into `JS_ThrowInternalError` (quickjs_jni.cpp:621).
         */
        val THROWING_METHODS = setOf("Tools.Files.deleteFile")
    }

''' + E6_OLD

EDITS = [
    (HOST, E1_OLD, E1_NEW),
    (WSHOST, E2_OLD, E2_NEW),
    (WSHOST, E3_OLD, E3_NEW),
    (DISPATCH, E4_OLD, E4_NEW),
    (DISPATCH, E5_OLD, E5_NEW),
    (DISPATCH, E6_OLD, E6_NEW),
]


def main() -> None:
    if "fileDelete" in HOST.read_text(encoding="utf-8"):
        print("already applied")
        return
    for path, old, new in EDITS:
        src = path.read_text(encoding="utf-8")
        found = src.count(old)
        if found != 1:
            raise SystemExit(f"{path.name}: anchor not unique, found {found}")
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print("applied: 3 files")


if __name__ == "__main__":
    main()