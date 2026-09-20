#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_copy.sh by `cp` -- the
# Android root shell cannot see /root, where the repo lives. The repo copy is
# authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_copy.sh /sdcard/scripts/
#
# usage: sh acceptance_copy.sh preflight | setup | restart | verify
#
#   #  case                          args                        expectation
#   1  file -> new path              (src, dst, false)           no THREW, {}, dst == src, src unchanged
#   2  directory tree, recursive     (dir, dst, true)            no THREW, {}, tree + per-file bytes
#   3  directory, recursive=false    (dir, dst, false)           THREW: EISDIR + the source path
#   4  source missing                (absent, dst, false)        THREW: ENOENT + the source path
#   5  destination already exists    (src, existing, false)      no THREW, {}, dst replaced by src
#
# THE ONES THAT LIE -- cases 3 and 5.
#
# Case 3: a host that reads `recursive` but ignores it can still answer {} and look
# healthy, because copying the *entries* of a directory happily produces something
# plausible. Only EISDIR proves the flag is honoured, and the expected wording is
# the one fileDelete already uses for this exact shape
# (KelivoWorkspaceHost.kt, fileDelete: "EISDIR: is a directory (recursive=false)").
# The destination must also still not exist afterwards: a half-copy that threw
# after creating it would leave litter behind.
#
# Case 5: a host that refuses to overwrite would throw; a host that *appends*
# would leave a file that is longer than the source and still "exists". So the
# check is not "the file is there" but a byte comparison against the source, plus
# the exact size -- appending 9 bytes to a 7-byte file gives 16, and cmp catches
# any other variant.
#
# The payload of every success is the empty object, so the success needle is the
# literal `-> "{}"`. Nothing reads a field from this result (see the KDoc): three
# call sites discard it and the fourth only tests `!!result`.
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

RD="$BASE/rc"
OUT="$RD/out"
S1="$RD/src1.txt"           # cases 1 and 5
EXPECT_S1="$RD/.expect_src1"   # the bytes of S1, to prove the source survived
TREE="$RD/tree"             # cases 2 and 3
NOSUCH="$RD/nosuch"         # case 4, deliberately never created
D1="$OUT/dst1.txt"          # case 1
TREE_DST="$OUT/tree_dst"    # case 2
TREE_DST2="$OUT/tree_dst_no"   # case 3, must never appear
D4="$OUT/dst4.txt"          # case 4, must never appear
D5="$RD/dst5.txt"           # case 5, exists before the round
EXPECT_D5="$RD/.expect_dst5"

