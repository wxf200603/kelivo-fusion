#!/usr/bin/env python3
"""Make the interactive-PTY probe report raw evidence instead of a verdict.

The first probe said `ran=false body=` — an empty *stripped* body. That is
ambiguous: it happens both when the shell never ran the command and when the
master side yielded nothing at all. Those two worlds need opposite fixes, so the
probe now records:

  * wakeBytes — bytes produced by a bare newline. Echo is the line discipline's
    job, not the shell's, so this separates "tty is in raw/no-echo state" from
    "tty echoes fine, the shell just is not reading".
  * raw        — the unfiltered capture, so an echo-only capture is visible.
  * attempts   — a slow proot login shell is given more than one shot.

It also gives the PTY time to settle and allows retries, because sending into a
shell that has not finished starting is a real failure mode.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()

old_probe = '''    /**
     * One-shot marker round trip that answers "can this PTY actually run a command?".
     *
     * [runPtyCommand] strips the line the PTY echoed back, so a shell that never
     * executes anything leaves an empty body while a working one leaves the text
     * the command itself printed. The verdict is written to the diagnostics file
     * so the claim stops being a matter of recollection.
     */
    private fun probePty(session: PtyHandle) {
        if (ptyProbed.putIfAbsent(session.id, true) != null) return
        val result = try {
            runPtyCommand(session.id, "echo $PTY_PROBE_MARKER", PTY_PROBE_TIMEOUT_MS)
        } catch (error: Exception) {
            diag("pty probe ${session.id} threw ${error.javaClass.simpleName}: ${error.message}")
            return
        }
        val body = result.optString("output")
        diag(
            "pty probe ${session.id} ran=${body.contains(PTY_PROBE_MARKER)} " +
                "exit=${result.optInt("exitCode")} timedOut=${result.optBoolean("timedOut")} " +
                "body=${body.take(120).replace('\\n', '|')}",
        )
    }
'''

new_probe = '''    /**
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
        send(session, "\\n")
        Thread.sleep(PROBE_SETTLE_MS)
        val wake = buffer.from(0)

        var ran = false
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
                "rawBytes=${raw.length} raw=${raw.take(200).replace('\\n', '|').replace('\\r', '<CR>')}",
        )
    }
'''

old_const = '''        /** Budget for the one-shot interactive probe; a login shell may be slow. */
        const val PTY_PROBE_TIMEOUT_MS = 4_000L
'''
new_const = '''        /** Per-attempt budget for the interactive probe; a login shell may be slow. */
        const val PTY_PROBE_TIMEOUT_MS = 3_000L

        /** How long to let the tty settle before the marker round trip. */
        const val PROBE_SETTLE_MS = 400L

        /** Attempts before the interactive path is declared unusable. */
        const val PROBE_ATTEMPTS = 2
'''

for index, (old_text, new_text) in enumerate(
    [(old_probe, new_probe), (old_const, new_const)], start=1
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

path.write_text(src)
print("patched")
print("wakeBytes refs:", src.count("wakeBytes"))
print("PROBE_ATTEMPTS refs:", src.count("PROBE_ATTEMPTS"))
print("return@repeat present:", "return@repeat" in src)