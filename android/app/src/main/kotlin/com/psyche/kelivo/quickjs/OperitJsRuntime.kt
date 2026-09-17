package com.psyche.kelivo.quickjs

import android.content.Context
import android.util.Log
import com.psyche.kelivo.workspace.KelivoWorkspaceHost
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * Runs Operit's JS tool packages on the ported QuickJS engine, exposing them to
 * Dart over MethodChannel `app.operit_js`.
 *
 * Packages are CommonJS-ish, so [callTool] wraps the source with a synthetic
 * `module`/`exports` pair before evaluating it. Tool functions are `async`, so
 * the result is collected in three steps: kick off the call, drain QuickJS
 * microtasks with `executePendingJobs()`, then read the result global.
 */
class OperitJsRuntime(
    private val context: Context,
    messenger: BinaryMessenger,
) {
    private val channel = MethodChannel(messenger, CHANNEL_NAME)
    private val worker = Executors.newSingleThreadExecutor { r -> Thread(r, "operit-js") }

    @Volatile private var runtime: QuickJsNativeRuntime? = null
    @Volatile private var config: KelivoWorkspaceHost.WorkspaceConfig? = null
    private val loaded = mutableSetOf<String>()

    fun attach() {
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "configure" -> {
                    val args = call.arguments as? Map<*, *> ?: emptyMap<Any, Any>()
                    worker.execute { result.success(runCatching { configure(args) }.getOrElse(::failure)) }
                }
                "listTools" -> worker.execute {
                    result.success(runCatching { listTools() }.getOrElse(::failure))
                }
                "callTool" -> {
                    val args = call.arguments as? Map<*, *> ?: emptyMap<Any, Any>()
                    worker.execute {
                        result.success(
                            runCatching {
                                callTool(
                                    pkg = args["pkg"] as? String ?: "",
                                    tool = args["tool"] as? String ?: "",
                                    argsJson = args["argsJson"] as? String ?: "{}",
                                )
                            }.getOrElse(::failure)
                        )
                    }
                }
                "status" -> result.success(
                    JSONObject()
                        .put("configured", runtime != null)
                        .put("packagesLoaded", loaded.size)
                        .put("usable", config?.isUsable == true)
                        .toString()
                )
                else -> result.notImplemented()
            }
        }
    }

    fun dispose() {
        channel.setMethodCallHandler(null)
        worker.execute { runCatching { runtime?.close() }; runtime = null }
        worker.shutdown()
    }

    private fun configure(args: Map<*, *>): String {
        val nativeLibDir =
            File(args["nativeLibDir"] as? String ?: context.applicationInfo.nativeLibraryDir)
        val cfg = KelivoWorkspaceHost.WorkspaceConfig(
            nativeLibDir = nativeLibDir,
            rootfsDir = File(args["rootfsDir"] as? String ?: ""),
            tmpDir = File(args["tmpDir"] as? String ?: ""),
            defaultCwd = args["cwd"] as? String ?: "/root",
        )
        runCatching { runtime?.close() }
        loaded.clear()
        val (rt, _) = QuickJsHostEnvironment.create(KelivoWorkspaceHost(context, cfg))
        rt.installCompatLayerOrThrow()
        config = cfg
        runtime = rt
        Log.i(
            TAG,
            "configure: usable=${cfg.isUsable} rootfs=${cfg.rootfsDir} " +
                "tmp=${cfg.tmpDir} nativeLib=${cfg.nativeLibDir}",
        )
        return JSONObject().put("ok", true).put("usable", cfg.isUsable).toString()
    }

    /**
     * One entry per package, each carrying full OpenAI-style function schemas
     * built from the package METADATA (name / description / parameters).
     *
     * Tool names are exposed as `<package>:<tool>` to match Operit exactly, so
     * prompts and examples written for Operit keep working.
     */
    private fun listTools(): String {
        val out = JSONArray()
        for (name in packageNames()) {
            val meta = readPackageSource(name)?.let(::parseMetadata) ?: continue
            val tools = JSONArray()
            meta.optJSONArray("tools")?.let { arr ->
                for (i in 0 until arr.length()) {
                    val entry = arr.optJSONObject(i) ?: continue
                    val toolName = entry.optString("name")
                    if (toolName.isEmpty()) continue
                    tools.put(buildToolSchema(name, toolName, entry))
                }
            }
            out.put(JSONObject().put("package", name).put("tools", tools))
        }
        return out.toString()
    }

    private fun buildToolSchema(pkg: String, tool: String, entry: JSONObject): JSONObject {
        val props = JSONObject()
        val required = JSONArray()
        entry.optJSONArray("parameters")?.let { arr ->
            for (i in 0 until arr.length()) {
                val p = arr.optJSONObject(i) ?: continue
                val pName = p.optString("name")
                if (pName.isEmpty()) continue
                props.put(
                    pName,
                    JSONObject()
                        .put("type", p.optString("type", "string"))
                        .put("description", localized(p.opt("description"))),
                )
                if (p.optBoolean("required", false)) required.put(pName)
            }
        }
        return JSONObject()
            .put("name", "$pkg:$tool")
            .put("description", localized(entry.opt("description")))
            .put(
                "parameters",
                JSONObject()
                    .put("type", "object")
                    .put("properties", props)
                    .put("required", required),
            )
    }

    /** METADATA descriptions are either a plain string or `{zh, en}`. */
    private fun localized(value: Any?): String = when (value) {
        is String -> value
        is JSONObject -> value.optString("zh").ifEmpty { value.optString("en") }
        else -> ""
    }


    private fun callTool(pkg: String, tool: String, argsJson: String): String {
        val rt = runtime ?: return err("runtime not configured")
        if (pkg.isBlank() || tool.isBlank()) return err("pkg and tool are required")

        if (!loaded.contains(pkg)) {
            val source = readPackageSource(pkg) ?: return err("package not found: $pkg")
            rt.eval(buildString {
                append("var module = { exports: {} }; var exports = module.exports;\n")
                append(source)
                append("\n;globalThis.__pkgs = globalThis.__pkgs || {};")
                append("globalThis.__pkgs[").append(JSONObject.quote(pkg)).append("] = module.exports; undefined;")
            }, "$pkg.js")
            rt.executePendingJobs()
            loaded.add(pkg)
        }

        val q = { s: String -> s.replace("\\", "\\\\").replace("'", "\\'") }
        rt.eval(buildString {
            append("globalThis.__operit_err = null; globalThis.__operit_out = undefined;")
            append("(function(){")
            append("  var t = ((globalThis.__pkgs['").append(q(pkg)).append("']) || {})['")
                .append(q(tool)).append("'];")
            append("  if (typeof t !== 'function') { globalThis.__operit_err = 'tool not found: ")
                .append(q(tool)).append("'; return; }")
            append("  try {")
            append("    Promise.resolve(t(").append(argsJson.ifBlank { "{}" }).append(")).then(")
            append("      function(v){ globalThis.__operit_out = (v === undefined ? null : v); },")
            append("      function(e){ globalThis.__operit_err = String((e && e.message) || e); });")
            append("  } catch (e) { globalThis.__operit_err = String((e && e.message) || e); }")
            append("})(); undefined;")
        }, "call.js")

        for (round in 0 until MAX_DRAIN_ROUNDS) {
            rt.executePendingJobs()
            val settled = rt.eval(
                "(globalThis.__operit_out !== undefined || globalThis.__operit_err !== null)",
                "probe.js",
            ).valueJson
            if (settled == "true") break
        }
        rt.executePendingJobs()

        val errValue = rt.eval("globalThis.__operit_err", "read-err.js").valueJson
        if (errValue != null && errValue != "null") return err(errValue.trim('"'))
        return rt.eval("globalThis.__operit_out", "read-out.js").valueJson ?: "null"
    }

    private fun failure(t: Throwable): String =
        JSONObject().put("error", t.javaClass.simpleName).put("message", t.message ?: "").toString()

    private fun err(message: String): String =
        JSONObject().put("error", "OperitJsError").put("message", message).toString()

    /**
     * Asset roots to try, in order.
     *
     * `pubspec.yaml` declares `assets/operit_packages/`, and Flutter keeps the
     * declared path verbatim under `flutter_assets/` — so the packaged path
     * carries an extra `assets/` component. The bare form is kept as a fallback
     * so this keeps working if that pubspec entry is ever moved or flattened.
     */
    private val assetRoots = listOf(
        "flutter_assets/assets/$ASSET_DIR",
        "flutter_assets/$ASSET_DIR",
    )

    private fun packageNames(): List<String> {
        for (root in assetRoots) {
            val names = runCatching { context.assets.list(root)?.toList().orEmpty() }
                .getOrElse { emptyList<String>() }
                .filter { it.endsWith(".js") }
                .map { it.removeSuffix(".js") }
                .sorted()
            if (names.isNotEmpty()) {
                Log.i(TAG, "loaded ${names.size} JS packages from $root")
                return names
            }
        }
        Log.w(TAG, "no JS packages found; tried ${assetRoots.joinToString()}")
        return emptyList()
    }

    private fun readPackageSource(name: String): String? {
        for (root in assetRoots) {
            val source = runCatching {
                context.assets.open("$root/$name.js")
                    .bufferedReader().use { it.readText() }
            }.getOrNull()
            if (source != null) return source
        }
        Log.w(TAG, "package source not found: $name.js")
        return null
    }

    // Extracts the JSON object from the leading METADATA block (see parseMetadata).
    private fun parseMetadata(source: String): JSONObject? {
        val marker = source.indexOf("METADATA")
        if (marker < 0) return null
        val open = source.indexOf('{', marker)
        if (open < 0) return null
        var depth = 0
        var i = open
        while (i < source.length) {
            when (source[i]) {
                '"' -> i = skipString(source, i)
                '{' -> depth++
                '}' -> {
                    depth--
                    if (depth == 0) {
                        return runCatching { JSONObject(source.substring(open, i + 1)) }.getOrNull()
                    }
                }
            }
            i++
        }
        return null
    }

    private fun skipString(s: String, start: Int): Int {
        var i = start + 1
        while (i < s.length) {
            when (s[i]) {
                '\\' -> i++
                '"' -> return i
            }
            i++
        }
        return s.length - 1
    }

    private companion object {
        const val TAG = "OperitJs"
        const val CHANNEL_NAME = "app.operit_js"
        const val ASSET_DIR = "operit_packages"
        const val MAX_DRAIN_ROUNDS = 64
    }
}