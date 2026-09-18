#!/usr/bin/env python3
"""Make the interactive terminal actually interactive.

Device evidence from `operit_js_diag.log` after 62ff490 (one `ls -la` call):

    pty candidate bash-current  ran=true markerHits=2      <- 4/4, incl. --noediting -l
    pty candidate bash-set+m    ran=true markerHits=2
    pty candidate bash-norc     ran=true markerHits=2
    pty candidate sh-i          ran=true markerHits=2
    pty open super_admin_default_session_kelivo-shared pid=18501 shell=/bin/bash
    pty probe ... plainRan=true reportRan=true exit=0
      reportRaw=echo __KELIVO_PTY_PROBE__ 2>&1; echo __KELIVO_END_1__:$?<CR>|..|__KELIVO_END_1__:0<CR>|
    pty send ... bytes=38 offset=151                       <- the real command, retained session
    result super_admin:terminal -> {"command":"ls -la", "exitCode":0, ...}

No `pty exec fell back` and no `pty exec fresh` line: the retained session ran the
command itself. That retires two claims this patch cleans up:

  1. The verdict "a retained session never consumes stdin" was a payload bug, not
     a dead tty, so its comment is retired.
  2. The exec gate was `plainRan`, but the payload exec submits is the report
     round trip - which is literally runPtyCommand. Gate on the form in use.

One real gap was left behind: the retained-session path never recorded its own
output, and terminalScreen only read that record - so the screen stayed blank or
stale exactly when the interactive path started working. The screen now reads the
session's own byte buffer, which is the only place an interactive program's
drawing shows up, and a live terminal tail is preferred over a command result.

Backslashes are built with chr() on purpose: the surrounding tooling passes file
content through verbatim, so a literal backslash in this source is not something
to reason about twice.
"""
from pathlib import Path

BS = chr(92)
NL = chr(10)

host = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = host.read_text()

# 1) The screen is the session's own PTY bytes; the last result is the fallback.
old1 = '''    /**
     * Live tail of the session's PTY output.
     *
     * Field names match what `super_admin.js` reads. A real screen model would
     * need a terminal emulator; the tail is what an agent actually needs.
     */
    override fun terminalScreen(sessionId: String): JSONObject {
        val content = sessionOutput[sessionId].orEmpty()
        return JSONObject()
            .put("sessionId", sessionId)
            .put("rows", SCREEN_ROWS)
            .put("cols", SCREEN_COLS)
            .put("content", content.takeLast(SCREEN_ROWS * SCREEN_COLS))
    }
'''
new1 = '''    /**
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
'''

# 2) The retained-session path records what it printed, like the other two paths.
old2 = '''        val deadline = System.currentTimeMillis() + timeout
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
'''
new2 = '''        val deadline = System.currentTimeMillis() + timeout
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
                return JSONObject()
                    .put("output", body)
                    .put("exitCode", finished?.exitCode ?: -1)
                    .put("sessionId", sessionId)
                    .put("timedOut", finished == null)
            }
            Thread.sleep(POLL_MS)
        }
'''

# 3) Gate the exec path on the form it actually submits.
old3 = '''        // Gate the interactive exec path on evidence, never on hope.
        if (plainRan) ptyUsable = true
'''
new3 = '''        // Gate the interactive exec path on evidence, never on hope. The proof
        // has to cover the payload exec actually submits, and the probe's report
        // round trip *is* [runPtyCommand] - so take that verdict. A plain echo
        // only shows that the shell reads stdin.
        if (reportRan) ptyUsable = true
'''

# 4) Retire the verdict the probe disproved.
old4 = '''    /**
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
'''
new4 = '''    /**
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
'''

for index, (old_text, new_text) in enumerate(
    [(old1, new1), (old2, new2), (old3, new3), (old4, new4)], start=1
):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

# ---- self checks ----------------------------------------------------------------

# The bug class that cost this project days: a redirect welded onto the word
# before it. `$command2>&1` submits `cmd2>&1`, so bash hands the trailing digit
# to the command (`ls -la2` -> "invalid option -- '2'"). Comments may *describe*
# the broken shape; live code may not contain it.
offenders = []
for number, line in enumerate(src.splitlines(), start=1):
    stripped = line.strip()
    if stripped.startswith(("*", "//", "/*")):
        continue
    at = line.find("2>&1")
    if at > 0 and not line[at - 1].isspace():
        offenders.append(f"{number}: {stripped}")
if offenders:
    raise SystemExit("redirect welded onto a word: " + " | ".join(offenders))

if "val payload = ptySubmission(" not in src:
    raise SystemExit("ptySubmission is no longer used by the PTY paths")

host.write_text(src)

# The patch script that landed the shared submission form still shows the
# pre-fix line (and the pre-CI-fix interpolation). Keep the record honest: the
# escaping it already uses maps a source pair of backslashes onto the single
# output backslash the landed Kotlin line needs.
record = Path("scripts/patch_pty_submission_form.py")
recorded = record.read_text()
tail = BS * 2 + "$?" + BS * 2 + "n"
old5 = '        "$command2>&1; echo $marker:' + tail + '"' + NL
new5 = '        "${command} 2>&1; echo $marker:' + tail + '"' + NL
if recorded.count(old5) == 1:
    record.write_text(recorded.replace(old5, new5))
    print("script record: updated")
else:
    print(f"script record: left alone (matches={recorded.count(old5)})")

print("patched", host)
print("live screen read:", src.count("ptyBuffers[sessionId]?.all()"))
print("sessionOutput writes:", src.count("sessionOutput[sessionId] ="))
print("exec gate:", "reportRan" if "if (reportRan) ptyUsable = true" in src else "plainRan")
print("retired claim left:", src.count("never consumes stdin"))
print(
    "payload lines:",
    [l.strip() for l in src.splitlines() if "2>&1" in l and not l.strip().startswith(("*", "//"))],
)