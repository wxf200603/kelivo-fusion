#!/usr/bin/env python3
"""Submit terminal commands through a fresh PTY session.

Evidence from the device:

  * Four freshly created PTY sessions - including the `--noediting -l` one
    believed to deadlock - each executed a marker echo (ran=true markerHits=2).
  * The *retained* session created by ensureSession does not consume stdin: its
    io counters stay frozen at rchar=11485 / wchar=0 / syscr=27, six signals
    produce no reaction, and a command written through the app's own master fd
    is ignored. Meanwhile it still prints a prompt, so it can write but not
    read.

A retained session is therefore the wrong vehicle, while a per-command session
is proven to work. This mirrors the launcher path, which already runs one
process per call.

Ordering in terminalExec becomes: retained PTY (only if a probe proved it) ->
fresh PTY session -> proot launcher. Each step is verified before the next is
tried, so behaviour cannot regress below what already ships.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()

# ---------------------------------------------------------------------------
# 1. terminalExec: add the fresh-session step between PTY and launcher
# ---------------------------------------------------------------------------
old_exec = '''            if (!viaPty.optBoolean("timedOut") && viaPty.optInt("exitCode") >= 0) return viaPty
            diag(
                "pty exec fell back to proot: timedOut=${viaPty.optBoolean("timedOut")} " +
                    "exit=${viaPty.optInt("exitCode")} out=${viaPty.optString("output").take(80)}",
            )
        }

        return runSessionCommand(sessionId, trimmed, timeout)
'''
new_exec = '''            if (!viaPty.optBoolean("timedOut") && viaPty.optInt("exitCode") >= 0) return viaPty
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
'''

# ---------------------------------------------------------------------------
# 2. the fresh-session runner
# ---------------------------------------------------------------------------
anchor_await = '''    /**
     * Waits until [needle] has been seen twice (the PTY echo, plus what the
     * command itself printed) or the budget runs out; returns what was captured.
     */
'''

new_runner = '''    /**
     * Runs [command] in a throwaway PTY session and returns the model-facing
     * result.
     *
     * Why not the retained session: it never consumes stdin (io counters
     * frozen, no reaction to six signals, a command written through the app's
     * own master fd ignored) even though it happily writes a prompt. Fresh
     * sessions, by contrast, executed every probe the candidate sweep gave
     * them. One session per command also matches how the launcher path already
     * works, so nothing depends on a long-lived shell staying healthy.
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
        val payload = "$command 2>&1; echo $marker:\\$?\\n"

        return try {
            synchronized(execLock) {
                ptySessions.open(
                    sessionId = freshId,
                    nativeLibDir = config.nativeLibDir,
                    rootfsDir = config.rootfsDir,
                    tmpDir = config.tmpDir,
                    binds = effectiveBinds(),
                    cwd = ProotCommand.validateGuestCwd(config.defaultCwd),
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
                diag(
                    "pty exec fresh exit=${result?.exitCode ?: -1} timedOut=${result == null} " +
                        "bytes=${seen.length} body=${body.take(100).replace('\\n', '|')}",
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

'''

for index, (old_text, new_text) in enumerate([(old_exec, new_exec)], start=1):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

anchor_found = src.count(anchor_await)
if anchor_found != 1:
    raise SystemExit(f"anchor for runner: expected 1 match, found {anchor_found}")
src = src.replace(anchor_await, new_runner + anchor_await)

path.write_text(src)
print("patched")
print("runPtyCommandFresh refs:", src.count("runPtyCommandFresh"))
print("MarkerResult refs:", src.count("MarkerResult"))
print("parseMarker refs:", src.count("parseMarker"))
print("stripEcho refs:", src.count("stripEcho"))
print("execLock refs:", src.count("execLock"))