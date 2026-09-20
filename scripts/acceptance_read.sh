#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_read.sh by `cp` -- the
# Android root shell cannot see /root, where the repo lives. The repo copy is
# authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_read.sh /sdcard/scripts/
#
# Acceptance driver for `Tools.Files.read` -- five cases, all of them through the
# `host:` prefix.
#
#   usage, as root on the device:
#     sh scripts/acceptance_read.sh preflight  # package / permission / fixture root
#     sh scripts/acceptance_read.sh setup      # preflight + fixtures + marker file
#     sh scripts/acceptance_read.sh restart    # force-stop + relaunch
#     sh scripts/acceptance_read.sh verify     # expectation table, expected vs actual
#
#   the target is the merged build: applicationId `com.psyche.kelivo.fusion`, not
#   the class namespace `com.psyche.kelivo`. Override with PKG= if that changes.
#
#   the marker is one-shot: `maybeRunSelfTest` deletes it after reading, so `setup`
#   has to run again before every round.
#
#   the diag log is append-only and owned by the app, so a round's lines are located
#   by the line count `setup` records in $BASE/.log_offset, not by moving the log
#   aside: `mv` only changes the directory entry, so a writer still holding the old
#   inode would keep appending to the .bak while the new log stayed empty -- a
#   probabilistic failure, and an acceptance driver must not introduce one.
#
#   #  case                          args                  expectation
#   1  read a text file              (file)                no THREW, content == file text
#   2  read a path that is absent    (absent)              THREW: ENOENT + the path
#   3  read a directory              (dir)                 THREW: EISDIR + the path
#   4  read an empty file            (empty)               no THREW, content == ""
#   5  read with the OBJECT argument ({"path": file})      no THREW, content == file text
#
# All five go through `host:` because the three real call sites cannot drive them:
# code_runner.js:827 and file_converter.js:191 read paths from their own tool
# parameters, and operit_editor.js:2614 reads manifest/package sources it
# discovered itself. None of them picks an absent path, a directory, or an empty
# payload.
#
# THE ONE THAT LIES -- case 5. Case 5 exists because args[0] has two shapes: two
# call sites pass a bare string and operit_editor.js:2614 passes
# `{path, environment}`. A dispatcher that only understands strings sends the whole
# JSON text down as a path, and answers ENOENT -- which looks like an ordinary
# missing file, so cases 1-4 all still pass while operit_editor's three read chains
# (toolpkg packing, duplicate-package cleanup, JS package install) are silently
# broken. For case 5 "it threw" is the FAIL; the PASS is a successful read whose
# content matches the file. The other half of the same trap is checked too: if the
# object were stringified into the path slot, `content` would hold JSON text, so the
# row also rejects a payload that carries the object's own braces.
#
# Case 3 is the shape check beside it: a directory is not a file, so a host that
# tests the isFile side first answers ENOENT for a directory and still looks like it
# threw. EISDIR is the PASS, ENOENT is the FAIL.
#
# Cases 2 and 3 carry their path in the error message, so the path doubles as the
# alignment check; cases 1, 4 and 5 rest on the line count and on their content.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic log,
# because the dispatcher rethrows for this method (the Files family set in
# OperitHostDispatcher.kt -- `throwingMethods`).

# The class namespace is `com.psyche.kelivo` but the applicationId of the merged
# build is `com.psyche.kelivo.fusion` (android/app/build.gradle.kts:10 vs :21). Both
# apps install side by side, the plain one carries no Operit runtime at all, and
# both report versionName 1.2.7 -- so the wrong value here writes the marker into an
# app that can never read it and every case FAILs for a reason that has nothing to
# do with the code under test.
PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

RD="$BASE/rd"
FILE="$RD/file.txt"        # cases 1 and 5
MISSING="$RD/missing.txt"  # case 2, deliberately never created
DIR="$RD/dir"              # case 3
EMPTYF="$RD/empty.txt"     # case 4
EXPECT="$RD/.expect"       # the same bytes, for the independent disk check

