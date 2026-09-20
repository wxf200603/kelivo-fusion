#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_list.sh by `cp` -- the
# Android root shell cannot see /root, where the repo lives. The repo copy is
# authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_list.sh /sdcard/scripts/
#
# usage: sh acceptance_list.sh preflight | setup | restart | verify
#
#   #  case                          args                  expectation
#   1  normal directory              (dir)                 no THREW, entries with both fixture names,
#                                                         isDirectory true for the subdirectory
#   2  empty directory               (dir)                 no THREW, {"entries":[]}
#   3  a regular file                (file)                THREW: ENOTDIR + the path
#   4  missing path                  (absent)              THREW: ENOENT + the path
#
# THE ONE THAT LIES -- case 3. Three different wrong implementations each answer
# case 3, and two of them look perfectly ordinary:
#   * no directory check at all            -> ENOENT  (a missing file; looks normal)
#   * existence check only, null -> EIO    -> EIO     (a refusal; looks normal)
#   * checks in the wrong order            -> ENOENT
# Only ENOTDIR proves the new check exists AND runs after existence. So for case 3,
# "it threw" is not the PASS: the message has to name the right class.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic log,
# the same as the read round: the dispatcher rethrows for this method (the Files
# family set in OperitHostDispatcher.kt -- `throwingMethods`).
#
# It is `list`, not `listFiles`: the payload is a single JSON object with one array
# named `entries`, and an entry is {name, isDirectory}. Nothing else is promised.
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

RD="$BASE/rl"
NORMAL="$RD/listing"       # case 1
EMPTYDIR="$RD/emptydir"    # case 2
PLAINFILE="$RD/plain.txt"  # case 3, a regular file
MISSING="$RD/missingdir"   # case 4, deliberately never created
EXPECT_L="$RD/.list_expect"   # sorted names of the normal dir, for the independent check
AFTER_L="$RD/.list_after"