# ASCII on purpose: the log line carries the payload JSON-escaped, so a multi-byte
# name would make the expected needle a statement about escaping rather than about
# copying. 9 bytes so an append or a truncation is visible in the byte comparison.
SRC_CONTENT=copy-case
OLD_CONTENT=old-here

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
    mkdir -p "$OUT" "$TREE/sub"
    printf '%s' "$SRC_CONTENT" > "$S1"
    printf '%s' "$SRC_CONTENT" > "$EXPECT_S1"
    printf 'A' > "$TREE/a.txt"
    printf 'BB' > "$TREE/sub/b.txt"
    printf '%s' "$OLD_CONTENT" > "$D5"
    cp "$D5" "$EXPECT_D5"
    # $NOSUCH is left absent on purpose; OUT exists but nothing inside it does.

    if [ ! -f "$S1" ] || [ ! -d "$TREE/sub" ] || [ ! -f "$TREE/sub/b.txt" ]; then
        echo "FAIL fixtures are not the shapes they claim -- aborting" >&2
        exit 1
    fi
    sz=$(wc -c < "$S1" | tr -d ' ')
    if [ "$sz" != "9" ]; then
        echo "FAIL fixture $S1 is $sz bytes, expected 9 -- aborting" >&2
        exit 1
    fi
    sz=$(wc -c < "$D5" | tr -d ' ')
    if [ "$sz" != "8" ]; then
        echo "FAIL fixture $D5 is $sz bytes, expected 8 -- aborting" >&2
        exit 1
    fi
    if [ -e "$D1" ] || [ -e "$TREE_DST" ] || [ -e "$TREE_DST2" ] || [ -e "$D4" ]; then
        echo "FAIL a destination already exists before the round -- aborting" >&2
        exit 1
    fi
    if [ -e "$NOSUCH" ]; then
        echo "FAIL $NOSUCH exists -- case 4 would not test ENOENT -- aborting" >&2
        exit 1
    fi

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.copy ["$S1","$D1",false]
#call host:Tools.Files.copy ["$TREE","$TREE_DST",true]
#call host:Tools.Files.copy ["$TREE","$TREE_DST2",false]
#call host:Tools.Files.copy ["$NOSUCH","$D4",false]
#call host:Tools.Files.copy ["$S1","$D5",false]
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
    echo "  $S1   (cases 1 and 5, '$SRC_CONTENT', 9 bytes)"
    echo "  $TREE (cases 2 and 3: a.txt + sub/b.txt)"
    echo "  $D5 (case 5, already exists, '$OLD_CONTENT', 8 bytes)"
    echo "  $NOSUCH (case 4, absent)"
    echo "destinations (none of them exist yet):"
    echo "  $D1"
    echo "  $TREE_DST"
    echo "  $TREE_DST2  (case 3 -- must still not exist afterwards)"
    echo "  $D4      (case 4 -- must still not exist afterwards)"
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

