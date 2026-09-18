#!/usr/bin/env python3
"""Share one proven submission form between both PTY paths.

Device evidence, all from the app itself:

  * `{ echo MARK ; }2>&1; echo …:$?`  -> not executed (echo only)
  * `echo MARK`                       -> executed (candidate sweep, 4/4)
  * `ls -la2>&1; echo MARK:$?`        -> executed, full output returned
                                          (pty exec fresh exit=0 bytes=484)

The common factor in the failures is the brace group: bash parses `}2` as a
literal word, the group never closes, and the shell sits on a continuation line
that `PS2=""` does not display - the exact "echoes but never executes" symptom.

So both the retained-session runner and the fresh-session runner now build their
payload from one helper that uses the plain form, and the brace group is gone
from the PTY path entirely.
"""
from pathlib import Path

path = Path("android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt")
src = path.read_text()

old1 = '''    /**
     * Waits until [needle] has been seen twice (the PTY echo, plus what the
     * command itself printed) or the budget runs out; returns what was captured.
     */
'''
new1 = '''    /**
     * The submission form proven to execute through a PTY.
     *
     * The brace-group form (`{ cmd ; }2>&1`) is what never ran: bash parses `}2`
     * as a literal word, so the group stays unclosed and the shell waits on a
     * continuation line that `PS2=""` never displays - which is exactly the
     * "echoes but never executes" report. Both the candidate sweep and the
     * fresh-session runner executed the plain form below, so every PTY path now
     * builds its payload here.
     */
    private fun ptySubmission(command: String, marker: String): String =
        "$command2>&1; echo $marker:\\$?\\n"

'''

old2 = '''        val payload = "{ $trimmed ; }2>&1; echo $marker:\\$?\\r\\n"
'''
new2 = '''        val payload = ptySubmission(trimmed, marker)
'''

old3 = '''        val payload = "$command 2>&1; echo $marker:\\$?\\n"
'''
new3 = '''        val payload = ptySubmission(command, marker)
'''

for index, (old_text, new_text) in enumerate([(old1, new1), (old2, new2), (old3, new3)], start=1):
    found = src.count(old_text)
    if found != 1:
        raise SystemExit(f"patch {index}: expected exactly 1 match, found {found}")
    src = src.replace(old_text, new_text)

path.write_text(src)
print("patched")
print("ptySubmission refs:", src.count("ptySubmission"))
print("brace-group payload left:", src.count('; }2>&1'))
print("space-brace payload left:", src.count('; } 2>&1'))