# ASCII on purpose: the log line carries the content JSON-escaped, and a fixture
# with newlines or multi-byte characters would make the expected needle a
# statement about escaping rather than about reading. 9 bytes to match its length.
RD_CONTENT=read-case
RD_SIZE=9
META="$BASE/.rd_expect"

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

# Checked before the fixtures go down, because both failure modes below cost a whole
# round: they produce a full table of FAILs that says nothing about the code under
# test. Only a missing package and an unwritable fixture root are fatal; the other
# two warn, since `appops` and `dumpsys` answers vary by build.
preflight() {
    if [ "${SKIP_PREFLIGHT:-0}" = "1" ]; then
        echo "preflight skipped (SKIP_PREFLIGHT=1)"
        return 0
    fi

    hard=0

    installed=$(pm path "$PKG" 2>/dev/null | sed -n '1p' | sed 's/^package://')
    if [ -z "$installed" ]; then
        echo "FAIL $PKG is not installed -- install the APK built from the commit under test" >&2
        hard=1
    else
        echo "ok   installed: $installed"
        ver=$(dumpsys package "$PKG" 2>/dev/null | sed -n 's/.*versionName=\([^ ]*\).*/\1/p' | sed -n '1p')
        last=$(dumpsys package "$PKG" 2>/dev/null | sed -n 's/.*lastUpdateTime=\([0-9-]* [0-9:]*\).*/\1/p' | sed -n '1p')
        echo "     versionName=${ver:-unknown} lastUpdateTime=${last:-unknown}"

        # The decisive check, and the only one that cannot be fooled by names: both
        # apps report versionName 1.2.7, and staged APK file names only say which
        # commit they *claim* to be. The hook under test is the literal `hostselftest`
        # that produces the diag line verify() greps for, so read it out of the
        # installed dex. This check goes away with the hook.
        dex=/data/local/tmp/acceptance_probe.dex
        unzip -p "$installed" 'classes*.dex' > "$dex" 2>/dev/null
        size=$(wc -c < "$dex" 2>/dev/null || echo 0)
        if [ "${size:-0}" -lt 100000 ]; then
            echo "warn cannot read the dex out of the installed apk -- build check skipped"
        elif grep -q hostselftest "$dex"; then
            echo "ok   installed build carries the host: hook"
        elif grep -q operit_selftest "$dex"; then
            echo "FAIL the installed build has the Operit runtime but not the host: hook;" >&2
            echo "     it predates the commit under test. Install the new APK first." >&2
            hard=1
        else
            echo "FAIL the installed build carries no Operit runtime at all -- wrong" >&2
            echo "     package? expected the merged applicationId $PKG" >&2
            hard=1
        fi
        rm -f "$dex"
    fi

    ops=$(appops get "$PKG" MANAGE_EXTERNAL_STORAGE 2>/dev/null)
    case "$ops" in
        *allow*) echo "ok   MANAGE_EXTERNAL_STORAGE: allow" ;;
        *) echo "warn MANAGE_EXTERNAL_STORAGE not confirmed (${ops:-no answer}) -- setup writes $BASE" ;;
    esac

    mkdir -p "$BASE" 2>/dev/null
    if printf probe > "$BASE/.probe" 2>/dev/null; then
        rm -f "$BASE/.probe"
        echo "ok   $BASE is writable"
    else
        echo "FAIL cannot write $BASE" >&2
        hard=1
    fi

    return "$hard"
}