cmp_ok() {
    # cmp_ok <a> <b> -> intact | changed | missing
    if [ ! -f "$1" ] || [ ! -f "$2" ]; then
        echo missing
        return
    fi
    if command -v cmp >/dev/null 2>&1; then
        cmp -s "$1" "$2" && echo intact || echo changed
    else
        echo unverified
    fi
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

    # The five lines run in order and share one prefix, so the cases are told apart
    # by position: 1 -> case 1, ... 5 -> case 5.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -5)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')

    # The success payload is the empty object, printed as a JSON string.
    n_ok='-> "{}"'

    c1_msg=missing; c2_msg=missing; c5_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l2" in *THREW*) c2_msg=threw ;; *hostselftest*) c2_msg=payload ;; esac
    case "$l5" in *THREW*) c5_msg=threw ;; *hostselftest*) c5_msg=payload ;; esac

    c1_payload=no; case "$l1" in *"$n_ok"*) c1_payload=yes ;; esac
    c2_payload=no; case "$l2" in *"$n_ok"*) c2_payload=yes ;; esac
    c5_payload=no; case "$l5" in *"$n_ok"*) c5_payload=yes ;; esac

    case "$l3" in *EISDIR*"$TREE"*) c3_msg=EISDIR ;; *ENOENT*) c3_msg=ENOENT ;; *THREW*) c3_msg=other ;; *) c3_msg=payload ;; esac
    case "$l4" in *ENOENT*"$NOSUCH"*) c4_msg=ENOENT ;; *EISDIR*) c4_msg=EISDIR ;; *THREW*) c4_msg=other ;; *) c4_msg=payload ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "5" ]; then
        echo "warn this round wrote $n hostselftest lines, not 5. A missing line shifts" >&2
        echo "     the positions below: every case is checked by its own message or its" >&2
        echo "     own bytes, so a shift shows up in all five." >&2
    fi

    # Independent state checks. Nothing here trusts the log: it reads the disk.
    c1_state=$(cmp_ok "$S1" "$D1")
    c1_src=$(cmp_ok "$S1" "$EXPECT_S1")
    c2_a=$(cmp_ok "$TREE/a.txt" "$TREE_DST/a.txt")
    c2_b=$(cmp_ok "$TREE/sub/b.txt" "$TREE_DST/sub/b.txt")
    [ -d "$TREE_DST" ] && c2_dir=yes || c2_dir=no
    c5_state=$(cmp_ok "$S1" "$D5")
    sz5=$(wc -c < "$D5" 2>/dev/null | tr -d ' ')
    [ -e "$TREE_DST2" ] && c3_litter=yes || c3_litter=no
    [ -e "$D4" ] && c4_litter=yes || c4_litter=no
    c5_old=$(cmp_ok "$OLD_CONTENT" "$D5")

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_payload" = yes ] && [ "$c1_state" = intact ] &&
        [ "$c1_src" = intact ] && c1=PASS
    c2=FAIL
    [ "$c2_msg" = payload ] && [ "$c2_payload" = yes ] && [ "$c2_dir" = yes ] &&
        [ "$c2_a" = intact ] && [ "$c2_b" = intact ] && c2=PASS
    c3=FAIL
    [ "$c3_msg" = EISDIR ] && [ "$c3_litter" = no ] && c3=PASS
    c4=FAIL
    [ "$c4_msg" = ENOENT ] && [ "$c4_litter" = no ] && c4=PASS
    c5=FAIL
    [ "$c5_msg" = payload ] && [ "$c5_payload" = yes ] && [ "$c5_state" = intact ] && c5=PASS

    echo "case  args               expected                            actual"
    printf '%-5s %-19s %-35s %s\n' 1 '(file -> new)' 'no THREW, {}, dst == src, src intact' \
        "msg=$c1_msg payload=$c1_payload dst=$c1_state src=$c1_src -> $c1"
    printf '%-5s %-19s %-35s %s\n' 2 '(dir, recursive)' 'no THREW, {}, tree + per-file bytes' \
        "msg=$c2_msg payload=$c2_payload dir=$c2_dir a=$c2_a sub/b=$c2_b -> $c2"
    printf '%-5s %-19s %-35s %s\n' 3 '(dir, no recurse)' 'THREW: EISDIR + source path, no dst' \
        "msg=$c3_msg dst_created=$c3_litter -> $c3"
    printf '%-5s %-19s %-35s %s\n' 4 '(absent source)' 'THREW: ENOENT + source path, no dst' \
        "msg=$c4_msg dst_created=$c4_litter -> $c4"
    printf '%-5s %-19s %-35s %s\n' 5 '(dst exists)' 'no THREW, {}, dst replaced by src' \
        "msg=$c5_msg payload=$c5_payload dst=$c5_state size=${sz5:-?} -> $c5"

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
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + '-> \"{}\"' + $D1 == $S1 + $S1 intact," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg payload=$c1_payload dst=$c1_state src=$c1_src" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted no THREW + {}, $TREE_DST a directory with both files matching," >&2
    [ "$c2" = FAIL ] && echo "          got msg=$c2_msg payload=$c2_payload dir=$c2_dir a=$c2_a sub/b=$c2_b" >&2
    [ "$c2" = FAIL ] && [ "$c2_dir" = yes ] && [ "$c2_a" = missing ] && echo "          a missing destination file means the walk did not descend." >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted EISDIR + $TREE and no destination, got msg=$c3_msg dst_created=$c3_litter" >&2
    [ "$c3" = FAIL ] && [ "$c3_msg" = payload ] && echo "          a {} here means recursive=false was read and then ignored." >&2
    [ "$c3" = FAIL ] && [ "$c3_litter" = yes ] && echo "          $TREE_DST2 exists: the copy ran before the check, or not at all." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted ENOENT + $NOSUCH, got msg=$c4_msg dst_created=$c4_litter" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted no THREW + '-> \"{}\"' + a byte-identical replacement of $D5," >&2
    [ "$c5" = FAIL ] && echo "          got msg=$c5_msg payload=$c5_payload dst=$c5_state size=${sz5:-?} (source is 9)" >&2
    [ "$c5" = FAIL ] && [ "$c5_old" = intact ] && echo "          the old bytes are still there: nothing was copied." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,15p' "$0" ; exit 1 ;;
esac