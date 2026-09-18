#!/usr/bin/env python3
"""Bind every terminal session to one shared working directory.

Requirement: `cd` must survive the call that made it. Before this patch the
directory lived in two places and neither was shared - `sessionCwd` was a cache
filled by the launcher path only, and a PTY session just started in
`config.defaultCwd` every time. So a new session, a second session, or a restart
always dropped the user back at /root.

What this patch wires up (all of it against the new GlobalWorkspace):

  1. one shared directory, independent of any PTY session;
  2. every PTY session opens in it (`sessionCwd()` at all three `open` sites);
  3. a `cd` that ran inside the shell is adopted - the submission now ends with
     `echo <marker>:$(pwd)`, so the host learns where the command finished
     rather than trying to parse `cd` out of arbitrary shell text;
  4. divergence is corrected before every command: the payload starts with an
     alignment `cd`, which costs nothing extra because the shell's own `pwd`
     comes back in the same round trip;
  5. the value persists in SharedPreferences, so a restart keeps the directory;
  6. a missing directory falls back to /root and logs it.

The required log markers live in GlobalWorkspace.kt:
  * workspace: loaded global cwd = xxx
  * workspace: update global cwd from cd command, new = xxx
  * workspace: fallback to root, target directory missing
"""
import re
from pathlib import Path

BS = chr(92)

host = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
workspace_file = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/GlobalWorkspace.kt")
src = host.read_text()

# 1) The shared directory, next to the per-session cache it supersedes.
old1 = '''    /** Working directory per session, so `cd` survives between calls. */
    private val sessionCwd = ConcurrentHashMap<String, String>()
'''
new1 = '''    /** Working directory per session, so `cd` survives between calls. */
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
'''

# 2) Every PTY session opens in the shared directory (three open sites).
old2 = "cwd = ProotCommand.validateGuestCwd(config.defaultCwd),"
new2 = "cwd = ProotCommand.validateGuestCwd(workspace.sessionCwd()),"

# 3) The launcher path starts there too, and follows a reported `pwd`.
old3 = '''        val cwd = sessionCwd[sessionId] ?: config.defaultCwd
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"
        val pwdMarker = "__KELIVO_PWD__"
'''
new3 = '''        // The launcher starts in the shared workspace too, so a directory
        // change made anywhere is where the next call begins.
        val cwd = workspace.sessionCwd()
        val marker = "__KELIVO_END_${markerSeq.incrementAndGet()}__"
        val pwdMarker = PTY_CWD_MARKER
'''

old4 = '''                if (next.startsWith("/")) sessionCwd[sessionId] = next
'''
new4 = '''                if (next.startsWith("/")) {
                    sessionCwd[sessionId] = next
                    workspace.follow(next)
                }
'''

# 4) The submission aligns first and reports where it ended.
old5 = (
    "    private fun ptySubmission(command: String, marker: String): String =\n"
    '        "${command} 2>&1; echo $marker:' + BS + "$?" + BS + 'n"\n'
)
new5 = (
    "    private fun ptySubmission(command: String, marker: String): String =\n"
    '        "cd ${singleQuote(workspace.sessionCwd())} 2>/dev/null; " +\n'
    '            "${command} 2>&1; echo $marker:' + BS + "$?; echo $PTY_CWD_MARKER:" + BS + "$(pwd)" + BS + 'n"\n'
)

old6 = '''     * fresh-session runner executed the plain form below, so every PTY path now
     * builds its payload here.
     */
'''
new6 = '''     * fresh-session runner executed the plain form below, so every PTY path now
     * builds its payload here.
     *
     * Two extra statements surround the command: an alignment `cd` into the
     * shared workspace, so a session starts where the last one finished, and a
     * trailing `pwd`, so the host learns where this command left the shell.
     */
'''

# 5) Both PTY paths hand the reported directory to the workspace.
old7 = '''                val body = stripEcho(finished?.body ?: seen, payload)
                // Record it here too: the interactive path used to be the one
                // route that left the screen record stale.
                sessionOutput[sessionId] = body
'''
new7 = '''                val body = stripEcho(finished?.body ?: seen, payload)
                // Record it here too: the interactive path used to be the one
                // route that left the screen record stale.
                sessionOutput[sessionId] = body
                // The shell may have moved since the last call.
                workspace.follow(readCwd(seen))
'''