# The marker is one-shot -- `maybeRunSelfTest` reads it and deletes it -- so this
# has to run again before every round. Reusing a previous round's fixtures is the
# quiet way to end up with a table describing a run that never happened.
setup() {
    need_root
    preflight || {
        echo "aborting: fix what preflight flagged above, or set SKIP_PREFLIGHT=1" >&2
        echo "to lay the fixtures down anyway." >&2
        exit 1
    }
    rm -rf "$RD"
    mkdir -p "$RD" "$DIR"
    printf '%s' "$RD_CONTENT" > "$FILE"
    printf '%s' "$RD_CONTENT" > "$EXPECT"
    : > "$EMPTYF"
    # $MISSING is left absent on purpose.

    size_now=$(wc -c < "$FILE" 2>/dev/null | tr -d ' ')
    if [ "$size_now" != "$RD_SIZE" ]; then
        echo "FAIL fixture $FILE is $size_now bytes, expected $RD_SIZE -- aborting" >&2
        echo "     before a round is spent on a fixture that is not what it claims." >&2
        exit 1
    fi
    printf '%s\n%s\n' "$RD_SIZE" "$RD_CONTENT" > "$META"

    mkdir -p "$FILES"
    # Case 5 is the same file through the object shape. The object is the one
    # operit_editor.js:2614 builds: exactly {path, environment}.
    cat > "$MARKER" <<EOF
#call host:Tools.Files.read ["$FILE"]
#call host:Tools.Files.read ["$MISSING"]
#call host:Tools.Files.read ["$DIR"]
#call host:Tools.Files.read ["$EMPTYF"]
#call host:Tools.Files.read [{"path":"$FILE","environment":"android"}]
EOF

    # Where this round starts in the append-only log. Recorded here, acted on in
    # verify -- see the .log_offset note at the top for why the log is not moved
    # aside instead.
    if [ -f "$DIAG" ]; then
        wc -l < "$DIAG" 2>/dev/null | tr -d ' ' > "$BASE/.log_offset"
    else
        echo 0 > "$BASE/.log_offset"
    fi

    echo "fixtures:"
    echo "  $FILE      (cases 1 and 5, '$RD_CONTENT', $RD_SIZE bytes)"
    echo "  $MISSING  (case 2, absent)"
    echo "  $DIR                            (case 3, directory)"
    echo "  $EMPTYF    (case 4, empty)"
    echo "marker:"
    sed 's/^/  /' "$MARKER"
    echo "now restart the app so configure() runs the marker, then: verify"
}

restart() {
    need_root
    am force-stop "$PKG"
    monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "relaunched $PKG -- open the JS tools screen if configure() does not run on launch"
}

