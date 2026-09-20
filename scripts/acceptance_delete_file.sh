#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_delete_file.sh by
# `cp` -- the Android root shell cannot see /root, where the repo lives. The repo
# copy is authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_delete_file.sh /sdcard/scripts/
#
# Acceptance driver for `Tools.Files.deleteFile` -- five cases, all of them
# through the `host:` prefix.
#
#   usage, as root on the device:
#     sh scripts/acceptance_delete_file.sh preflight  # package / permission / fixture root
#     sh scripts/acceptance_delete_file.sh setup      # preflight + fixtures + marker file
#     sh scripts/acceptance_delete_file.sh restart    # force-stop + relaunch
#     sh scripts/acceptance_delete_file.sh verify     # expectation table, expected vs actual
#
#   the target is the merged build: applicationId `com.psyche.kelivo.fusion`, not
#   the class namespace `com.psyche.kelivo`. Override with PKG= if that changes.
#
#   setup runs preflight first and aborts on a missing package or an unwritable
#   fixture root, so a round cannot end in a table of FAILs that says nothing
#   about the code under test. SKIP_PREFLIGHT=1 lays the fixtures down anyway.
#
#   the marker is one-shot: `maybeRunSelfTest` deletes it after reading, so
#   `setup` has to run again before every round.
#
#   the diag log is append-only and owned by the app, so a round's lines are
#   located by the line count `setup` records in $BASE/.log_offset, not by moving
#   the log aside: `mv` only changes the directory entry, so a writer still
#   holding the old inode would keep appending to the .bak while the new log
#   stayed empty -- a probabilistic failure, and an acceptance driver must not
#   introduce one. Re-runs stay exact however many thousands of lines pile up.
#
#   #  case                                  args             expectation
#   1  delete a plain file                    (file, false)    no THREW, file gone
#   2  non-empty dir, recursive=false         (dir, false)     THREW: EISDIR, dir intact
#   3  empty dir, recursive=false             (dir, false)     THREW: EISDIR, dir intact
#   4  delete a path that does not exist      (absent, false)  THREW: ENOENT
#   5  recursive delete of a non-empty dir    (dir, true)      no THREW, tree gone
#
# All five go through `host:` because no package call site can drive any of
# them. Nothing in the 31 packages passes `recursive=false` or chooses its own
# path: github.js:799 and file_converter.js:211 hardcode `true`, openai_draw.js:208
# deletes an internal tmp, operit_editor.js:2599/2716 hide the path inside a
# cleanup helper, extended_file_tools has no delete tool at all, and
# github:delete_file deletes a remote. So EISDIR, ENOENT and the two success
# cases were all equally unreachable before `host:` landed (worktree commit
# 7e2fcf3) -- an earlier note in the handoff claiming cases 1 and 5 "go through
# the normal channel" measured the call sites wrong.
#
# This is a statement about the package surface, not a temporary concession, and
# the way out is mechanical: when a package does ship a delete that takes its
# arguments from the outside, each line below becomes that package's call and the
# prefix goes away. The cases themselves do not change.
#
# THE ONE THAT LIES -- case 3. `File.delete()` returns true for an empty
# directory. A host that checks `isDirectory && !recursive` *after* deleting
# therefore reports success and the directory disappears without a word. The
# failure mode for case 3 is "no THREW line AND the directory is gone". An
# exception here is the PASS, not the failure -- do not read "it threw" as a
# broken run.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic
# log: this method is on the host's throw list, so the dispatcher rethrows
# rather than answering with an error object. The list is not named here on
# purpose -- it gains one member per Files method, and its identifier has
# already been renamed once.

# The class namespace is `com.psyche.kelivo` but the applicationId of the merged
# build is `com.psyche.kelivo.fusion` (android/app/build.gradle.kts:10 vs :21).
# Both apps install side by side, the plain one carries no Operit runtime at all,
# and both report versionName 1.2.7 -- so the wrong value here writes the marker
# into an app that can never read it and every case FAILs for a reason that has
# nothing to do with the code under test.
PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

# Fixtures, one per case and each on its own path: cases 1 and 5 both expect
# success, so they must not be able to disturb 2/3/4.
PLAIN="$BASE/plain/file.txt"       # case 1
NONEMPTY="$BASE/nonempty"          # case 2
EMPTY="$BASE/empty"                # case 3
MISSING="$BASE/missing"            # case 4, deliberately never created
REC="$BASE/rec"                    # case 5

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

