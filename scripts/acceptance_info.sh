#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_info.sh by `cp` -- the
# Android root shell cannot see /root, where the repo lives. The repo copy is
# authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_info.sh /sdcard/scripts/
#
# usage: sh acceptance_info.sh preflight | setup | restart | verify
#
#   #  case                          args                  expectation
#   1  a regular file                (file)                no THREW, {"fileType":"file"}
#   2  a directory                   (dir)                 no THREW, {"fileType":"directory"}
#   3  missing path                  (absent)              THREW: ENOENT + the path
#
# THE ONE THAT LIES -- case 2. Three wrong implementations all answer case 1
# correctly and only one of them is caught here:
#   * always returns "file"                -> case 1 passes, case 2 fails
#   * returns "folder" (operit_editor.js:2794's local default, never compared
#     against fileType)                    -> case 1 passes, case 2 fails
#   * returns "Directory" (wrong case)     -> case 1 passes, case 2 fails, because
#                                             operit_editor.js:2799 compares
#                                             `=== "directory"` exactly
# So case 2 is where the value domain is actually pinned: "file" alone is not
# evidence that the directory word is right.
#
# The failure of case 3 arrives as a `THREW: ...` line in the diagnostic log, the
# same as the other rounds: the dispatcher rethrows for this method (the Files
# family set in OperitHostDispatcher.kt -- `throwingMethods`). No count is given
# on purpose: the list gains one member per Files method.
#
# The payload is a single JSON object whose only field is `fileType`, exactly
# "file" or "directory". Nothing else is promised and nothing else is checked.
#
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

RD="$BASE/ri"
PLAINFILE="$RD/plain.txt"  # case 1
DIR="$RD/adir"             # case 2
MISSING="$RD/nosuchpath"   # case 3, deliberately never created
EXPECT_F="$RD/.info_expect"   # the file's bytes, for the independent check