old8 = '''                val body = stripEcho(result?.body ?: seen, payload)
                sessionOutput[sessionId] = body
'''
new8 = '''                val body = stripEcho(result?.body ?: seen, payload)
                sessionOutput[sessionId] = body
                workspace.follow(readCwd(seen))
'''

# 6) Reading the reported directory out of a capture.
old9 = '''    /** A finished command: its output, and the status the marker carried. */
    private data class MarkerResult(val body: String, val exitCode: Int)
'''
new9 = '''    /** The shell's own `pwd` from a submission; "" when it did not report one. */
    private fun readCwd(seen: String): String = seen.lineSequence()
        .firstOrNull { it.trimEnd('\\r').startsWith("$PTY_CWD_MARKER:") }
        ?.substringAfter("$PTY_CWD_MARKER:")
        ?.trim()
        .orEmpty()

    /** A finished command: its output, and the status the marker carried. */
    private data class MarkerResult(val body: String, val exitCode: Int)
'''

# 7) One marker name shared by both paths.
old10 = '''        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"
'''
new10 = '''        /** Printed by the probe command, looked for in the *stripped* body. */
        const val PTY_PROBE_MARKER = "__KELIVO_PTY_PROBE__"

        /**
         * Carries the shell's own `pwd` back out of a submission, so the shared
         * workspace can follow a `cd` that ran inside the terminal.
         */
        const val PTY_CWD_MARKER = "__KELIVO_PWD__"
'''

pairs = [
    (old1, new1, 1),
    (old2, new2, 3),
    (old3, new3, 1),
    (old4, new4, 1),
    (old5, new5, 1),
    (old6, new6, 1),
    (old7, new7, 1),
    (old8, new8, 1),
    (old9, new9, 1),
    (old10, new10, 1),
]
for index, (old_text, new_text, expected) in enumerate(pairs, start=1):
    found = src.count(old_text)
    if found != expected:
        raise SystemExit(f"patch {index}: expected {expected} match(es), found {found}")
    src = src.replace(old_text, new_text)

# ---- self checks ----------------------------------------------------------------

# The bug class that has cost this project days twice: a redirect welded onto the
# word before it (`$command2>&1` -> `ls -la2`; `'path'2>/dev/null`). A redirect
# must be its own word. Comments may describe the broken shape; live code may not.
REDIRECT = re.compile(r"[0-9]?(?:>&|>/)")
for number, line in enumerate(src.splitlines(), start=1):
    stripped = line.strip()
    if stripped.startswith(("*", "//", "/*")):
        continue
    for match in REDIRECT.finditer(line):
        head = line[: match.start()]
        if head and not head[-1].isspace():
            raise SystemExit(
                f"redirect welded onto the word before it, line {number}: {stripped}",
            )

if not workspace_file.is_file():
    raise SystemExit("GlobalWorkspace.kt is missing; the host would not compile")

workspace_src = workspace_file.read_text()
for marker in (
    "workspace: loaded global cwd = ",
    "workspace: update global cwd from cd command, new = ",
    "workspace: fallback to root, target directory missing ",
):
    if marker not in workspace_src:
        raise SystemExit(f"required log marker missing: {marker}")

# The wiring itself: three PTY opens, the launcher, and the payload's alignment cd.
if src.count("workspace.sessionCwd()") != 5:
    raise SystemExit(f"expected 5 sessionCwd() uses, found {src.count('workspace.sessionCwd()')}")
if src.count("workspace.follow(") != 3:
    raise SystemExit(f"expected 3 follow() uses, found {src.count('workspace.follow(')}")
if src.count("private val workspace = GlobalWorkspace(") != 1:
    raise SystemExit("the workspace is not constructed exactly once")
if "validateGuestCwd(config.defaultCwd)" in src:
    raise SystemExit("a session still opens in the raw default cwd")

host.write_text(src)

print("patched", host)
print("shared cwd uses:", src.count("workspace.sessionCwd()"))
print("follow uses:", src.count("workspace.follow("))
print("markers:", sum(1 for m in (
    "workspace: loaded global cwd = ",
    "workspace: update global cwd from cd command, new = ",
    "workspace: fallback to root, target directory missing ",
) if m in workspace_src))