# ASCII names on purpose: the log line carries the payload JSON-escaped, so a
# multi-byte name would make the expected needle a statement about escaping rather
# than about listing. The subdirectory is what makes isDirectory observable.
F1=alpha.txt
F2=beta

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
    mkdir -p "$NORMAL" "$EMPTYDIR"
    printf 'a' > "$NORMAL/$F1"
    mkdir -p "$NORMAL/$F2"
    printf 'plain' > "$PLAINFILE"
    # $MISSING is left absent on purpose.

    # The names recorded now, compared byte-for-byte after the run: a listing that
    # moved or created an entry would otherwise still match a by-name check.
    ls -1 "$NORMAL" | sort > "$EXPECT_L"
    n_expect=$(wc -l < "$EXPECT_L" | tr -d ' ')
    if [ "$n_expect" != "2" ]; then
        echo "FAIL fixture $NORMAL lists $n_expect names, expected 2 -- aborting" >&2
        echo "     before a round is spent on a fixture that is not what it claims." >&2
        exit 1
    fi
    if [ ! -f "$PLAINFILE" ] || [ ! -d "$EMPTYDIR" ]; then
        echo "FAIL fixtures are not the shapes they claim -- aborting" >&2
        exit 1
    fi
    if [ -e "$MISSING" ]; then
        echo "FAIL $MISSING exists -- case 4 would not test ENOENT -- aborting" >&2
        exit 1
    fi

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.list ["$NORMAL"]
#call host:Tools.Files.list ["$EMPTYDIR"]
#call host:Tools.Files.list ["$PLAINFILE"]
#call host:Tools.Files.list ["$MISSING"]
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
    echo "  $NORMAL   (case 1: '$F1' + subdir '$F2')"
    echo "  $EMPTYDIR (case 2, empty)"
    echo "  $PLAINFILE (case 3, a regular file)"
    echo "  $MISSING (case 4, absent)"
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

    # The four lines run in order and share one prefix, so the cases are told apart
    # by position: 1 -> case 1, ... 4 -> case 4.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -4)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')

    # The payload as it appears inside the escaped JSON string: field, not whole
    # object, because the order inside the payload is org.json's business.
    n_entries='entries\":['
    n_empty='entries\":[]'
    n_a='name\":\"'"$F1"'\"'
    n_b='name\":\"'"$F2"'\"'
    n_dirtrue='isDirectory\":true'

    c1_msg=missing; c2_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l2" in *THREW*) c2_msg=threw ;; *hostselftest*) c2_msg=payload ;; esac

    c1_entries=no; case "$l1" in *"$n_entries"*) c1_entries=yes ;; esac
    c1_a=no; case "$l1" in *"$n_a"*) c1_a=yes ;; esac
    c1_b=no; case "$l1" in *"$n_b"*) c1_b=yes ;; esac
    c1_dt=no; case "$l1" in *"$n_dirtrue"*) c1_dt=yes ;; esac

    c2_empty=no; case "$l2" in *"$n_empty"*) c2_empty=yes ;; esac

    case "$l3" in *ENOTDIR*"$PLAINFILE"*) c3_msg=ENOTDIR ;; *ENOENT*) c3_msg=ENOENT ;; *THREW*) c3_msg=other ;; *) c3_msg=payload ;; esac
    case "$l4" in *ENOENT*"$MISSING"*) c4_msg=ENOENT ;; *ENOTDIR*) c4_msg=ENOTDIR ;; *THREW*) c4_msg=other ;; *) c4_msg=payload ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "4" ]; then
        echo "warn this round wrote $n hostselftest lines, not 4. A missing line shifts" >&2
        echo "     the positions below: cases 1/2 are checked by their content, and the" >&2
        echo "     two failures by their class, so a shift shows up in all four." >&2
    fi

    # Listing must not modify anything: a host that created, moved or removed an
    # entry on the way past would otherwise still match a by-name check.
    if [ -d "$NORMAL" ]; then
        ls -1 "$NORMAL" | sort > "$AFTER_L" 2>/dev/null
        if command -v cmp >/dev/null 2>&1; then
            cmp -s "$AFTER_L" "$EXPECT_L" && c1_file=intact || c1_file=changed
        else
            c1_file="unverified"
        fi
    else
        c1_file=gone
    fi
    if [ -d "$EMPTYDIR" ]; then
        ne=$(ls -1 "$EMPTYDIR" 2>/dev/null | wc -l | tr -d ' ')
        [ "$ne" = "0" ] && c2_file=intact || c2_file="changed($ne)"
    else
        c2_file=gone
    fi
    [ -f "$PLAINFILE" ] && c3_file=intact || c3_file=gone
    [ -e "$MISSING" ] && c4_file=appeared || c4_file=intact

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_entries" = yes ] && [ "$c1_a" = yes ] &&
        [ "$c1_b" = yes ] && [ "$c1_dt" = yes ] && [ "$c1_file" = intact ] && c1=PASS
    c2=FAIL
    [ "$c2_msg" = payload ] && [ "$c2_empty" = yes ] && [ "$c2_file" = intact ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = ENOTDIR ] && [ "$c3_file" = intact ] && c3=PASS
    c4=FAIL; [ "$c4_msg" = ENOENT ] && [ "$c4_file" = intact ] && c4=PASS

    echo "case  args               expected                            actual"
    printf '%-5s %-19s %-35s %s\n' 1 '(dir)' 'no THREW, entries + both names + isDirectory:true' \
        "msg=$c1_msg entries=$c1_entries $F1=$c1_a $F2=$c1_b dirtrue=$c1_dt dir=$c1_file -> $c1"
    printf '%-5s %-19s %-35s %s\n' 2 '(empty dir)' 'no THREW, entries == []' \
        "msg=$c2_msg empty=$c2_empty dir=$c2_file -> $c2"
    printf '%-5s %-19s %-35s %s\n' 3 '(a file)' 'THREW: ENOTDIR + path (not ENOENT, not EIO)' \
        "msg=$c3_msg file=$c3_file -> $c3"
    printf '%-5s %-19s %-35s %s\n' 4 '(absent)' 'THREW: ENOENT + path' \
        "msg=$c4_msg -> $c4"

    echo
    echo "evidence (last 4 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ]; then
        echo "all four PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + entries + '$F1' + '$F2' + isDirectory:true," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg entries=$c1_entries $F1=$c1_a $F2=$c1_b dirtrue=$c1_dt dir=$c1_file" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted no THREW + 'entries\":[]', got msg=$c2_msg empty=$c2_empty dir=$c2_file" >&2
    [ "$c2" = FAIL ] && echo "          a THREW here means an empty directory was reported as a failure;" >&2
    [ "$c2" = FAIL ] && echo "          an empty payload field means entries came back as something else." >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted ENOTDIR + $PLAINFILE, got msg=$c3_msg" >&2
    [ "$c3" = FAIL ] && echo "          ENOENT here means the isDirectory check is missing or ran first;" >&2
    [ "$c3" = FAIL ] && echo "          EIO means existence was checked but the directory test was not." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted ENOENT + $MISSING, got msg=$c4_msg" >&2
    [ "$c4" = FAIL ] && echo "          ENOTDIR here means the two checks are in the wrong order." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,14p' "$0" ; exit 1 ;;
esac