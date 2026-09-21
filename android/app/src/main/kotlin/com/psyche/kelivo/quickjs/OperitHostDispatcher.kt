package com.psyche.kelivo.quickjs

import org.json.JSONArray
import org.json.JSONObject

/**
 * Maps Operit's JS host API (`NativeInterface.__call(method, argsJson)`) onto
 * Kelivo capabilities.
 *
 * ## Why this works without touching the JS packages
 *
 * Operit's compat layer installs a `Proxy` around `NativeInterface`, so a JS
 * call like `Tools.System.terminal.exec(id, cmd, 5000)` arrives here as the
 * plain string pair:
 *
 * ```
 * method   = "Tools.System.terminal.exec"
 * argsJson = "[\"sess-1\",\"ls -la\",5000]"
 * ```
 *
 * So supporting an Operit tool package requires **no changes to the .js file**
 * — only a branch in the `when` below.
 *
 * ## Coverage
 *
 * The 7 branches implemented here are exactly the ones `super_admin.js` uses,
 * as captured by `scripts/mock_host_test.js`. Other packages need more
 * branches (see `docs/merge/02-Host-API映射表.md` for the full 140-method map).
 *
 * Unmapped methods fall through to [fallback] (which handles `console.*` and
 * `scheduleTimer`/`cancelTimer`) and finally to a readable `NotSupported`
 * error, so the AI gets a useful message instead of a crash.
 */