# Checked before the fixtures go down, because both failure modes below cost a
# whole round: they produce a full table of FAILs that says nothing about the
# code under test. Only a missing package and an unwritable fixture root are
# fatal; the other two warn, since `appops` and `dumpsys` answers vary by build.
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
        newest=$(ls -t /sdcard/Download/kelivo-fusion-*.apk 2>/dev/null | sed -n '1p')
        if [ -n "$newest" ]; then
            echo "     newest staged: $(basename "$newest") ($(date -r "$newest" '+%Y-%m-%d %H:%M' 2>/dev/null))"
        else
            echo "warn no /sdcard/Download/kelivo-fusion-*.apk staged to compare against"
        fi

        # The decisive check, and the only one that cannot be fooled by names:
        # both apps report versionName 1.2.7, and the staged APK file names only
        # say which commit they *claim* to be. The hook under test is the literal
        # `hostselftest` that produces the diag line verify() greps for, so read
        # it out of the installed dex. This check goes away with the hook.
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
    rm -rf "$BASE"
    mkdir -p "$(dirname "$PLAIN")" "$NONEMPTY/sub" "$EMPTY" "$REC/sub"
    echo case1 > "$PLAIN"
    echo case2 > "$NONEMPTY/sub/file"
    echo case5 > "$REC/sub/file"
    # $MISSING is left absent on purpose.

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.deleteFile ["$PLAIN",false]
#call host:Tools.Files.deleteFile ["$NONEMPTY",false]
#call host:Tools.Files.deleteFile ["$EMPTY",false]
#call host:Tools.Files.deleteFile ["$MISSING",false]
#call host:Tools.Files.deleteFile ["$REC",true]
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
    echo "  $PLAIN                (case 1)"
    echo "  $NONEMPTY/sub/file    (case 2)"
    echo "  $EMPTY                (case 3, empty)"
    echo "  $MISSING              (case 4, absent)"
    echo "  $REC/sub/file         (case 5)"
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
    # round, which is worth saying out loud -- silently reading nothing, or
    # silently reading everything, are both worse than a warning.
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

    # The five lines run in order and share one prefix, so the cases are told
    # apart by position: 1 -> case 1, ... 5 -> case 5.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -5)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')

    # "no THREW" only means something for a line that ran at all, so cases 1 and
    # 5 start out missing: an absent line must not pass by being empty.
    c1_msg=missing
    c5_msg=missing
    case "$l1" in *hostselftest*) c1_msg=ok ;; esac
    case "$l1" in *THREW*) c1_msg=threw ;; esac
    case "$l5" in *hostselftest*) c5_msg=ok ;; esac
    case "$l5" in *THREW*) c5_msg=threw ;; esac

    # 2/3/4 carry their path inside the error message, so the path doubles as the
    # alignment check -- the log is append-only, and a shifted position or a
    # stale line from an earlier round cannot match both marker and path.
    # Cases 1 and 5 return nothing to match on, so they rest on the five lines
    # being the last five the log holds.
    case "$l2" in *EISDIR*"$NONEMPTY"*) c2_msg=EISDIR ;; *) c2_msg=other ;; esac
    case "$l3" in *EISDIR*"$EMPTY"*) c3_msg=EISDIR ;; *) c3_msg=other ;; esac
    case "$l4" in *ENOENT*"$MISSING"*) c4_msg=ENOENT ;; *) c4_msg=other ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "5" ]; then
        echo "warn this round wrote $n hostselftest lines, not 5. A missing line" >&2
        echo "     shifts the positions below: the path anchors on 2/3/4 catch it," >&2
        echo "     cases 1 and 5 cannot be cross-checked that way." >&2
    fi

    [ -e "$PLAIN" ] && c1_path=present || c1_path=gone
    [ -d "$NONEMPTY" ] && c2_dir=intact || c2_dir=gone
    [ -d "$EMPTY" ] && c3_dir=intact || c3_dir=gone
    [ -e "$MISSING" ] && c4_path=appeared || c4_path=absent
    [ -d "$REC" ] && c5_dir=present || c5_dir=gone

    c1=FAIL; [ "$c1_msg" = ok ] && [ "$c1_path" = gone ] && c1=PASS
    c2=FAIL; [ "$c2_msg" = EISDIR ] && [ "$c2_dir" = intact ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = EISDIR ] && [ "$c3_dir" = intact ] && c3=PASS
    c4=FAIL; [ "$c4_msg" = ENOENT ] && [ "$c4_path" = absent ] && c4=PASS
    c5=FAIL; [ "$c5_msg" = ok ] && [ "$c5_dir" = gone ] && c5=PASS

    echo "case  args            expected                    actual"
    printf '%-5s %-15s %-27s %s\n' 1 '(file, false)' 'no THREW, file gone' \
        "msg=$c1_msg path=$c1_path -> $c1"
    printf '%-5s %-15s %-27s %s\n' 2 '(dir, false)' 'THREW: EISDIR, dir intact' \
        "msg=$c2_msg dir=$c2_dir -> $c2"
    printf '%-5s %-15s %-27s %s\n' 3 '(dir, false)' 'THREW: EISDIR, dir intact' \
        "msg=$c3_msg dir=$c3_dir -> $c3"
    printf '%-5s %-15s %-27s %s\n' 4 '(absent, false)' 'THREW: ENOENT' \
        "msg=$c4_msg path=$c4_path -> $c4"
    printf '%-5s %-15s %-27s %s\n' 5 '(dir, true)' 'no THREW, tree gone' \
        "msg=$c5_msg dir=$c5_dir -> $c5"

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
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + $PLAIN gone, got msg=$c1_msg path=$c1_path" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted EISDIR + $NONEMPTY intact, got msg=$c2_msg dir=$c2_dir" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted EISDIR + $EMPTY intact, got msg=$c3_msg dir=$c3_dir" >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted ENOENT, got msg=$c4_msg path=$c4_path" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted no THREW + $REC gone, got msg=$c5_msg dir=$c5_dir" >&2
    if [ "$c3" = FAIL ]; then
        echo "case 3 is the one that lies: 'it threw' is the PASS. A silent run" >&2
        echo "means File.delete() removed the empty dir while the check for" >&2
        echo "isDirectory && !recursive ran too late to notice." >&2
    fi
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,12p' "$0" ; exit 1 ;;
esac
