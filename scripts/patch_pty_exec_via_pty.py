#!/usr/bin/env python3
"""Route terminal.exec through the PTY once it is proven, and record both payload forms.

What the device said:

  * The candidate sweep ran four shells - including the very `--noediting -l`
    configuration believed to deadlock - and every one of them executed a
    marker echo (`ran=true markerHits=2`). So the interactive path *does* work.
  * The session created by `ensureSession`, with that same shell, does not read
    its stdin at all: `rchar=11485 / wchar=0 / syscr=27` stayed frozen across a
    probe, a plain `touch` written through the app's own master fd, and six
    signals.
  * The one structural difference left is concurrency: the candidates are
    created serially under `execLock`, while `terminalExec` starts a *second*
    proot (runSessionCommand) beside the live PTY one - and the host's own
    comment says PRoot is not safe to launch concurrently.

So: once the PTY is proven able to run a command, `terminalExec` submits through
it and only falls back to the proot launcher when the PTY yields nothing. The
probe also records the plain and the report payload separately, so the next log
line says whether a failing session fails for both forms.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()

# ---------------------------------------------------------------------------
# 1. terminalExec prefers the proven PTY, falls back to the proot launcher
# ---------------------------------------------------------------------------
old_exec = '''        val trimmed = command.trim()
        if (trimmed.isEmpty()) return unavailable(sessionId, "empty command")

        return runSessionCommand(sessionId, trimmed, timeout)
    }
'''
new_exec = '''        val trimmed = command.trim()
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

        return runSessionCommand(sessionId, trimmed, timeout)
    }
'''

# ---------------------------------------------------------------------------
# 2. the probe records the plain form and the report form separately
# ---------------------------------------------------------------------------
old_probe = '''        var ran = false
        var raw = ""
        var lastExit = -1
        try {
            for (attempt in 1..PROBE_ATTEMPTS) {
                val start = buffer.size()
                val result = runPtyCommand(session.id, "echo $PTY_PROBE_MARKER", PTY_PROBE_TIMEOUT_MS)
                raw = buffer.from(start)
                lastExit = result.optInt("exitCode")
                if (result.optString("output").contains(PTY_PROBE_MARKER)) {
                    ran = true
                    break
                }
                diag("pty probe ${session.id} attempt=$attempt miss rawBytes=${raw.length}")
            }
        } catch (error: Exception) {
            diag("pty probe ${session.id} threw ${error.javaClass.simpleName}: ${error.message}")
            return
        }

        diag(
            "pty probe ${session.id} ran=$ran exit=$lastExit wakeBytes=${wake.length} " +
                "rawBytes=${raw.length} " +
                "raw=${raw.take(200).replace('\\n', '|').replace("\\r", "<CR>")}",
        )
    }
'''
new_probe = '''        // The plain form first. The candidate sweep shows a bare echo does run
        // through a fresh session, so a session that ignores even this is
        // broken independently of how the report payload is built.
        val plainStart = buffer.size()
        send(session, "echo $PTY_PROBE_MARKER\\n")
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

        // Gate the interactive exec path on evidence, never on hope.
        if (plainRan) ptyUsable = true

        diag(
            "pty probe ${session.id} plainRan=$plainRan reportRan=$reportRan exit=$reportExit " +
                "wakeBytes=${wake.length} plainHits=${countOccurrences(plainRaw, PTY_PROBE_MARKER)} " +
                "plainRaw=${plainRaw.take(140).replace('\\n', '|').replace("\\r", "<CR>")} " +
                "reportRaw=${reportRaw.take(140).replace('\\n', '|').replace("\\r", "<CR>")}",
        )
    }

    /**
     * Waits until [needle] has been seen twice (the PTY echo, plus what the
     * command itself printed) or the budget runs out; returns what was captured.
     */
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
'''

# ---------------------------------------------------------------------------
# 3. the flag and the exec timeout
# ---------------------------------------------------------------------------
old_flag = '''    /** Non-zero once the shell-candidate sweep has been started. */
    private val candidatesProbed = AtomicLong()
'''
new_flag = '''    /** Non-zero once the shell-candidate sweep has been started. */
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
'''

old_const = '''        /**
         * Budget per shell candidate. A deadlocked shell never returns, so this
         * only has to be long enough for a working one to print its marker.
         */
        const val PTY_CANDIDATE_TIMEOUT_MS = 2_000L
'''
new_const = '''        /**
         * Budget per shell candidate. A deadlocked shell never returns, so this
         * only has to be long enough for a working one to print its marker.
         */
        const val PTY_CANDIDATE_TIMEOUT_MS = 2_000L

        /** Ceiling for one PTY-submitted command before falling back. */
        const val PTY_EXEC_TIMEOUT_MS = 5_000L
'''

for index, (old_text, new_text) in enumerate(
    [
        (old_exec, new_exec),
        (old_probe, new_probe),
        (old_flag, new_flag),
        (old_const, new_const),
    ],
    start=1,
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

path.write_text(src)
print("patched")
print("ptyUsable refs:", src.count("ptyUsable"))
print("awaitMarker refs:", src.count("awaitMarker"))
print("plainRan refs:", src.count("plainRan"))
print("PTY_EXEC_TIMEOUT_MS refs:", src.count("PTY_EXEC_TIMEOUT_MS"))