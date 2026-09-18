#!/usr/bin/env python3
"""Add a one-shot interactive-PTY self check to KelivoWorkspaceHost.

Why: the PTY path was written off as unusable ("the shell never receives what is
written to the master side") and terminalExec routes around it. An on-device
reproduction with this exact proot argv and `/bin/bash --noediting -l` executed
the command fine, so the old verdict is not trustworthy. Instead of silently
routing around a path that may work, probe it once per session and record the
answer in the diagnostics file.

Behaviour is deliberately unchanged: terminalExec keeps using the verified proot
launcher until the probe produces evidence that the PTY works.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()
original = src

# --- 1: probe on session creation -------------------------------------------
old = '''    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        ensureSession(id)
        return id
    }
'''
new = '''    override fun terminalCreate(sessionName: String): String {
        val id = sessionName.ifBlank { "kelivo-${System.nanoTime()}" }
        // The interactive path was reported broken before; re-check it on every
        // new session so the claim is either confirmed or retired by evidence.
        ensureSession(id)?.let { probePty(it) }
        return id
    }
'''

# --- 2: remember probed sessions --------------------------------------------
old2 = '''    private val sessions = ConcurrentHashMap<String, PtyHandle>()
'''
new2 = '''    private val sessions = ConcurrentHashMap<String, PtyHandle>()

    /** Sessions whose one-shot PTY round trip has already been attempted. */
    private val ptyProbed = ConcurrentHashMap<String, Boolean>()
'''

# --- 3: drop the stale "deliberately not routed through a PTY" claim --------
old3 = '''    /**
     * Runs one command and returns the model-facing result.
     *
     * Deliberately *not* routed through a PTY. Interactive PTYs are wired up
     * ([ensureSession], [terminalInput], [terminalScreen]) but on device the
     * shell never received what was written to the master side, so commands go
     * through the proot launcher that is verified to work.
     *
     * Session identity is preserved by carrying the working directory across
     * calls \u2014 the state agents actually rely on (`cd`, then relative paths) \u2014
     * rather than by keeping a process alive.
     */
'''
new3 = '''    /**
     * Runs one command and returns the model-facing result.
     *
     * Still routed through the proot launcher rather than the PTY: that path is
     * verified, and its marker protocol keeps the captured stream to the
     * command's own output. [probePty] reports whether the interactive path
     * works on this build, so a future switch to PTY submission is based on
     * evidence instead of the earlier assumption that it never worked.
     *
     * Session identity is preserved by carrying the working directory across
     * calls \u2014 the state agents actually rely on (`cd`, then relative paths) \u2014
     * rather than by keeping a process alive.
     */
'''

# --- 4: runPtyCommand is used again, and its comment must stop lying --------
old4 = '''    /**
     * Interactive PTY dispatch, kept for reference but currently unused.
     *
     * The PTY opens and echoes, yet the shell inside never receives what is
     * written to the master side, so no command ever runs through it. See the
     * class comment; [terminalExec] uses [runSessionCommand] instead.
     */
    @Suppress("unused")
    private fun runPtyCommand(sessionId: String, trimmed: String, timeout: Long): JSONObject {
'''
new4 = '''    /**
     * Interactive PTY dispatch: writes a command into the session's PTY and
     * waits for the marker line the shell prints back.
     *
     * Once written off \u2014 the PTY echoed input while the shell never ran a
     * command. An on-device reproduction with this exact proot argv and shell
     * did execute the command, and `--noediting` above is the fix for the
     * readline case, so the old verdict is no longer taken on faith.
     * [probePty] re-tests it; this is the path [terminalInput] and [terminalScreen]
     * already serve.
     */
    private fun runPtyCommand(sessionId: String, trimmed: String, timeout: Long): JSONObject {
'''

# --- 5: the probe itself ----------------------------------------------------
old5 = '''    private fun send(session: PtyHandle, text: String): Boolean =
        sendRaw(session, text.toByteArray(StandardCharsets.UTF_8))
'''
new5 = '''    /**
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

    private fun send(session: PtyHandle, text: String): Boolean =
        sendRaw(session, text.toByteArray(StandardCharsets.UTF_8))
'''

# --- 6: constants -----------------------------------------------------------
old6 = '''        const val POLL_MS = 25L
'''
new6 = '''        const val POLL_MS = 25L

        /** Budget for the one-shot interactive probe; a login shell may be slow. */
        const val PTY_PROBE_TIMEOUT_MS = 4_000L

        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"
'''

for index, (old_text, new_text) in enumerate(
    [(old, new), (old2, new2), (old3, new3), (old4, new4), (old5, new5), (old6, new6)],
    start=1,
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

path.write_text(src)
print("patched:", path)
print("changed:", src != original)
print("probePty refs:", src.count("probePty("))
print("runPtyCommand refs:", src.count("runPtyCommand("))
