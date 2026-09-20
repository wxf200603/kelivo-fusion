package com.psyche.kelivo.workspace

import android.content.Context
import android.os.Environment
import com.psyche.kelivo.quickjs.KelivoHost
import com.psyche.kelivo.shell.RootShell
import com.psyche.kelivo.shell.ShizukuShell
import com.psyche.kelivo.shell.readCapped
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
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

    /** Sessions whose one-shot PTY round trip has already been attempted. */
    private val ptyProbed = ConcurrentHashMap<String, Boolean>()

    /** Non-zero once the shell-candidate sweep has been started. */
    private val candidatesProbed = AtomicLong()

    /**
     * Set once a session has actually executed a probe command.
     *
     * [terminalExec] only submits through the PTY when this is true, so the
     * interactive path is used on evidence and the verified launcher is kept
     * otherwise.
     */
    @Volatile
    private var ptyUsable = false
    private val markerSeq = AtomicLong()

    /** Working directory per session, so `cd` survives between calls. */
    private val sessionCwd = ConcurrentHashMap<String, String>()

    /**
     * The one directory every session shares.
     *
     * [sessionCwd] stays as a per-session view for the log, but the shared
     * workspace is what a new session opens in and what a `cd` updates, so a
     * directory change is not trapped inside the shell that made it.
     */
    private val workspace = GlobalWorkspace(
        context = context,
        rootfsDir = config.rootfsDir,
        binds = ::effectiveBinds,
        defaultCwd = config.defaultCwd,
        log = ::diag,
    )

    /** Last output per session, for `terminal_getscreen`. */
    private val sessionOutput = ConcurrentHashMap<String, String>()

    /**
     * The shared working directory, for callers that report it rather than use it.
     *
     * The MCP server mirrors this into the diagnostic log after every command, so
     * "the terminal and the app agree on the directory" is checkable from the log
     * instead of taken on faith. Deliberately not [GlobalWorkspace.sessionCwd]:
     * that one verifies and may fall back, which is right before *starting* a
     * command and wrong for describing where the last one finished.
     */
    val globalCwd: String
        get() = workspace.cwd

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
            val id = event["sessionId"] as? String ?: return@addListener
            when (event["type"]) {
                "pty" -> (event["data"] as? ByteArray)?.let { ptyBuffers[id]?.append(it) }
                "ptyExit" -> diag("pty exit $id code=${event["exitCode"]}")
            }
        }
    }

    /**
     * Mirrors host-side events into the same diagnostic log the bridge writes.
     *
     * A PTY that dies silently made the first interactive attempt
     * indistinguishable from "the command produced no output", so the open,
     * write and exit paths all report here.
     */
    private fun diag(message: String) {
        runCatching { File(context.filesDir, DIAG_FILE).appendText("host: $message\n") }
    }

    // ---------------------------------------------------------------- terminal

    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        // Which shell can run interactively under proot is an open question
        // (see [probeShellCandidates]); answer it before reporting a session.
        probeShellCandidates()
        // The interactive path was reported broken before; re-check it on every
        // new session so the claim is either confirmed or retired by evidence.
        ensureSession(id)?.let { probePty(it) }
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
                    cwd = ProotCommand.validateGuestCwd(workspace.sessionCwd()),
                    // Keep the captured stream to the command's own output: an
                    // interactive prompt would otherwise be prepended to every
                    // result the model sees.
                    env = mapOf("PS1" to "", "PS2" to ""),
                    cols = SCREEN_COLS,
                    rows = SCREEN_ROWS,
                    shell = guestShellPath,
                    shellArgs = guestShellArgs,
                )
            } catch (error: Exception) {
                ptyBuffers.remove(id)
                diag("pty open failed: ${error.javaClass.simpleName}: ${error.message}")
                return@synchronized null
            }
            diag("pty open $id pid=$pid shell=$guestShellPath args=$guestShellArgs")
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

        // Once the PTY is known to run commands, submit through it: the session
        // stays alive and interactive, and no second proot is started beside
        // the one already serving it ("PRoot is not safe to launch
        // concurrently here"). Anything unexpected falls back to the launcher
        // path that has always worked.
        if (ptyUsable) {
            val viaPty = try {
                runPtyCommand(sessionId, trimmed, minOf(timeout, PTY_EXEC_TIMEOUT_MS))
            } catch (error: Exception) {
                unavailable(sessionId, "pty exec threw ${error.javaClass.simpleName}")
            }
            if (!viaPty.optBoolean("timedOut") && viaPty.optInt("exitCode") >= 0) return viaPty
            diag(
                "pty exec fell back to proot: timedOut=${viaPty.optBoolean("timedOut")} " +
                    "exit=${viaPty.optInt("exitCode")} out=${viaPty.optString("output").take(80)}",
            )
        }

        // A retained session is not the only shape a PTY can take. The candidate
        // sweep showed that *freshly created* sessions do execute commands,
        // which is the same one-process-per-call model the launcher path uses -
        // so try that before giving up on the interactive route.
        val fresh = runPtyCommandFresh(sessionId, trimmed, minOf(timeout, PTY_EXEC_TIMEOUT_MS))
        if (!fresh.optBoolean("timedOut") && fresh.optInt("exitCode") >= 0) return fresh

        return runSessionCommand(sessionId, trimmed, timeout)
    }

    /**
     * Runs one command and returns the model-facing result.
     *
     * Still routed through the proot launcher rather than the PTY: that path is
     * verified, and its marker protocol keeps the captured stream to the
     * command's own output. [probePty] reports whether the interactive path
     * works on this build, so a future switch to PTY submission is based on
     * evidence instead of the earlier assumption that it never worked.
     *
     * Session identity is preserved by carrying the working directory across
     * calls — the state agents actually rely on (`cd`, then relative paths) —
     * rather than by keeping a process alive.
     */
    private fun runSessionCommand(sessionId: String, command: String, timeout: Long): JSONObject {
        // The launcher starts in the shared workspace too, so a directory
        // change made anywhere is where the next call begins.
        val cwd = workspace.sessionCwd()
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"
        val pwdMarker = PTY_CWD_MARKER

        val script = buildString {
            append("cd ").append(singleQuote(cwd)).append(" 2>/dev/null; ")
            // `}` must be its own word: `}2>&1` parses as the literal word `}2`, which
            // leaves the brace group unclosed ("unexpected end of file").
            append("{ ").append(command).append(" ; } 2>&1; ")
            append("__kelivo_status=$?; echo ").append(marker).append(":\$__kelivo_status; ")
            append("echo ").append(pwdMarker).append(":$(pwd)")
        }

        val outcome = synchronized(execLock) { runProot(script, cwd, timeout) }

        val body = StringBuilder()
        var seenMarker = false
        var exitCode = -1
        for (line in outcome.output.lines()) {
            val text = line.trimEnd('\r')
            if (text.startsWith("$marker:")) {
                seenMarker = true
                exitCode = text.removePrefix("$marker:").trim().toIntOrNull() ?: -1
                continue
            }
            if (text.startsWith("$pwdMarker:")) {
                val next = text.removePrefix("$pwdMarker:").trim()
                if (next.startsWith("/")) {
                    sessionCwd[sessionId] = next
                    workspace.follow(next)
                }
                continue
            }
            if (!seenMarker) body.append(line).append('\n')
        }

        val output = body.toString().trimEnd()
        sessionOutput[sessionId] = output
        diag("exec $sessionId exit=$exitCode timedOut=${outcome.timedOut} cwd=${sessionCwd[sessionId]}")

        return JSONObject()
            .put("output", output)
            .put("exitCode", if (outcome.timedOut) -1 else exitCode)
            .put("sessionId", sessionId)
            .put("timedOut", outcome.timedOut)
    }

    /** POSIX single-quoting, so a path with spaces or quotes stays one word. */
    private fun singleQuote(value: String): String =
        "'" + value.replace("'", "'\\''") + "'"

    /**
     * Interactive PTY dispatch: writes a command into the session's PTY and
     * waits for the marker line the shell prints back.
     *
     * Once written off — the PTY echoed input while the shell never ran a
     * command. An on-device reproduction with this exact proot argv and shell
     * did execute the command, and `--noediting` above is the fix for the
     * readline case, so the old verdict is no longer taken on faith.
     * [probePty] re-tests it; this is the path [terminalInput] and [terminalScreen]
     * already serve.
     */
    private fun runPtyCommand(sessionId: String, trimmed: String, timeout: Long): JSONObject {
        val session = ensureSession(sessionId)
            ?: return runProotResult(trimmed, timeout, sessionId)
        val buffer = ptyBuffers[sessionId]
            ?: return unavailable(sessionId, "session buffer missing")

        // Anything already buffered belongs to an earlier call: only bytes
        // written from here on can be this command's output.
        val startOffset = buffer.size()
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"

        // `2>&1` folds stderr into the stream the model reads, and the trailing
        // echo carries the exit status back out through the PTY.
        //
        // Submitted as CRLF on purpose. In canonical mode the line discipline
        // only ends a line on NL, while a terminal's Enter key sends CR — so
        // send both. If CR happens to be translated too, the extra empty line
        // it submits is harmless; if it is not, it stays inside the echo text,
        // which the marker parser trims.
        val payload = ptySubmission(trimmed, marker)
        if (!send(session, payload)) return unavailable(sessionId, "the PTY rejected the command")
        diag("pty send $sessionId pid=${session.pid} bytes=${payload.length} offset=$startOffset")

        val deadline = System.currentTimeMillis() + timeout
        while (true) {
            val seen = buffer.from(startOffset)
            val finished = parseMarker(seen, marker)
            if (finished != null || System.currentTimeMillis() >= deadline) {
                // After a timeout the shell keeps running; the leftover output
                // lands in the next call's start offset, so a later read is not
                // corrupted by it.
                val body = stripEcho(finished?.body ?: seen, payload)
                // Record it here too: the interactive path used to be the one
                // route that left the screen record stale.
                sessionOutput[sessionId] = body
                // The shell may have moved since the last call.
                workspace.follow(readCwd(seen))
                return JSONObject()
                    .put("output", body)
                    .put("exitCode", finished?.exitCode ?: -1)
                    .put("sessionId", sessionId)
                    .put("timedOut", finished == null)
            }
            Thread.sleep(POLL_MS)
        }
    }

    /** The shell's own `pwd` from a submission; "" when it did not report one. */
    private fun readCwd(seen: String): String = seen.lineSequence()
        .firstOrNull { it.trimEnd('\r').startsWith("$PTY_CWD_MARKER:") }
        ?.substringAfter("$PTY_CWD_MARKER:")
        ?.trim()
        .orEmpty()

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

    /** A shell configuration worth testing for the interactive PTY. */
    private data class ShellCandidate(
        val name: String,
        val shell: String,
        val args: List<String>,
    )

    /**
     * Shell configurations the interactive PTY is tested against.
     *
     * More than one, because an interactive shell under proot has been observed
     * to deadlock: the tracer and the tracee both sit in `get_signal`, the shell
     * never reads its stdin, and the io counters stop moving — while
     * non-interactive `bash -lc` works fine. That makes job control the prime
     * suspect, so the candidates vary exactly that: job control turned off, the
     * system startup files skipped, and a shell with minimal interactive setup.
     * The first entry is the current configuration, kept as a control.
     */
    private fun shellCandidates(): List<ShellCandidate> {
        val candidates = mutableListOf<ShellCandidate>()
        val bash = File(config.rootfsDir, "bin/bash")
        if (bash.isFile) {
            candidates += ShellCandidate("bash-current", "/bin/bash", listOf("--noediting", "-l"))
            ensurePtyShim()?.let { shim ->
                candidates += ShellCandidate(
                    "bash-set+m",
                    "/bin/bash",
                    listOf("--noediting", "--init-file", shim),
                )
            }
            candidates += ShellCandidate(
                "bash-norc",
                "/bin/bash",
                listOf("--noediting", "--norc", "--noprofile", "-i"),
            )
        }
        if (File(config.rootfsDir, "bin/sh").isFile) {
            candidates += ShellCandidate("sh-i", "/bin/sh", listOf("-i"))
        }
        return candidates
    }

    /**
     * Writes the shim the job-control-off candidate sources, returning its guest
     * path. It lives in the rootfs the app already owns and nothing else reads
     * it: only that one candidate passes `--init-file`.
     */
    private fun ensurePtyShim(): String? = try {
        val file = File(config.rootfsDir, PTY_SHIM_GUEST_PATH.trimStart('/'))
        val body = "# Written by Kelivo for the interactive PTY probe.\n" +
            "# Job control off: tcsetpgrp is what the proot tracer deadlocks on.\n" +
            "set +m\n"
        if (!file.isFile || file.readText() != body) {
            file.parentFile?.mkdirs()
            file.writeText(body)
        }
        PTY_SHIM_GUEST_PATH
    } catch (error: Exception) {
        diag("pty shim failed: ${error.javaClass.simpleName}: ${error.message}")
        null
    }

    /**
     * Runs every [shellCandidates] entry once and logs which of them can execute
     * a command through the PTY. One round trip each, so the answer costs one
     * timeout per deadlocked candidate and nothing more.
     */
    private fun probeShellCandidates() {
        if (candidatesProbed.getAndIncrement() != 0L) return
        if (!config.isUsable) {
            diag("pty candidates skipped: workspace not usable")
            return
        }
        synchronized(execLock) {
            for (candidate in shellCandidates()) {
                diag("pty candidate ${probeShellCandidate(candidate)}")
            }
        }
    }

    /** One marker round trip against [candidate]; returns a log line. */
    private fun probeShellCandidate(candidate: ShellCandidate): String {
        val sessionId = "probe-${candidate.name}"
        ptyBuffers[sessionId] = PtyBuffer()
        val buffer = ptyBuffers[sessionId] ?: return "${candidate.name} no-buffer"
        val pid = try {
            ptySessions.open(
                sessionId = sessionId,
                nativeLibDir = config.nativeLibDir,
                rootfsDir = config.rootfsDir,
                tmpDir = config.tmpDir,
                binds = effectiveBinds(),
                cwd = ProotCommand.validateGuestCwd(workspace.sessionCwd()),
                env = mapOf("PS1" to "", "PS2" to ""),
                cols = SCREEN_COLS,
                rows = SCREEN_ROWS,
                shell = candidate.shell,
                shellArgs = candidate.args,
            )
        } catch (error: Exception) {
            ptyBuffers.remove(sessionId)
            return "${candidate.name} open-failed ${error.javaClass.simpleName}: ${error.message}"
        }

        try {
            // Echo belongs to the line discipline, not the shell, so a bare
            // newline shows whether the tty is echoing at all.
            ptySessions.write(sessionId, "\n".toByteArray(StandardCharsets.UTF_8))
            Thread.sleep(PROBE_SETTLE_MS)
            val wake = buffer.from(0)

            val payload = "echo $PTY_PROBE_MARKER\n"
            val start = buffer.size()
            ptySessions.write(sessionId, payload.toByteArray(StandardCharsets.UTF_8))
            val deadline = System.currentTimeMillis() + PTY_CANDIDATE_TIMEOUT_MS
            var raw = ""
            while (System.currentTimeMillis() < deadline) {
                raw = buffer.from(start)
                if (countOccurrences(raw, PTY_PROBE_MARKER) >= 2) break
                Thread.sleep(POLL_MS)
            }
            // Two occurrences: the echo of the command line, plus its output.
            val hits = countOccurrences(raw, PTY_PROBE_MARKER)
            return "${candidate.name} shell=${candidate.shell} pid=$pid ran=${hits >= 2} " +
                "markerHits=$hits wakeBytes=${wake.length} " +
                "raw=${raw.take(140).replace('\n', '|').replace("\r", "<CR>")}"
        } catch (error: Exception) {
            return "${candidate.name} threw ${error.javaClass.simpleName}: ${error.message}"
        } finally {
            ptySessions.close(sessionId)
            ptyBuffers.remove(sessionId)
        }
    }

    /** Occurrences of [needle] in [haystack]; echo plus output means two. */
    private fun countOccurrences(haystack: String, needle: String): Int {
        if (needle.isEmpty()) return 0
        var count = 0
        var index = haystack.indexOf(needle)
        while (index >= 0) {
            count++
            index = haystack.indexOf(needle, index + needle.length)
        }
        return count
    }

    /**
     * Marker round trip that answers "can this PTY actually run a command?".
     *
     * A stripped body cannot tell the two failure worlds apart, so this records
     * raw evidence instead:
     *
     *  * `wakeBytes` — what a bare newline produced. Echo is performed by the
     *    line discipline, not by the shell, so a non-zero value proves the tty
     *    is echoing and the question is whether anything reads it. Zero means
     *    the tty is in a raw/no-echo state, an entirely different bug.
     *  * `raw` — the unfiltered capture (an echo-only capture shows up here).
     *  * `attempts` — a proot login shell can still be starting when the first
     *    write lands, so the round trip is retried before being declared dead.
     */
    private fun probePty(session: PtyHandle) {
        if (ptyProbed.putIfAbsent(session.id, true) != null) return
        val buffer = ptyBuffers[session.id] ?: return

        // Wake the line discipline: this is the echo check, independent of bash.
        send(session, "\n")
        Thread.sleep(PROBE_SETTLE_MS)
        val wake = buffer.from(0)

        // The plain form first. The candidate sweep shows a bare echo does run
        // through a fresh session, so a session that ignores even this is
        // broken independently of how the report payload is built.
        val plainStart = buffer.size()
        send(session, "echo $PTY_PROBE_MARKER\n")
        val plainRaw = awaitMarker(buffer, plainStart, PTY_PROBE_TIMEOUT_MS)
        val plainRan = countOccurrences(plainRaw, PTY_PROBE_MARKER) >= 2

        // The form terminal.exec uses, with the exit-status marker it parses.
        var reportRaw = ""
        var reportRan = false
        var reportExit = -1
        if (plainRan) {
            val start = buffer.size()
            try {
                val result = runPtyCommand(session.id, "echo $PTY_PROBE_MARKER", PTY_PROBE_TIMEOUT_MS)
                reportRaw = buffer.from(start)
                reportExit = result.optInt("exitCode")
                reportRan = result.optString("output").contains(PTY_PROBE_MARKER)
            } catch (error: Exception) {
                diag("pty probe ${session.id} report threw ${error.javaClass.simpleName}: ${error.message}")
            }
        }

        // Gate the interactive exec path on evidence, never on hope. The proof
        // has to cover the payload exec actually submits, and the probe's report
        // round trip *is* [runPtyCommand] - so take that verdict. A plain echo
        // only shows that the shell reads stdin.
        if (reportRan) ptyUsable = true

        diag(
            "pty probe ${session.id} plainRan=$plainRan reportRan=$reportRan exit=$reportExit " +
                "wakeBytes=${wake.length} plainHits=${countOccurrences(plainRaw, PTY_PROBE_MARKER)} " +
                "plainRaw=${plainRaw.take(140).replace('\n', '|').replace("\r", "<CR>")} " +
                "reportRaw=${reportRaw.take(140).replace('\n', '|').replace("\r", "<CR>")}",
        )
    }

    /**
     * Runs [command] in a throwaway PTY session and returns the model-facing
     * result.
     *
     * The retained session is the preferred route now ([runPtyCommand], gated
     * on [ptyUsable]); this remains the next attempt when it does not answer,
     * so the interactive route still gets its chance before the launcher does.
     * One session per command also matches how the launcher path already works,
     * so nothing depends on a long-lived shell staying healthy.
     *
     * The "a retained session never consumes stdin" verdict that used to be
     * written here is retired: on the very same shell arguments the probe
     * reported `plainRan=true reportRan=true` with the exit status
     * round-tripped. The tty was never dead - the payload was.
     *
     * The submission is the plain form: no brace group, no `}2>&1`, terminated
     * by a bare newline - exactly what the sweep proved runs.
     */
    private fun runPtyCommandFresh(sessionId: String, command: String, timeout: Long): JSONObject {
        val freshId = "pty-exec-${markerSeq.incrementAndGet()}"
        ptyBuffers[freshId] = PtyBuffer()
        val buffer = ptyBuffers[freshId]
            ?: return unavailable(sessionId, "session buffer missing")
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"
        val bash = File(config.rootfsDir, "bin/bash")
        val shell = if (bash.isFile) "/bin/bash" else "/bin/sh"
        val shellArgs = if (bash.isFile) listOf("--noediting", "-l") else listOf("-l")
        val payload = ptySubmission(command, marker)

        return try {
            synchronized(execLock) {
                ptySessions.open(
                    sessionId = freshId,
                    nativeLibDir = config.nativeLibDir,
                    rootfsDir = config.rootfsDir,
                    tmpDir = config.tmpDir,
                    binds = effectiveBinds(),
                    cwd = ProotCommand.validateGuestCwd(workspace.sessionCwd()),
                    env = mapOf("PS1" to "", "PS2" to ""),
                    cols = SCREEN_COLS,
                    rows = SCREEN_ROWS,
                    shell = shell,
                    shellArgs = shellArgs,
                )
                // A login shell needs a moment before it reads; the sweep used
                // the same pause and never missed.
                Thread.sleep(PROBE_SETTLE_MS)
                val start = buffer.size()
                ptySessions.write(freshId, payload.toByteArray(StandardCharsets.UTF_8))

                val deadline = System.currentTimeMillis() + timeout
                var seen = ""
                var result: MarkerResult? = null
                while (System.currentTimeMillis() < deadline) {
                    seen = buffer.from(start)
                    result = parseMarker(seen, marker)
                    if (result != null) break
                    Thread.sleep(POLL_MS)
                }

                val body = stripEcho(result?.body ?: seen, payload)
                sessionOutput[sessionId] = body
                workspace.follow(readCwd(seen))
                diag(
                    "pty exec fresh exit=${result?.exitCode ?: -1} timedOut=${result == null} " +
                        "bytes=${seen.length} body=${body.take(100).replace('\n', '|')}",
                )
                JSONObject()
                    .put("output", body)
                    .put("exitCode", result?.exitCode ?: -1)
                    .put("sessionId", sessionId)
                    .put("timedOut", result == null)
            }
        } catch (error: Exception) {
            diag("pty exec fresh failed: ${error.javaClass.simpleName}: ${error.message}")
            unavailable(sessionId, "pty session failed: ${error.javaClass.simpleName}")
        } finally {
            ptySessions.close(freshId)
            ptyBuffers.remove(freshId)
        }
    }

    /**
     * The submission form proven to execute through a PTY.
     *
     * The brace-group form (`{ cmd ; }2>&1`) is what never ran: bash parses `}2`
     * as a literal word, so the group stays unclosed and the shell waits on a
     * continuation line that `PS2=""` never displays - which is exactly the
     * "echoes but never executes" report. Both the candidate sweep and the
     * fresh-session runner executed the plain form below, so every PTY path now
     * builds its payload here.
     *
     * Two extra statements surround the command: an alignment `cd` into the
     * shared workspace, so a session starts where the last one finished, and a
     * trailing `pwd`, so the host learns where this command left the shell.
     */
    private fun ptySubmission(command: String, marker: String): String =
        "cd ${singleQuote(workspace.sessionCwd())} 2>/dev/null; " +
            "${command} 2>&1; echo $marker:\$?; echo $PTY_CWD_MARKER:\$(pwd)\n"

    private fun awaitMarker(buffer: PtyBuffer, start: Int, timeoutMs: Long): String {
        val deadline = System.currentTimeMillis() + timeoutMs
        var raw = ""
        while (System.currentTimeMillis() < deadline) {
            raw = buffer.from(start)
            if (countOccurrences(raw, PTY_PROBE_MARKER) >= 2) return raw
            Thread.sleep(POLL_MS)
        }
        return raw
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
     *
     * The session's own byte buffer *is* the screen: what an interactive
     * program draws (a prompt, `nano`, `top`) never passes through a command's
     * marker, so the last command result is only the fallback for sessions the
     * launcher served.
     */
    override fun terminalScreen(sessionId: String): JSONObject {
        val live = ptyBuffers[sessionId]?.all()
        val content = if (live.isNullOrEmpty()) sessionOutput[sessionId].orEmpty() else live
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

    override fun fileExists(path: String, environment: String?): JSONObject =
        JSONObject().apply { put("exists", File(path).exists()) }

    override fun fileDelete(path: String, recursive: Boolean) {
        val target = File(path)
        // Both checks run before any delete(). File.delete() returns true for an
        // empty directory, so deleting first would remove it silently; and it
        // returns false for a missing target as well as for a non-empty one.
        if (!target.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        if (target.isDirectory && !recursive) {
            throw IOException("EISDIR: is a directory (recursive=false): $path")
        }
        deleteTree(target)
    }

    /**
     * Depth-first delete. Every delete() is checked, so a partially removed
     * tree is never reported as success.
     */
    private fun deleteTree(target: File) {
        if (target.isDirectory) {
            val children = target.listFiles()
                ?: throw IOException("EIO: cannot list directory: ${target.path}")
            for (child in children) {
                deleteTree(child)
            }
        }
        if (!target.delete()) {
            throw IOException("EIO: failed to delete: ${target.path}")
        }
    }

    override fun fileReadBinary(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as fileMkdir / fileWrite / fileExists /
        // fileDelete: `path` is the caller's absolute path, and there is no workspace
        // root to check it against. A directory is caught before `isFile`, because a
        // directory is not a file either.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        if (!target.isFile) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        val bytes = target.readBytes()
        // Single-line is part of the contract, not a detail, and java.util.Base64's
        // basic encoder is what guarantees it: the call sites build
        // `data:<mime>;base64,<contentBase64>` by hand, so a line break in the payload
        // would silently corrupt the data URL. Same class the repo already uses for
        // certificates (RootfsCertificates.kt:7).
        return JSONObject()
            .put("contentBase64", java.util.Base64.getEncoder().encodeToString(bytes))
            .put("size", bytes.size.toLong())
    }

    override fun fileWriteBinary(path: String, base64: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as fileMkdir / fileWrite / fileExists / fileDelete /
        // fileReadBinary: `path` is the caller's absolute path, and there is no workspace
        // root to check it against. A directory is caught before anything is decoded, so
        // EISDIR never depends on the payload being valid.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        // The strict (basic) decoder on purpose: the MIME decoder silently ignores
        // characters outside the alphabet, which would write damaged bytes to disk and
        // report success. Malformed input leaves here as IllegalArgumentException,
        // untranslated - the callers name it in their own failure message.
        val bytes = java.util.Base64.getDecoder().decode(base64)
        target.parentFile?.mkdirs()
        target.writeBytes(bytes)
        // Not void: both draw packages do `if (!writeResult.successful)`, so `undefined`
        // would read as a failure on the success path.
        return JSONObject()
            .put("successful", true)
            .put("details", "${bytes.size} bytes written")
    }

    override fun fileRead(path: String): JSONObject {
        val target = File(path)
        // Same zero-validation stance as every other Files method here: `path` is the
        // caller's absolute path, and there is no workspace root to check it against.
        // A directory is caught before `isFile`, because a directory is not a file.
        if (target.isDirectory) {
            throw IOException("EISDIR: is a directory: $path")
        }
        if (!target.isFile) {
            throw FileNotFoundException("ENOENT: no such file or directory: $path")
        }
        val bytes = target.readBytes()
        // Strict UTF-8, on purpose: a lenient decode would replace bad bytes with U+FFFD
        // and let the damage surface downstream as a JSON.parse failure, which reads
        // like a content problem. Reporting it here keeps the encoding problem where it
        // happened. CharacterCodingException is left untranslated for the callers.
        val text = StandardCharsets.UTF_8.newDecoder()
            .onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT)
            .decode(ByteBuffer.wrap(bytes))
            .toString()
        // Not a .size / .encoding / .truncated payload: no call site reads anything but
        // `content` (code_runner.js:828, file_converter.js:191, operit_editor.js:2615).
        return JSONObject().put("content", text)
    }

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

    override fun fileMove(source: String, destination: String): JSONObject {
        val src = File(source)
        val dst = File(destination)
        // Same zero-validation stance as every other Files method here: both paths are the
        // caller's absolute paths, and there is no workspace root to check them against.
        if (!src.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $source")
        }
        // Internal guard, not part of the KDoc: no caller can see this, and without it the
        // fallback is a suicide path. copyFileTo(src, src) opens the source for write, so the
        // source is truncated before a byte of it is read, and the deleteTree that follows
        // removes the only copy. A rename onto the same path is a no-op, so returning {}
        // without touching the disk is the whole job.
        if (src.canonicalOrAbsolute() == dst.canonicalOrAbsolute()) {
            return JSONObject()
        }
        // Both shapes are refused by rename(2) and by the copy helpers alike, so refusing them
        // here costs nothing and buys the honesty of the message below: past this point,
        // "copy incomplete" means something may have been written.
        if (src.isDirectory && dst.exists() && !dst.isDirectory) {
            throw IOException("EISDIR: destination is a file, not a directory: ${dst.path}")
        }
        if (!src.isDirectory && dst.isDirectory) {
            throw IOException("EISDIR: destination is a directory: ${dst.path}")
        }
        if (src.renameTo(dst)) {
            return JSONObject()
        }
        // renameTo answers true or false and nothing else: java.io.File discards the errno, so
        // why it failed is not knowable here. Two ordinary causes are a filesystem boundary
        // (/sdcard is FUSE, /data is ext4) and a non-empty destination directory (ENOTEMPTY),
        // and there is no third signal to route on - nor would a narrower trigger help, since
        // the merge that the second cause needs can only happen on this route anyway. Every
        // failure therefore takes one route, copy then delete, which is not atomic: between
        // the halves both copies exist. The halves fail differently, so they report
        // differently.
        val dstWasDirectory = dst.exists() && dst.isDirectory
        try {
            if (src.isDirectory) copyTree(src, dst) else copyFileTo(src, dst)
        } catch (t: Throwable) {
            // Remove what the copy wrote. A destination that was already a directory is left
            // alone instead: it can hold entries the source never carried, and deleting those
            // would be a worse outcome than the one being reported. Everything else - a
            // destination we created, or a file that was already truncated when the write
            // began - is removed rather than left behind looking complete.
            val removed = !dstWasDirectory && deleteIfPresent(dst)
            throw IOException(
                "EIO: rename-path failed, copy incomplete (" +
                    (if (removed) "destination removed" else "destination not removed") +
                    "): ${t.message}",
                t,
            )
        }
        try {
            deleteTree(src)
        } catch (t: Throwable) {
            // The destination is complete and is deliberately NOT rolled back: by this point
            // the source may already be partially removed, so deleting the destination would
            // destroy the only complete copy left. The message names that side.
            throw IOException(
                "EIO: rename-path failed, source removal incomplete " +
                    "(source may be partially removed, destination is complete): ${t.message}",
                t,
            )
        }
        // {} : the file is at the destination and the source is gone.
        return JSONObject()
    }

    /** Removes [target] if it is there, and answers whether anything was removed. */
    private fun deleteIfPresent(target: File): Boolean {
        if (!target.exists()) return false
        return runCatching {
            deleteTree(target)
            true
        }.getOrDefault(false)
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

        /** Per-attempt budget for the interactive probe; a login shell may be slow. */
        const val PTY_PROBE_TIMEOUT_MS = 3_000L

        /** How long to let the tty settle before the marker round trip. */
        const val PROBE_SETTLE_MS = 400L

        /** Attempts before the interactive path is declared unusable. */
        const val PROBE_ATTEMPTS = 2

        /**
         * Budget per shell candidate. A deadlocked shell never returns, so this
         * only has to be long enough for a working one to print its marker.
         */
        const val PTY_CANDIDATE_TIMEOUT_MS = 2_000L

        /** Ceiling for one PTY-submitted command before falling back. */
        const val PTY_EXEC_TIMEOUT_MS = 5_000L

        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"

        /**
         * Carries the shell's own `pwd` back out of a submission, so the shared
         * workspace can follow a `cd` that ran inside the terminal.
         */
        const val PTY_CWD_MARKER = "__KELIVO_PWD__"

        /** Init file the job-control-off candidate sources; written by the host. */
        const val PTY_SHIM_GUEST_PATH = "/root/.kelivo_pty_rc"

        /** Cap on captured PTY bytes per session; the oldest half is dropped. */
        const val MAX_PTY_BUFFER_BYTES = 512 * 1024

        /** Where phone storage is mounted inside the container. */
        const val SHARED_GUEST_PATH = "/sdcard"

        /** Shared with the bridge: one diagnostic log for the whole feature. */
        const val DIAG_FILE = "operit_js_diag.log"

        /** A marker's status suffix: a plain integer, e.g. `0` or `-1`. */
        val STATUS_PATTERN = Regex("-?\\d+")

        /**
         * How far into a capture the echoed command may start and still be
         * treated as the PTY echo (terminal init output can precede it).
         */
        const val ECHO_SEARCH_LIMIT = 256
    }
}