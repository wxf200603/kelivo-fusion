package com.psyche.kelivo.workspace

import android.content.Context
import android.os.Environment
import com.psyche.kelivo.quickjs.KelivoHost
import com.psyche.kelivo.shell.RootShell
import com.psyche.kelivo.shell.ShizukuShell
import com.psyche.kelivo.shell.readCapped
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.nio.charset.StandardCharsets
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * The [KelivoHost] implementation that actually runs things.
 *
 * Backed by the primitives that already ship in this app:
 *
 * | host call          | backend                                                     |
 * |--------------------|-------------------------------------------------------------|
 * | terminalCreate     | [PtySessions.open] — a real PTY running a login shell        |
 * | terminalExec       | write + end-marker read-back on that PTY                     |
 * | terminalScreen     | live PTY output tail                                         |
 * | terminalInput      | raw bytes into the PTY (control keys supported)              |
 * | shell              | [RootShell] / [ShizukuShell] (ported from the ops branch)   |
 * | fileMkdir/fileWrite| plain java.io on the host path                              |
 *
 * ## Why ProcessBuilder instead of ExecRunner
 *
 * Operit's JS (`super_admin.js`) expects `terminal.exec` to return
 * `{output, exitCode, timedOut}` **synchronously**, while Kelivo's ExecRunner
 * is asynchronous (results arrive over an EventChannel). Rather than inventing
 * a new event-plumbing layer, this class drives proot directly — it builds the
 * exact same argv ExecRunner would (via [ProotCommand.build]) and blocks on the
 * process, reusing the module's `internal killProcessTree` for timeouts.
 *
 * ## Sessions
 *
 * Every session is a persistent login shell inside the container, so `cd`,
 * exported variables and interactive programs survive between calls. Output
 * arrives asynchronously over [WorkspaceEvents] — that is how [PtySession] is
 * wired — so [terminalExec] correlates a command with its result by appending
 * an end marker that also echoes the exit status.
 *
 * ## Storage
 *
 * Phone storage is bound in as `/sdcard` whenever the app can really read it;
 * see [effectiveBinds] for the fallback used when "All files access" is off.
 */
