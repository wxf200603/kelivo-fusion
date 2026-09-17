package com.psyche.kelivo.workspace

import android.content.Context
import com.psyche.kelivo.quickjs.KelivoHost
import com.psyche.kelivo.shell.RootShell
import com.psyche.kelivo.shell.ShizukuShell
import com.psyche.kelivo.shell.readCapped
import org.json.JSONObject
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * The [KelivoHost] implementation that actually runs things.
 *
 * Backed by the primitives that already ship in this app:
 *
 * | host call          | backend                                                     |
 * |--------------------|-------------------------------------------------------------|
 * | terminalCreate     | bookkeeping only (sessionId -> guest cwd)                   |
 * | terminalExec       | [ProotCommand] + [ProcessBuilder] (same launch ExecRunner uses) |
 * | terminalScreen     | tail of the session's last output (degraded, see below)     |
 * | terminalInput      | no-op, documented limitation                                |
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
 * ## Known limitations (deliberate, for the first milestone)
 *
 * - `terminalScreen` / `terminalInput` are degraded: a real interactive PTY
 *   needs [PtySession], whose read path is asynchronous. Only `super_admin`'s
 *   `terminal` / `shell` tools depend on exec, and those work.
 * - No `binds` are added beyond what [WorkspaceConfig] supplies.
 */
class KelivoWorkspaceHost(
    @Suppress("unused") private val context: Context,
    private val config: WorkspaceConfig,
) : KelivoHost {

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

    private class Session(val cwd: String) {
        @Volatile var lastOutput: String = ""
        @Volatile var lastExitCode: Int = 0
    }

    private val sessions = ConcurrentHashMap<String, Session>()

    /** Serialises proot runs; PRoot is not safe to run truly concurrently here. */
    private val execLock = Any()

    private data class Outcome(val output: String, val exitCode: Int, val timedOut: Boolean)

    // ---------------------------------------------------------------- terminal

    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        sessions.getOrPut(id) { Session(config.defaultCwd) }
        return id
    }

    override fun terminalExec(sessionId: String, command: String, timeoutMs: Long?): JSONObject {
        val session = sessions.getOrPut(sessionId) { Session(config.defaultCwd) }
        val timeout = (timeoutMs ?: DEFAULT_TIMEOUT_MS).coerceAtLeast(MIN_TIMEOUT_MS)

        if (!config.isUsable) {
            return JSONObject()
                .put("output", "workspace not configured: run the environment setup first")
                .put("exitCode", -1)
                .put("sessionId", sessionId)
                .put("timedOut", false)
        }

        val outcome = synchronized(execLock) { runProot(command, session.cwd, timeout) }
        session.lastOutput = outcome.output
        session.lastExitCode = outcome.exitCode

        return JSONObject()
            .put("output", outcome.output)
            .put("exitCode", outcome.exitCode)
            .put("sessionId", sessionId)
            .put("timedOut", outcome.timedOut)
    }

    /**
     * Degraded: returns the tail of this session's most recent output rather
     * than a live PTY screen. Field names match what `super_admin.js` reads.
     */
    override fun terminalScreen(sessionId: String): JSONObject {
        val session = sessions[sessionId]
        val content = session?.lastOutput.orEmpty()
        return JSONObject()
            .put("sessionId", sessionId)
            .put("rows", SCREEN_ROWS)
            .put("cols", SCREEN_COLS)
            .put("content", content.takeLast(SCREEN_ROWS * SCREEN_COLS))
    }

    /**
     * Degraded: without a PTY there is nothing to write into. Commands should
     * go through `terminalExec` instead. Kept as a no-op so JS never crashes.
     */
    override fun terminalInput(sessionId: String, args: JSONObject) {
        sessions.getOrPut(sessionId) { Session(config.defaultCwd) }
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

    // -------------------------------------------------------------- proot exec

    private fun runProot(command: String, cwd: String, timeoutMs: Long): Outcome {
        config.tmpDir.mkdirs()
        ProotCommand.stageTalloc(config.nativeLibDir, config.tmpDir)

        val launch = ProotCommand.build(
            nativeLibDir = config.nativeLibDir,
            rootfsDir = config.rootfsDir,
            tmpDir = config.tmpDir,
            binds = config.binds,
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
    }
}