class OperitHostDispatcher(
    private val host: KelivoHost,
    private val fallback: ((method: String, argsJson: String?) -> String?)? = null,
) {

    fun call(method: String, argsJson: String?): String? {
        val args: JSONArray? = argsJson?.takeIf { it.isNotBlank() }?.let { JSONArray(it) }
        return try {
            when (method) {
                "Tools.System.terminal.create" -> {
                    val name = args?.optString(0).orEmpty()
                    JSONObject()
                        .put("sessionId", host.terminalCreate(name))
                        .toString()
                }

                "Tools.System.terminal.exec" -> {
                    val a = args ?: JSONArray()
                    val sessionId = a.optString(0)
                    val command = a.optString(1)
                    val timeout = if (a.length() > 2 && !a.isNull(2)) {
                        a.optLong(2).takeIf { it > 0 }
                    } else {
                        null
                    }
                    host.terminalExec(sessionId, command, timeout).toString()
                }

                "Tools.System.terminal.screen" ->
                    host.terminalScreen(args?.optString(0).orEmpty()).toString()

                "Tools.System.terminal.input" -> {
                    // super_admin.js ignores the return value here.
                    host.terminalInput(
                        args?.optString(0).orEmpty(),
                        args?.optJSONObject(1) ?: JSONObject(),
                    )
                    null
                }

                // Note: terminal_wait needs no dedicated branch — it is
                // implemented in JS on top of terminal.exec with a marker echo.
                "Tools.System.shell" ->
                    host.shell(args?.optString(0).orEmpty()).toString()

                "Tools.Files.mkdir" -> {
                    host.fileMkdir(args?.optString(0).orEmpty(), args?.optBoolean(1) ?: false)
                    null
                }

                "Tools.Files.write" -> {
                    host.fileWrite(
                        args?.optString(0).orEmpty(),
                        args?.optString(1).orEmpty(),
                        args?.optBoolean(2) ?: false,
                    )
                    null
                }

                "Tools.Files.exists" -> {
                    host.fileExists(
                        args?.optString(0).orEmpty(),
                        args?.optString(1)?.takeIf { it.isNotBlank() },
                    ).toString()
                }

                "Tools.Files.deleteFile" -> {
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

                "Tools.Files.readBinary" -> {
                    // args[1] would be `environment`; it is deliberately not read, for the same
                    // reason as deleteFile above: the dispatcher serves a single host and
                    // KelivoHost.fileReadBinary() takes no environment. Reading it here would be
                    // pretending we route on it. No workspace root and no path binding either -
                    // the path reaches File(path) exactly as it does for every other Files method.
                    host.fileReadBinary(args?.optString(0).orEmpty()).toString()
                }
                "Tools.Files.writeBinary" -> {
                    // args[2] would be `environment`; it is deliberately not read, for the same
                    // reason as deleteFile and readBinary above: the dispatcher serves a single
                    // host and KelivoHost.fileWriteBinary() takes no environment. No workspace
                    // root and no path binding either - the path reaches File(path) exactly as
                    // it does for every other Files method.
                    host.fileWriteBinary(
                        args?.optString(0).orEmpty(),
                        args?.optString(1).orEmpty(),
                    ).toString()
                }
                "Tools.Files.read" -> {
                    // args[0] has two shapes: two of the three call sites pass a bare string
                    // (code_runner.js:827, file_converter.js:191) and one passes an object
                    // (operit_editor.js:2614). The object carries exactly {path, environment};
                    // only `.path` is consumed here, and `.environment` is not read - the same
                    // discipline as every other environment in this family. The object form is
                    // an outlier even in its own file: the other twelve Files calls in
                    // operit_editor.js pass environment as a positional string.
                    val a0 = args?.opt(0)
                    val path = when (a0) {
                        is String -> a0
                        is JSONObject -> a0.optString("path")
                        else -> ""
                    }
                    host.fileRead(path).toString()
                }
                "Tools.Files.list" -> {
                    // args[1] would be `environment`; deliberately not read, for the same
                    // reason as deleteFile / readBinary / writeBinary / read: the dispatcher
                    // serves a single host and KelivoHost.fileList() takes no environment.
                    // Unlike read, args[0] is not polymorphic here - both call sites pass a
                    // bare path string (operit_editor.js:2700, 2838) - so no object shape is
                    // accepted; accepting one would be inventing an interface.
                    host.fileList(args?.optString(0).orEmpty()).toString()
                }
                "Tools.Files.info" -> {
                    // args[1] would be `environment`; deliberately not read, for the same
                    // reason as the rest of this family - the dispatcher serves a single
                    // host and KelivoHost.fileInfo() takes no environment. The second call
                    // site is what makes that concrete rather than ceremonial:
                    // extended_file_tools.js:104 passes `params.environment`, a variable its
                    // own schema marks optional, so it can be undefined. There is no enum
                    // here to route on even in principle.
                    host.fileInfo(args?.optString(0).orEmpty()).toString()
                }
                "Tools.Files.copy" -> {
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
                "Tools.Files.move" -> {
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
                "Tools.Files.unzip" -> {
                    // args[2] would be `environment`; deliberately not read, as in the rest of
                    // this family -- one host, one namespace, nothing to route on.
                    //
                    // Note the shape: unzip_files(source, destination, environment)
                    // (extended_file_tools.js:112) has NO boolean, so unlike Files.zip there is
                    // no index to get wrong here. The zip round learned that lesson the hard
                    // way -- a marker that leaves the environment slot out moves every later
                    // argument one index left, and the host then reads the default instead of
                    // the caller's value.
                    val a = args ?: JSONArray()
                    host.fileUnzip(
                        a.optString(0),
                        a.optString(1),
                    ).toString()
                }
                "Tools.Files.zip" -> {
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
                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
            }
        } catch (t: Throwable) {
            // Declared in throwingMethods; every other method keeps returning an object.
            if (method in throwingMethods) throw t
            errorJson(method, t)
        }
    }

    private companion object {
        /**
         * Methods that surface a failure as a JS throw instead of an error object.
         *
         * This started with Files.deleteFile and has grown with each Files method.
         * `throwingMethods` below is the list, and the only place the membership is
         * written down. The Files family convention is: file
         * operations that touch the real filesystem
         * throw on failure, because (a) callers wrap them in try/catch and expect the
         * throw, and (b) returning an error object degrades the failure into a
         * meaningless placeholder at the call site (contentBase64 empty / undefined.length).
         *
         * Exceptions will be individual methods whose callers genuinely want an error
         * object to inspect — not the default.
         */
        private val throwingMethods = setOf(
            "Tools.Files.deleteFile",
            "Tools.Files.readBinary",
            "Tools.Files.writeBinary",
            "Tools.Files.read",
            "Tools.Files.list",
            "Tools.Files.info",
            "Tools.Files.copy",
            "Tools.Files.move",
            "Tools.Files.zip",
            "Tools.Files.unzip",
        )
    }

    private fun notSupported(method: String): String = JSONObject()
        .put("error", "NotSupported")
        .put("method", method)
        .put("hint", "This Operit host API is not mapped to a Kelivo capability yet.")
        .toString()

    private fun errorJson(method: String, t: Throwable): String = JSONObject()
        .put("error", t.javaClass.simpleName)
        .put("message", t.message ?: "")
        .put("method", method)
        .toString()
}