class KelivoWorkspaceHost(
    private val context: Context,
    private val config: WorkspaceConfig,
) : KelivoHost {

    private class PtyHandle(val id: String, val pid: Int)

    /** Bounded capture of one session's raw PTY bytes. */
    private class PtyBuffer {
        private val out = ByteArrayOutputStream()

        @Synchronized
        fun append(data: ByteArray) {
            out.write(data)
            if (out.size() > MAX_PTY_BUFFER_BYTES) {
                // Drop the oldest half; losing scrollback is cheaper than
                // growing without bound on a chatty command.
                val all = out.toByteArray()
                val keep = all.size / 2
                out.reset()
                out.write(all, all.size - keep, keep)
            }
        }

        @Synchronized
        fun size(): Int = out.size()

        @Synchronized
        fun all(): String = String(out.toByteArray(), StandardCharsets.UTF_8)

        /** Everything written since [offset] (clamped to what we still hold). */
        @Synchronized
        fun from(offset: Int): String {
            val all = out.toByteArray()
            val start = offset.coerceIn(0, all.size)
            return String(all, start, all.size - start, StandardCharsets.UTF_8)
        }
    }

    /** PTY output goes here, not to Dart's event channel (see the constructor). */
    private val ptyEvents = WorkspaceEvents(queueWhenIdle = false)
    private val ptySessions = PtySessions(ptyEvents)
    private val ptyBuffers = ConcurrentHashMap<String, PtyBuffer>()
    private val sessions = ConcurrentHashMap<String, PtyHandle>()
    private val markerSeq = AtomicLong()

    /**
     * Everything needed to launch proot, resolved by the caller.
     *
     * The Dart side owns rootfs selection; it hands the result down once via
     * `app.operit_js/configure`.
     */
    data class WorkspaceConfig(
        val nativeLibDir: File,
        val rootfsDir: File,
        val tmpDir: File,
        val binds: List<BindMount> = emptyList(),
        val defaultCwd: String = "/root",
    ) {
        val isUsable: Boolean
            get() = rootfsDir.isDirectory && File(nativeLibDir, ProotCommand.EXEC_LIB).isFile
    }

    /** Serialises PTY creation; PRoot is not safe to launch concurrently here. */
    private val execLock = Any()

    private data class Outcome(val output: String, val exitCode: Int, val timedOut: Boolean)

    init {
        ptyEvents.addListener { event ->
            if (event["type"] != "pty") return@addListener
            val id = event["sessionId"] as? String ?: return@addListener
            val data = event["data"] as? ByteArray ?: return@addListener
            ptyBuffers[id]?.append(data)
        }
    }

    // ---------------------------------------------------------------- terminal

    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        ensureSession(id)
        return id
    }

    /**
     * Opens the PTY for [id] if it is not running yet.
     *
     * Returns null when the workspace is unusable, so callers can report a
     * readable error instead of throwing into the JS bridge.
     */
    private fun ensureSession(id: String): PtyHandle? {
        sessions[id]?.let { return it }
        if (!config.isUsable) return null
        return synchronized(execLock) {
            sessions[id]?.let { return@synchronized it }
            ptyBuffers[id] = PtyBuffer()

            // `--noediting` is deliberate. With readline active the PTY kept
            // swallowing written commands — they were echoed back but never
            // executed — and every read carried bracketed-paste escapes.
            // Canonical-mode input makes line submission deterministic while
            // still being a persistent, interactive shell.
            val bash = File(config.rootfsDir, "bin/bash")
            val guestShellPath = if (bash.isFile) "/bin/bash" else null
            // bash only accepts long options *before* short ones: `-l --noediting`
            // is rejected with "`--`: invalid option".
            val guestShellArgs =
                if (bash.isFile) listOf("--noediting", "-l") else listOf("-l")

            val pid = try {
                ptySessions.open(
                    sessionId = id,
                    nativeLibDir = config.nativeLibDir,
                    rootfsDir = config.rootfsDir,
                    tmpDir = config.tmpDir,
                    binds = effectiveBinds(),
                    cwd = ProotCommand.validateGuestCwd(config.defaultCwd),
                    // Keep the captured stream to the command's own output: an
                    // interactive prompt would otherwise be prepended to every
                    // result the model sees.
                    env = mapOf("PS1" to "", "PS2" to ""),
                    cols = SCREEN_COLS,
                    rows = SCREEN_ROWS,
                    shell = guestShellPath,
                    shellArgs = guestShellArgs,
                )
            } catch (_: Exception) {
                ptyBuffers.remove(id)
                return@synchronized null
            }
            PtyHandle(id, pid).also { sessions[id] = it }
        }
    }

    /** Closes every PTY this host opened; called when the runtime is rebuilt. */
    fun close() {
        for (id in sessions.keys.toList()) {
            ptySessions.close(id)
        }
        sessions.clear()
        ptyBuffers.clear()
    }

    override fun terminalExec(sessionId: String, command: String, timeoutMs: Long?): JSONObject {
        val timeout = (timeoutMs ?: DEFAULT_TIMEOUT_MS).coerceAtLeast(MIN_TIMEOUT_MS)
        if (!config.isUsable) {
            return unavailable(sessionId, "workspace not configured: run the environment setup first")
        }
        val trimmed = command.trim()
        if (trimmed.isEmpty()) return unavailable(sessionId, "empty command")

        val session = ensureSession(sessionId)
            ?: return runProotResult(trimmed, timeout, sessionId)
        val buffer = ptyBuffers[sessionId]
            ?: return unavailable(sessionId, "session buffer missing")

        // Anything already buffered belongs to an earlier call: only bytes
        // written from here on can be this command's output.
        val startOffset = buffer.size()
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"

        // `2>&1` folds stderr into the stream the model reads, and the trailing
        // echo carries the exit status back out through the PTY. The line ends
        // with CR — the byte a real terminal sends for Enter.
        val payload = "{ $trimmed ; }2>&1; echo $marker:\$?\r"
        if (!send(session, payload)) return unavailable(sessionId, "the PTY rejected the command")

        val deadline = System.currentTimeMillis() + timeout
        while (true) {
            val seen = buffer.from(startOffset)
            val finished = parseMarker(seen, marker)
            if (finished != null) {
                return JSONObject()
                    .put("output", stripEcho(finished.body, payload))
                    .put("exitCode", finished.exitCode)
                    .put("sessionId", sessionId)
                    .put("timedOut", false)
            }
            if (System.currentTimeMillis() >= deadline) {
                // The shell keeps running; the leftover output lands in the next
                // call's start offset, so a later read is not corrupted by it.
                return JSONObject()
                    .put("output", stripEcho(seen, payload))
                    .put("exitCode", -1)
                    .put("sessionId", sessionId)
                    .put("timedOut", true)
            }
            Thread.sleep(POLL_MS)
        }
    }

    /** A finished command: its output, and the status the marker carried. */
    private data class MarkerResult(val body: String, val exitCode: Int)

    /**
     * Finds the line the shell printed for `echo <marker>:$?`.
     *
     * The PTY echoes our payload back, so the marker text also appears *inside*
     * the echoed command line. Only a line that begins with the marker and is
     * followed by a plain integer is the shell's own output — the echo line
     * starts with `{` and ends with the literal `$?`, so it can never match.
     */
    private fun parseMarker(seen: String, marker: String): MarkerResult? {
        var offset = 0
        for (line in seen.split('\n')) {
            val trimmed = line.trimEnd('\r')
            if (trimmed.startsWith(marker)) {
                val status = trimmed.substring(marker.length).removePrefix(":").trim()
                if (STATUS_PATTERN.matches(status)) {
                    return MarkerResult(seen.substring(0, offset), status.toInt())
                }
            }
            offset += line.length + 1
        }
        return null
    }

    /**
     * Drops the line the PTY echoed back for [payload].
     *
     * A PTY echoes whatever is written to it, so the command text is the first
     * thing in the captured bytes. Matching on the exact line we sent keeps
     * this honest: everything the command itself printed is preserved.
     */
    private fun stripEcho(body: String, payload: String): String {
        val firstLine = payload.lineSequence().firstOrNull().orEmpty()
        if (firstLine.isEmpty()) return body.trimEnd()
        val at = body.indexOf(firstLine)
        // Startup noise (terminal init, a prompt redraw) can precede the echo,
        // so the match is allowed to sit a little way in — but no further.
        return if (at in 0..ECHO_SEARCH_LIMIT) {
            body.substring(at + firstLine.length).trimStart('\r', '\n')
        } else {
            body.trimEnd()
        }
    }

    private fun send(session: PtyHandle, text: String): Boolean =
        sendRaw(session, text.toByteArray(StandardCharsets.UTF_8))

    private fun sendRaw(session: PtyHandle, data: ByteArray): Boolean = try {
        ptySessions.write(session.id, data)
        true
    } catch (_: Exception) {
        false
    }

    private fun unavailable(sessionId: String, message: String): JSONObject = JSONObject()
        .put("output", message)
        .put("exitCode", -1)
        .put("sessionId", sessionId)
        .put("timedOut", false)

    /**
     * Live tail of the session's PTY output.
     *
     * Field names match what `super_admin.js` reads. A real screen model would
     * need a terminal emulator; the tail is what an agent actually needs.
     */
    override fun terminalScreen(sessionId: String): JSONObject {
        val content = ptyBuffers[sessionId]?.all().orEmpty()
        return JSONObject()
            .put("sessionId", sessionId)
            .put("rows", SCREEN_ROWS)
            .put("cols", SCREEN_COLS)
            .put("content", content.takeLast(SCREEN_ROWS * SCREEN_COLS))
    }

    /**
     * Writes straight into the session's PTY.
     *
     * `super_admin.js` sends `{input, control}`; `control=ctrl` with
     * `input='c'` means the raw Ctrl-C byte (0x03), and `enter`/`tab`/`esc`
     * map to their own control characters. This is what makes interactive
     * programs (prompts, `nano`, `top`) usable from a tool call.
     */
    override fun terminalInput(sessionId: String, args: JSONObject) {
        val session = ensureSession(sessionId) ?: return
        val text = args.optString("input")
        val control = args.optString("control").lowercase()

        if (control == "ctrl") {
            ctrlCode(text.firstOrNull())?.let { sendRaw(session, byteArrayOf(it)) }
            return
        }

        val payload = buildString {
            append(text)
            when (control) {
                "enter" -> append('\r')
                "tab" -> append('\t')
                "esc" -> append('\u001b')
            }
        }
        sendRaw(session, payload.toByteArray(StandardCharsets.UTF_8))
    }

    /** `A`..`_` map onto 0x01..0x1F, which is how a PTY encodes Ctrl chords. */
    private fun ctrlCode(ch: Char?): Byte? {
        val upper = ch?.uppercaseChar() ?: return null
        if (upper.code < 'A'.code || upper.code > '_'.code) return null
        return (upper.code and 0x1F).toByte()
    }

    // ------------------------------------------------------------------- shell

    override fun shell(command: String): JSONObject {
        val result = RootShell.run(command, SHELL_TIMEOUT_MS)
            ?: ShizukuShell.run(command, SHELL_TIMEOUT_MS)
        return if (result != null) {
            JSONObject()
                .put("output", result.output)
                .put("exitCode", result.exitCode)
        } else {
            JSONObject()
                .put("output", "no root or Shizuku channel available")
                .put("exitCode", -1)
        }
    }

    // ------------------------------------------------------------------- files

    override fun fileMkdir(path: String, recursive: Boolean) {
        val dir = File(path)
        if (recursive) dir.mkdirs() else dir.mkdir()
    }

    override fun fileWrite(path: String, content: String, append: Boolean) {
        val file = File(path)
        file.parentFile?.mkdirs()
        if (append && file.isFile) file.appendText(content) else file.writeText(content)
    }

    // ----------------------------------------------------------------- storage

    /**
     * Binds phone storage into the container as `/sdcard`.
     *
     * `/storage/emulated/0` is only reachable when "All files access" is
     * granted (the manifest asks for MANAGE_EXTERNAL_STORAGE); without it
     * Android hands an app nothing outside its own directories, and every read
     * through PRoot would fail with EACCES. The app-specific external dir needs
     * no permission, so it is the fallback: the mount always exists, only its
     * reach varies.
     */
    private fun effectiveBinds(): List<BindMount> {
        val binds = config.binds.toMutableList()
        if (binds.any { it.guest == SHARED_GUEST_PATH }) return binds
        val host = resolveSharedHost() ?: return binds

        // PRoot can only bind onto a path that already exists in the rootfs.
        runCatching {
            val guestDir = File(config.rootfsDir, SHARED_GUEST_PATH.trimStart('/'))
            if (!guestDir.isDirectory) guestDir.mkdirs()
        }
        binds += BindMount(host.absolutePath, SHARED_GUEST_PATH)
        return binds
    }

    private fun resolveSharedHost(): File? {
        val external = runCatching { Environment.getExternalStorageDirectory() }.getOrNull()
        if (external != null && canList(external)) return external

        val appDir = runCatching { context.getExternalFilesDir(null) }.getOrNull() ?: return null
        if (appDir.isDirectory || appDir.mkdirs()) return appDir
        return null
    }

    private fun canList(dir: File): Boolean =
        runCatching { dir.isDirectory && dir.list() != null }.getOrDefault(false)

    /**
     * One-shot proot run, used only when the PTY cannot be opened.
     *
     * Keeping this path means a PTY failure degrades to the previous
     * behaviour instead of taking the terminal tool away entirely.
     */
    private fun runProotResult(command: String, timeout: Long, sessionId: String): JSONObject {
        val outcome = synchronized(execLock) { runProot(command, config.defaultCwd, timeout) }
        return JSONObject()
            .put("output", outcome.output)
            .put("exitCode", outcome.exitCode)
            .put("sessionId", sessionId)
            .put("timedOut", outcome.timedOut)
    }

    // -------------------------------------------------------------- proot exec

    private fun runProot(command: String, cwd: String, timeoutMs: Long): Outcome {
        config.tmpDir.mkdirs()
        ProotCommand.stageTalloc(config.nativeLibDir, config.tmpDir)

        val launch = ProotCommand.build(
            nativeLibDir = config.nativeLibDir,
            rootfsDir = config.rootfsDir,
            tmpDir = config.tmpDir,
            binds = effectiveBinds(),
            cwd = ProotCommand.validateGuestCwd(cwd),
            command = command,
            env = emptyMap(),
        )

        val builder = ProcessBuilder(launch.argv)
            .directory(launch.workingDirectory)
            // Merge stderr into stdout: Operit's terminal tool reports a single
            // combined "output" field, exactly like ExecRunner's UI feed.
            .redirectErrorStream(true)
        builder.environment().putAll(launch.processEnv)

        val process = builder.start()
        try {
            process.outputStream.close()
        } catch (_: Exception) {
            // Nothing to send; the command is fully specified in argv.
        }

        val buffer = StringBuilder()
        val reader = Thread {
            buffer.append(readCapped(process.inputStream).text)
        }.apply { isDaemon = true; start() }

        val finished = try {
            process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }

        val timedOut = !finished
        if (timedOut) killProcessTree(process)
        reader.join(READER_JOIN_MS)

        val exitCode = if (timedOut) {
            -1
        } else {
            try {
                process.exitValue()
            } catch (_: IllegalThreadStateException) {
                killProcessTree(process)
                -1
            }
        }

        return Outcome(buffer.toString(), exitCode, timedOut)
    }

    private companion object {
        const val DEFAULT_TIMEOUT_MS = 15_000L
        const val MIN_TIMEOUT_MS = 1_000L
        const val SHELL_TIMEOUT_MS = 20_000L
        const val READER_JOIN_MS = 1_500L
        const val SCREEN_ROWS = 24
        const val SCREEN_COLS = 80

        /** How often `terminalExec` re-reads the PTY buffer while waiting. */
        const val POLL_MS = 25L

        /** Cap on captured PTY bytes per session; the oldest half is dropped. */
        const val MAX_PTY_BUFFER_BYTES = 512 * 1024

        /** Where phone storage is mounted inside the container. */
        const val SHARED_GUEST_PATH = "/sdcard"

        /** A marker's status suffix: a plain integer, e.g. `0` or `-1`. */
        val STATUS_PATTERN = Regex("-?\\d+")

        /**
         * How far into a capture the echoed command may start and still be
         * treated as the PTY echo (terminal init output can precede it).
         */
        const val ECHO_SEARCH_LIMIT = 256
    }
}