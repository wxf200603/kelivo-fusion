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

                else -> fallback?.invoke(method, argsJson) ?: notSupported(method)
            }
        } catch (t: Throwable) {
            errorJson(method, t)
        }
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