# ASCII on purpose: the log line carries the payload JSON-escaped, so a multi-byte
# name would make the expected needle a statement about escaping rather than about
# inspection. 9 bytes, so a truncation would also show up in the byte comparison.
RD_CONTENT=info-case

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
    mkdir -p "$DIR"
    printf '%s' "$RD_CONTENT" > "$PLAINFILE"
    printf '%s' "$RD_CONTENT" > "$EXPECT_F"
    # $MISSING is left absent on purpose.

    # A path that is a file and a path that is a directory, both real, plus one that
    # is not there: the three shapes the value domain is defined against.
    if [ ! -f "$PLAINFILE" ] || [ ! -d "$DIR" ]; then
        echo "FAIL fixtures are not the shapes they claim -- aborting" >&2
        exit 1
    fi
    sz=$(wc -c < "$PLAINFILE" | tr -d ' ')
    if [ "$sz" != "9" ]; then
        echo "FAIL fixture $PLAINFILE is $sz bytes, expected 9 -- aborting" >&2
        exit 1
    fi
    if [ -e "$MISSING" ]; then
        echo "FAIL $MISSING exists -- case 3 would not test ENOENT -- aborting" >&2
        exit 1
    fi

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.info ["$PLAINFILE"]
#call host:Tools.Files.info ["$DIR"]
#call host:Tools.Files.info ["$MISSING"]
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
    echo "  $PLAINFILE   (case 1, a regular file, '$RD_CONTENT')"
    echo "  $DIR (case 2, a directory)"
    echo "  $MISSING  (case 3, absent)"
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

    # The three lines run in order and share one prefix, so the cases are told apart
    # by position: 1 -> case 1, 2 -> case 2, 3 -> case 3.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -3)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')

    # The payload as it appears inside the escaped JSON string. Matched as a field
    # value, not as a whole object: the order inside the payload is org.json's
    # business, and an exact-object match would also fail on a field that is
    # legitimately added later.
    n_file='fileType\":\"file\"'
    n_dir='fileType\":\"directory\"'
    # The traps, as variables on purpose: written inline in a `case` pattern the
    # backslashes are eaten as quote escapes, and the pattern silently never matches.
    n_wrong_folder='fileType\":\"folder\"'
    n_wrong_case='fileType\":\"Directory\"'

    c1_msg=missing; c2_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l2" in *THREW*) c2_msg=threw ;; *hostselftest*) c2_msg=payload ;; esac

    c1_file=no; case "$l1" in *"$n_file"*) c1_file=yes ;; esac
    c2_dir=no; case "$l2" in *"$n_dir"*) c2_dir=yes ;; esac
    # The trap, recorded separately so a FAIL says which trap fired: a payload that
    # carries "folder" is the operit_editor.js:2794 default, not a directory word.
    c2_wrong=no; case "$l2" in *"$n_wrong_folder"*) c2_wrong=folder ;;
        *"$n_wrong_case"*) c2_wrong=case ;; esac

    case "$l3" in *ENOENT*"$MISSING"*) c3_msg=ENOENT ;; *THREW*) c3_msg=other ;; *) c3_msg=payload ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "3" ]; then
        echo "warn this round wrote $n hostselftest lines, not 3. A missing line shifts" >&2
        echo "     the positions below: case 1 and case 2 are checked by their content," >&2
        echo "     and case 3 by its class, so a shift shows up in all three." >&2
    fi

    # Inspection must not modify anything: a host that touched the file on the way
    # past would otherwise still match a by-value check.
    if [ -f "$PLAINFILE" ]; then
        if command -v cmp >/dev/null 2>&1; then
            cmp -s "$PLAINFILE" "$EXPECT_F" && c1_file_state=intact || c1_file_state=changed
        else
            c1_file_state="unverified"
        fi
    else
        c1_file_state=gone
    fi
    [ -d "$DIR" ] && c2_dir_state=intact || c2_dir_state=gone
    [ -e "$MISSING" ] && c3_state=appeared || c3_state=intact

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_file" = yes ] && [ "$c1_file_state" = intact ] && c1=PASS
    c2=FAIL
    [ "$c2_msg" = payload ] && [ "$c2_dir" = yes ] && [ "$c2_dir_state" = intact ] && [ "$c2_wrong" = no ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = ENOENT ] && [ "$c3_state" = intact ] && c3=PASS

    echo "case  args               expected                            actual"
    printf '%-5s %-19s %-35s %s\n' 1 '(a file)' 'no THREW, {"fileType":"file"}' \
        "msg=$c1_msg fileType=$c1_file bytes=$c1_file_state -> $c1"
    printf '%-5s %-19s %-35s %s\n' 2 '(a directory)' 'no THREW, {"fileType":"directory"}' \
        "msg=$c2_msg fileType=$c2_dir wrong=$c2_wrong dir=$c2_dir_state -> $c2"
    printf '%-5s %-19s %-35s %s\n' 3 '(absent)' 'THREW: ENOENT + path' \
        "msg=$c3_msg path=$c3_state -> $c3"

    echo
    echo "evidence (last 3 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ]; then
        echo "all three PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + 'fileType\":\"file\"' + $PLAINFILE intact," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg fileType=$c1_file bytes=$c1_file_state" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted no THREW + 'fileType\":\"directory\"' + $DIR intact," >&2
    [ "$c2" = FAIL ] && echo "          got msg=$c2_msg fileType=$c2_dir wrong=$c2_wrong dir=$c2_dir_state" >&2
    [ "$c2" = FAIL ] && [ "$c2_wrong" = folder ] && echo "          wrong=folder: that is operit_editor.js:2794's local default, and 2799" >&2
    [ "$c2" = FAIL ] && [ "$c2_wrong" = folder ] && echo "          compares === \"directory\", so the toolpkg path would silently break." >&2
    [ "$c2" = FAIL ] && [ "$c2_wrong" = case ] && echo "          wrong=case: 2799 compares === \"directory\" exactly, not case-insensitively." >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted ENOENT + $MISSING, got msg=$c3_msg path=$c3_state" >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,15p' "$0" ; exit 1 ;;
esac