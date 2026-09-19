package com.psyche.kelivo.quickjs

import android.content.Context
import android.util.Log
import androidx.annotation.VisibleForTesting
import com.psyche.kelivo.workspace.KelivoWorkspaceHost
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import org.hjson.JsonValue
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

    /**
     * The live host. Kept so its PTY sessions can be released when the runtime
     * is rebuilt or torn down — a reconfigure must not leave shells running.
     */
    @Volatile private var workspaceHost: KelivoWorkspaceHost? = null
    private val loaded = mutableSetOf<String>()

    /**
     * Packages whose load already failed, with the reason, so a repeat call
     * reports it instead of re-running the eval and degrading to a
     * "tool not found" message.
     */
    private val failedLoads = mutableMapOf<String, String>()

    fun attach() {
        diag("attach()")
        channel.setMethodCallHandler { call, result ->
            diag("call ${call.method}")
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
                "diag" -> {
                    val args = call.arguments as? Map<*, *> ?: emptyMap<Any, Any>()
                    diag("dart: ${args["msg"]}")
                    result.success(null)
                }
                "workspaceCwd" -> result.success(
                    workspaceHost?.globalCwd.orEmpty()
                )
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
        worker.execute {
            runCatching { runtime?.close() }
            runCatching { workspaceHost?.close() }
            workspaceHost = null
            runtime = null
        }
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
        // The previous host owns the PTYs; release them before handing over.
        runCatching { workspaceHost?.close() }
        workspaceHost = null
        loaded.clear()
        failedLoads.clear()
        val host = KelivoWorkspaceHost(context, cfg)
        val (rt, _) = QuickJsHostEnvironment.create(host)
        workspaceHost = host
        rt.installCompatLayerOrThrow()
        installHostBootstrap(rt, cfg)
        config = cfg
        runtime = rt
        diag("configure: usable=${cfg.isUsable} rootfs=${cfg.rootfsDir}")
        runCatching { maybeRunSelfTest() }
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
        val names = packageNames()
        diag("listTools: ${names.size} packages")
        for (name in names) {
            val source = readPackageSource(name)
            if (source == null) {
                diag("listTools: skip $name (asset unreadable)")
                continue
            }
            val meta = parseMetadata(source)
            if (meta == null) {
                // Reported by name: `?: continue` hid six real packages
                // behind a count that only ever looked plausible.
                diag("listTools: skip $name (no METADATA block, or it will not parse as HJSON)")
                continue
            }
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
        diag("listTools: ${out.length()} entries")
        val emitted = (0 until out.length())
            .mapNotNull { out.optJSONObject(it)?.optString("package") }
            .filter { it.isNotEmpty() }
        diag("listTools: emitted=${emitted.joinToString(",")}")
        val payload = out.toString()
        // Written out as well as counted: the Dart loader is diffed against
        // this exact payload, and a count cannot be diffed.
        runCatching {
            File(context.filesDir, "operit_js_listTools.json").writeText(payload)
        }.onFailure { diag("listTools: dump failed: $it") }
        return payload
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


    /**
     * Logging wrapper around [executeTool].
     *
     * The diagnostic log records both the arguments and the outcome of every
     * call, which is what makes an on-device test report verifiable: a call the
     * model claims to have made shows up here with the bytes it actually got
     * back, so a hallucinated result is immediately visible.
     */
    private fun callTool(pkg: String, tool: String, argsJson: String): String {
        diag("callTool $pkg:$tool args=${argsJson.take(300)}")
        val out = executeTool(pkg, tool, argsJson)
        diag("result $pkg:$tool -> ${out.take(400)}")
        return out
    }

    private fun executeTool(pkg: String, tool: String, argsJson: String): String {
        val rt = runtime ?: return err("runtime not configured")
        if (pkg.isBlank() || tool.isBlank()) return err("pkg and tool are required")

        if (!loaded.contains(pkg)) {
            val source = readPackageSource(pkg) ?: return err("package not found: $pkg")
            // A package that threw while it was evaluated leaves module.exports
            // empty, and every later lookup then says "tool not found" - which
            // reads like a missing tool, not a broken package. Load once and
            // remember why it failed.
            failedLoads[pkg]?.let { return err(it) }

            // Only the eval is guarded; a missing source is reported earlier.
            // Two shapes, and checking `success` alone would miss the second:
            //   1. native caught a JS throw -> EvalResult.success == false;
            //   2. the payload is not JSON (empty / truncated) -> parse throws.
            val loadAttempt = runCatching {
                rt.eval(buildString {
                    append("var module = { exports: {} }; var exports = module.exports;\n")
                    append(source)
                    append("\n;globalThis.__pkgs = globalThis.__pkgs || {};")
                    append("globalThis.__pkgs[").append(JSONObject.quote(pkg)).append("] = module.exports; undefined;")
                }, "$pkg.js")
            }
            val loadFailure = loadAttempt.fold(
                onSuccess = { result ->
                    if (result.success) {
                        null
                    } else {
                        listOfNotNull(result.errorMessage, result.errorStack, result.errorDetailsJson)
                            .joinToString(" | ")
                            .ifBlank { "eval returned success=false" }
                    }
                },
                onFailure = { error -> "${error.javaClass.simpleName}: ${error.message}" },
            )
            if (loadFailure != null) {
                val message = "package $pkg failed to load: $loadFailure"
                failedLoads[pkg] = message
                return err(message)
            }
            rt.executePendingJobs()
            loaded.add(pkg)
        }

        val q = { s: String -> s.replace("\\", "\\\\").replace("'", "\\'") }
        rt.eval(buildString {
            append("globalThis.__operit_err = null; globalThis.__operit_out = undefined;")
            append("globalThis.__operit_done = false;")
            append("(function(){")
            append("  var t = ((globalThis.__pkgs['").append(q(pkg)).append("']) || {})['")
                .append(q(tool)).append("'];")
            append("  if (typeof t !== 'function') { globalThis.__operit_err = 'tool not found: ")
                .append(q(tool)).append("'; return; }")
            append("  try {")
            append("    Promise.resolve(t(").append(argsJson.ifBlank { "{}" }).append(")).then(")
            append("      function(v){ if (!globalThis.__operit_done) globalThis.__operit_out = (v === undefined ? null : v); },")
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

    /**
     * Appends one line to `<files>/operit_js_diag.log`.
     *
     * Release builds send nothing useful to logcat — Dart's `print` is not
     * redirected there, and the shared log buffer is monopolised by the host
     * app — so this file is the only reliable way to see how far the bridge
     * actually gets on a real device.
     */
    private fun diag(message: String) {
        runCatching { File(context.filesDir, DIAG_FILE).appendText("$message\n") }
    }

    /**
     * One-shot end-to-end check of the whole tool chain, gated behind a marker
     * file so an ordinary launch never spawns a shell command behind the user's
     * back.
     *
     * The marker's contents are the command line to run; the result goes to the
     * diagnostic log. This exercises every hop the model will use:
     *
     *     super_admin.js -> Tools proxy -> NativeInterface.__call ->
     *     OperitHostDispatcher -> KelivoWorkspaceHost -> proot
     *
     * Delete-the-marker-after-use keeps it strictly one shot.
     */
    private fun maybeRunSelfTest() {
        val marker = File(context.filesDir, SELFTEST_MARKER)
        if (!marker.isFile) return
        val text = runCatching { marker.readText().trim() }.getOrNull().orEmpty()
        marker.delete()

        if (text.startsWith(PTY_PREFIX)) {
            runPtySelfTest()
            return
        }

        // `#call` runs `<pkg>:<tool> {json}` lines through [callTool].
        if (text.startsWith(CALL_PREFIX)) {
            runCallSelfTest(text.removePrefix(CALL_PREFIX))
            return
        }

        // A leading `#shell` selects the Android-side tool (root/Shizuku); anything
        // else runs inside the container as a normal terminal command.
        val useShell = text.startsWith(SHELL_PREFIX)
        val command = (if (useShell) text.removePrefix(SHELL_PREFIX) else text)
            .trim()
            .ifBlank { "echo operit-selftest" }
        val tool = if (useShell) "shell" else "terminal"

        val startedAt = System.currentTimeMillis()
        runCatching {
            callTool("super_admin", tool, JSONObject().put("command", command).toString())
        }.onFailure { diag("selftest $tool threw: ${it.message}") }
        diag("selftest $tool [$command] finished in ${System.currentTimeMillis() - startedAt}ms")
    }

    /** Runs each `<pkg>:<tool> {json}` line in [spec] through [callTool]. */
    private fun runCallSelfTest(spec: String) {
        for (line in spec.lines()) {
            val l = line.trim()
            if (l.isEmpty()) continue
            val i = l.indexOf(' ')
            val target = (if (i < 0) l else l.substring(0, i)).trim()
            val args = (if (i < 0) "{}" else l.substring(i + 1)).trim().ifBlank { "{}" }
            // `host:<method>` skips the package layer and calls
            // `NativeInterface.__call` directly.
            //
            // SELF-TEST ONLY: no tool is registered under this prefix and no
            // package exports it. It exists because the cases this contract is
            // about cannot be produced through the package layer -- every
            // deleteFile call site hardcodes `recursive` (github.js:799,
            // file_converter.js:211) or keeps the path inside a cleanup helper
            // (openai_draw.js:208, operit_editor.js:2599/2716), so EISDIR
            // (directory + recursive=false) and ENOENT for a path the test
            // picks are unreachable from a package. Remove it the day one
            // exposes a delete whose arguments come from the outside.
            //
            // The argument text reaches __call verbatim, so it is the JSON
            // array OperitHostDispatcher.kt:40 parses with `JSONArray(...)`:
            //
            //     #call host:Tools.Files.deleteFile ["/sdcard/t",false]
            //
            // An expected failure arrives here as a `THREW: ...` line: the
            // dispatcher rethrows for this method (THROWING_METHODS).
            if (target.startsWith(HOST_PREFIX)) {
                val method = target.removePrefix(HOST_PREFIX)
                // `continue`, not `return`: one marker file carries several
                // cases, and a return would silently drop the rest.
                val rt = runtime ?: continue
                val eval = rt.eval(
                    "NativeInterface.__call(" +
                        JSONObject.quote(method) + ", " +
                        JSONObject.quote(args) + ")",
                    "hostcall.js",
                )
                val out =
                    if (eval.success) {
                        eval.valueJson.orEmpty()
                    } else {
                        "THREW: ${eval.errorMessage}"
                    }
                diag("hostselftest $method -> $out")
                continue
            }

            val c = target.indexOf(':')
            if (c <= 0 || c == target.length - 1) {
                diag("callselftest: bad target '$target'")
                continue
            }
            val started = System.currentTimeMillis()
            val out = runCatching {
                callTool(target.substring(0, c), target.substring(c + 1), args)
            }.getOrElse { "threw: ${it.message}" }
            diag("callselftest $target -> ${out.take(600)} (${System.currentTimeMillis() - started}ms)")
        }
    }

    /**
     * Exercises the interactive path, one call per step.
     *
     * The steps share a session: if `pwd` after `cd /tmp` still reports `/tmp`,
     * the PTY is genuinely persistent rather than a fresh proot per command.
     * The last step checks that phone storage is mounted.
     */
    private fun runPtySelfTest() {
        val steps = listOf(
            "cd /tmp && pwd",
            "pwd",
            "ls /sdcard | head -3",
        )
        for (step in steps) {
            val startedAt = System.currentTimeMillis()
            val out = runCatching {
                callTool("super_admin", "terminal", JSONObject().put("command", step).toString())
            }.getOrElse { "threw: ${it.message}" }
            diag("pty [$step] -> ${out.take(600)} (${System.currentTimeMillis() - startedAt}ms)")
        }
        val screen = runCatching {
            callTool("super_admin", "terminal_getscreen", "{}")
        }.getOrElse { "threw: ${it.message}" }
        diag("pty screen -> ${screen.take(400)}")
    }

    /**
     * Injects the `Tools.*` namespace tree that Operit's own runtime provides.
     *
     * The ported compat layer only installs the flat `NativeInterface` bridge,
     * so without this every package dies with `'Tools' is not defined`. The
     * proxy below turns `Tools.System.terminal.exec(a, b, c)` into
     * `NativeInterface.__call("Tools.System.terminal.exec", "[a,b,c]")` — the
     * exact shape [OperitHostDispatcher] already handles.
     *
     * `scripts/mock_tools_proxy_test.js` extracts this very string and runs it
     * against the real super_admin.js, so the text below is the tested one.
     */
    private fun installHostBootstrap(
        rt: QuickJsNativeRuntime,
        cfg: KelivoWorkspaceHost.WorkspaceConfig,
    ) {
        val cleanOnExit = File(cfg.tmpDir, "operit-cleanOnExit")
        runCatching { cleanOnExit.mkdirs() }
        val script = HOST_BOOTSTRAP.replace(
            "'__KELIVO_CLEAN_ON_EXIT_DIR__'",
            JSONObject.quote(cleanOnExit.absolutePath),
        )
        // `eval` reports JS errors inside [QuickJsNativeRuntime.EvalResult] rather
        // than throwing, so a plain onSuccess would log "installed" even when the
        // bootstrap script blew up.
        val result = runCatching { rt.eval(script, "operit-bootstrap.js") }
            .getOrElse {
                diag("bootstrap threw: ${it.message}")
                return
            }
        if (result.success) {
            diag("bootstrap installed: Tools=${result.valueJson}")
        } else {
            diag("bootstrap failed: ${result.errorMessage} ${result.errorStack}")
        }
    }

    private val HOST_BOOTSTRAP = """
        (function () {
            var root = globalThis;

            function parseHostResult(text) {
                if (text === null || text === undefined) return null;
                if (typeof text !== 'string') return text;
                var trimmed = text.trim();
                if (trimmed.length === 0) return null;
                var first = trimmed.charAt(0);
                if (first === '{' || first === '[') {
                    try {
                        return JSON.parse(trimmed);
                    } catch (error) {
                        return text;
                    }
                }
                return text;
            }

            function invokeHost(path, args) {
                var bridge = root.NativeInterface;
                if (!bridge || typeof bridge.__call !== 'function') {
                    return Promise.reject(new Error('NativeInterface.__call is unavailable: ' + path));
                }
                return Promise.resolve(bridge.__call(path, JSON.stringify(args))).then(parseHostResult);
            }

            function makeNamespace(path) {
                function leaf() {
                    return invokeHost(path, Array.prototype.slice.call(arguments));
                }
                return new Proxy(leaf, {
                    get: function (target, property) {
                        // Never look like a thenable, so `await Tools.System`
                        // cannot accidentally resolve the namespace itself.
                        if (property === 'then') return undefined;
                        if (typeof property === 'symbol') return target[property];
                        if (property === 'name' || property === 'length') return target[property];
                        if (property === 'call' || property === 'apply' || property === 'bind') {
                            return target[property];
                        }
                        return makeNamespace(path + '.' + String(property));
                    },
                    apply: function (target, thisArg, args) {
                        return invokeHost(path, args);
                    },
                });
            }

            if (typeof root.Tools === 'undefined') {
                root.Tools = makeNamespace('Tools');
            }

            if (typeof root.getChatId !== 'function') {
                // One stable id for every conversation: the merged build wants
                // a single shared container session set, not per-chat ones.
                root.getChatId = function () {
                    return 'kelivo-shared';
                };
            }

            if (typeof root.complete !== 'function') {
                // Operit hands a package's result back through `complete`, not
                // through the function's return value. Record it and let it win
                // over the `undefined` a completing tool returns.
                root.complete = function (value) {
                    root.__operit_done = true;
                    root.__operit_out = (value === undefined ? null : value);
                };
            }

            if (typeof root.OPERIT_CLEAN_ON_EXIT_DIR === 'undefined') {
                root.OPERIT_CLEAN_ON_EXIT_DIR = '__KELIVO_CLEAN_ON_EXIT_DIR__';
            }
        })();
    """.trimIndent()

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

    // Extracts the METADATA object at the top of a package. The block is HJSON, not
    // JSON -- `name: code_runner` without quotes is valid there -- so it goes through
    // org.hjson rather than org.json alone. Extraction and parse are the upstream's
    // (PackageManager.kt:2467 and :2258); the return type is not, because callers
    // here report "no block" separately from an empty one. See METADATA_PATTERN.
    @VisibleForTesting
    internal fun parseMetadata(source: String): JSONObject? {
        val match = METADATA_PATTERN.find(source) ?: return null
        val block = match.groupValues[1].trim()
        if (block.isEmpty()) return null
        return runCatching { JSONObject(JsonValue.readHjson(block).toString()) }.getOrNull()
    }

    private companion object {
        const val TAG = "OperitJs"
        const val CHANNEL_NAME = "app.operit_js"
        const val ASSET_DIR = "operit_packages"
        const val DIAG_FILE = "operit_js_diag.log"

        /**
         * The upstream's METADATA expression, character for character:
         * `PackageManager.kt:2467`. Raw string on purpose -- the backslashes are
         * the regular expression's, not escapes.
         */
        val METADATA_PATTERN = """/\*\s*METADATA\s*([\s\S]*?)\*/""".toRegex()

        /**
         * Presence of this file triggers the one-shot end-to-end self test in
         * [maybeRunSelfTest]. Its contents are the command line to run; prefix
         * them with `#shell` to test the Android-side tool instead of the
         * container.
         */
        const val SELFTEST_MARKER = "operit_selftest.txt"

        /** Marker prefix that switches [maybeRunSelfTest] to `super_admin:shell`. */
        const val SHELL_PREFIX = "#shell"

        /** Marker prefix that runs the multi-step interactive (PTY) self test. */
        const val PTY_PREFIX = "#pty"

        /** Marker prefix that calls `pkg:tool {json}` lines directly. */
        const val CALL_PREFIX = "#call"

        /**
         * Marker prefix that drives `NativeInterface.__call` with no package in
         * between. SELF-TEST ONLY -- see [runCallSelfTest].
         */
        const val HOST_PREFIX = "host:"
        const val MAX_DRAIN_ROUNDS = 64
    }
}