verify() {
    need_root
    if [ ! -f "$DIAG" ]; then
        echo "no $DIAG -- the marker never ran" >&2
        exit 1
    fi

    # Only this round's lines count. No sidecar means setup did not run for this
    # round, which is worth saying out loud -- silently reading nothing, or silently
    # reading everything, are both worse than a warning.
    offset=""
    if [ -f "$BASE/.log_offset" ]; then
        offset=$(tr -d ' ' < "$BASE/.log_offset")
    else
        echo "warn no $BASE/.log_offset -- was setup run for this round?" >&2
        echo "     falling back to the whole log." >&2
    fi
    case "${offset:-}" in
        '' | *[!0-9]*) offset=0 ;;
    esac

    if [ ! -f "$META" ]; then
        echo "warn no $META -- was setup run for this round?" >&2
        echo "     falling back to the constant content '$RD_CONTENT'" >&2
    fi

    # The five lines run in order and share one prefix, so the cases are told apart
    # by position: 1 -> case 1, ... 5 -> case 5.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -5)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')

    # The content as it appears inside the escaped JSON string. Matched as a field,
    # not as a whole object: the order inside the payload is org.json's business.
    n_content='content\":\"'"$RD_CONTENT"'\"'
    n_empty='content\":\"\"'
    # The stringified object, i.e. the other half of case 5's trap: if args[0] were
    # pasted into the path slot, `content` would hold this.
    n_brace='{\\\"path'

    c1_msg=missing; c4_msg=missing; c5_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l4" in *THREW*) c4_msg=threw ;; *hostselftest*) c4_msg=payload ;; esac
    case "$l5" in *THREW*) c5_msg=threw ;; *hostselftest*) c5_msg=payload ;; esac

    c1_c=no; case "$l1" in *"$n_content"*) c1_c=yes ;; esac
    c4_c=no; case "$l4" in *"$n_empty"*) c4_c=yes ;; esac
    c5_c=no; case "$l5" in *"$n_content"*) c5_c=yes ;; esac
    c5_brace=no; case "$l5" in *"$n_brace"*) c5_brace=yes ;; esac

    case "$l2" in *ENOENT*"$MISSING"*) c2_msg=ENOENT ;; *) c2_msg=other ;; esac
    case "$l3" in *EISDIR*"$DIR"*) c3_msg=EISDIR ;; *) c3_msg=other ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "5" ]; then
        echo "warn this round wrote $n hostselftest lines, not 5. A missing line shifts" >&2
        echo "     the positions below: the path anchors on 2/3 catch it, and cases 1/4/5" >&2
        echo "     are checked by their content, so a shift shows up there too." >&2
    fi

    # Reading must not modify anything: a host that rewrote or truncated the file on
    # the way past would otherwise still match a content check.
    size_after=$(wc -c < "$FILE" 2>/dev/null | tr -d ' ')
    if [ "$size_after" = "$RD_SIZE" ]; then
        if command -v cmp >/dev/null 2>&1; then
            cmp -s "$FILE" "$EXPECT" && c1_file=intact || c1_file=changed
        else
            c1_file="size-ok"
        fi
    else
        c1_file="changed(${size_after:-gone})"
    fi
    [ -f "$EMPTYF" ] && c4_file=intact || c4_file=gone
    [ -d "$DIR" ] && c3_dir=intact || c3_dir=gone

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_c" = yes ] && [ "$c1_file" = intact ] && c1=PASS
    c2=FAIL; [ "$c2_msg" = ENOENT ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = EISDIR ] && [ "$c3_dir" = intact ] && c3=PASS
    c4=FAIL
    [ "$c4_msg" = payload ] && [ "$c4_c" = yes ] && [ "$c4_file" = intact ] && c4=PASS
    c5=FAIL
    [ "$c5_msg" = payload ] && [ "$c5_c" = yes ] && [ "$c5_brace" = no ] && c5=PASS

    echo "case  args               expected                            actual"
    printf '%-5s %-19s %-35s %s\n' 1 '(file)' 'no THREW, content matches, file intact' \
        "msg=$c1_msg content=$c1_c file=$c1_file -> $c1"
    printf '%-5s %-19s %-35s %s\n' 2 '(absent)' 'THREW: ENOENT + path' \
        "msg=$c2_msg -> $c2"
    printf '%-5s %-19s %-35s %s\n' 3 '(dir)' 'THREW: EISDIR + path (not ENOENT)' \
        "msg=$c3_msg dir=$c3_dir -> $c3"
    printf '%-5s %-19s %-35s %s\n' 4 '(empty)' 'no THREW, content == ""' \
        "msg=$c4_msg content=$c4_c file=$c4_file -> $c4"
    printf '%-5s %-19s %-35s %s\n' 5 '(object arg)' 'no THREW, content matches (not ENOENT)' \
        "msg=$c5_msg content=$c5_c brace=$c5_brace -> $c5"

    echo
    echo "evidence (last 5 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] &&
        [ "$c4" = PASS ] && [ "$c5" = PASS ]; then
        echo "all five PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + content '$RD_CONTENT' + $FILE intact," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg content=$c1_c file=$c1_file" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted ENOENT + $MISSING, got msg=$c2_msg" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted EISDIR + $DIR, got msg=$c3_msg dir=$c3_dir" >&2
    [ "$c3" = FAIL ] && echo "          ENOENT here means the isDirectory check ran second (or not at all)." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted no THREW + content \"\", got msg=$c4_msg content=$c4_c" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted no THREW + content '$RD_CONTENT' (brace=$c5_brace)," >&2
    [ "$c5" = FAIL ] && echo "          got msg=$c5_msg content=$c5_c" >&2
    [ "$c5" = FAIL ] && echo "  case 5 is the one that lies: a dispatcher that only understands a bare" >&2
    [ "$c5" = FAIL ] && echo "          string sends the JSON text down as a path and answers ENOENT, which" >&2
    [ "$c5" = FAIL ] && echo "          looks like an ordinary missing file -- so 'it threw' is the FAIL." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,12p' "$0" ; exit 1 ;;
esac