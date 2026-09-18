#!/usr/bin/env python3
"""Add a multi-candidate self check for the interactive PTY.

Root cause established on device: an *interactive* shell under proot
deadlocks; the tracer and the tracee both sit in `get_signal`, the shell never
reads stdin, and writing to the master fd changes nothing (bash io counters:
rchar unchanged, wchar=0, syscw=0). Non-interactive `bash -lc` is unaffected,
which points at job control.

So instead of guessing one fix per 25-minute CI round, the host now tests
several shell configurations in one pass and logs each verdict:

  bash-current  --noediting -l        (the configuration that deadlocks)
  bash-set+m    --noediting --init-file <shim>   (job control off)
  bash-norc     --noediting --norc --noprofile -i
  sh-i          -i                    (dash's interactive startup is minimal)

Each candidate gets its own throwaway PTY session, one marker round trip, and a
line in the diagnostics file. A deadlocked candidate costs its timeout and
nothing else; a working one returns in milliseconds.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()

# ---------------------------------------------------------------------------
# 1. run the candidate sweep before the session is described as usable
# ---------------------------------------------------------------------------
old_create = '''    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        // The interactive path was reported broken before; re-check it on every
        // new session so the claim is either confirmed or retired by evidence.
        ensureSession(id)?.let { probePty(it) }
        return id
    }
'''
new_create = '''    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        // Which shell can run interactively under proot is an open question
        // (see [probeShellCandidates]); answer it before reporting a session.
        probeShellCandidates()
        // The interactive path was reported broken before; re-check it on every
        // new session so the claim is either confirmed or retired by evidence.
        ensureSession(id)?.let { probePty(it) }
        return id
    }
'''

# ---------------------------------------------------------------------------
# 2. the candidates and their sweep
# ---------------------------------------------------------------------------
new_block = '''    /** A shell configuration worth testing for the interactive PTY. */
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
        val body = "# Written by Kelivo for the interactive PTY probe.\\n" +
            "# Job control off: tcsetpgrp is what the proot tracer deadlocks on.\\n" +
            "set +m\\n"
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
                cwd = ProotCommand.validateGuestCwd(config.defaultCwd),
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
            ptySessions.write(sessionId, "\\n".toByteArray(StandardCharsets.UTF_8))
            Thread.sleep(PROBE_SETTLE_MS)
            val wake = buffer.from(0)

            val payload = "echo $PTY_PROBE_MARKER\\n"
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
                "raw=${raw.take(140).replace('\\n', '|').replace("\\r", "<CR>")}"
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

'''

anchor_probe = '''    /**
     * Marker round trip that answers "can this PTY actually run a command?".
'''

# ---------------------------------------------------------------------------
# 3. field, shim path constant, candidate timeout
# ---------------------------------------------------------------------------
old_field = '''    /** Sessions whose one-shot PTY round trip has already been attempted. */
    private val ptyProbed = ConcurrentHashMap<String, Boolean>()
'''
new_field = '''    /** Sessions whose one-shot PTY round trip has already been attempted. */
    private val ptyProbed = ConcurrentHashMap<String, Boolean>()

    /** Non-zero once the shell-candidate sweep has been started. */
    private val candidatesProbed = AtomicLong()
'''

old_const = '''        /** Attempts before the interactive path is declared unusable. */
        const val PROBE_ATTEMPTS = 2
'''
new_const = '''        /** Attempts before the interactive path is declared unusable. */
        const val PROBE_ATTEMPTS = 2

        /**
         * Budget per shell candidate. A deadlocked shell never returns, so this
         * only has to be long enough for a working one to print its marker.
         */
        const val PTY_CANDIDATE_TIMEOUT_MS = 2_000L
'''

old_pyshim = '''        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"
'''
new_pyshim = '''        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"

        /** Init file the job-control-off candidate sources; written by the host. */
        const val PTY_SHIM_GUEST_PATH = "/root/.kelivo_pty_rc"
'''

for index, (old_text, new_text) in enumerate(
    [
        (old_create, new_create),
        (old_field, new_field),
        (old_const, new_const),
        (old_pyshim, new_pyshim),
    ],
    start=1,
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

anchor_found = src.count(anchor_probe)
if anchor_found != 1:
    raise SystemExit(f"anchor for candidate block: expected 1 match, found {anchor_found}")
src = src.replace(anchor_probe, new_block + anchor_probe)

path.write_text(src)
print("patched")
print("probeShellCandidates refs:", src.count("probeShellCandidates"))
print("probeShellCandidate refs:", src.count("probeShellCandidate"))
print("ShellCandidate refs:", src.count("ShellCandidate"))
print("candidatesProbed refs:", src.count("candidatesProbed"))
print("countOccurrences refs:", src.count("countOccurrences"))
print("illegal replace(Char,String):", bool(__import__("re").search(r"\\.replace\\('(?:[^'\\\\\\\\]|\\\\\\\\.)*',\\s*\\\"", src)))
print("return@repeat present:", "return@repeat" in src)
print("has AtomicLong import:", "import java.util.concurrent.atomic.AtomicLong" in src)
