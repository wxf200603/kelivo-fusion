#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_write_binary.sh by
# `cp` -- the Android root shell cannot see /root, where the repo lives. The repo
# copy is authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_write_binary.sh /sdcard/scripts/
#
# Acceptance driver for `Tools.Files.writeBinary` -- five cases, all of them
# through the `host:` prefix.
#
#   usage, as root on the device:
#     sh scripts/acceptance_write_binary.sh preflight  # package / permission / fixture root
#     sh scripts/acceptance_write_binary.sh setup      # preflight + fixtures + marker file
#     sh scripts/acceptance_write_binary.sh restart    # force-stop + relaunch
#     sh scripts/acceptance_write_binary.sh verify     # expectation table, expected vs actual
#
#   the target is the merged build: applicationId `com.psyche.kelivo.fusion`, not
#   the class namespace `com.psyche.kelivo`. Override with PKG= if that changes.
#
#   the marker is one-shot: `maybeRunSelfTest` deletes it after reading, so
#   `setup` has to run again before every round.
#
#   the diag log is append-only and owned by the app, so a round's lines are
#   located by the line count `setup` records in $BASE/.log_offset, not by moving
#   the log aside: `mv` only changes the directory entry, so a writer still
#   holding the old inode would keep appending to the .bak while the new log
#   stayed empty -- a probabilistic failure, and an acceptance driver must not
#   introduce one.
#
#   #  case                                 args                     expectation
#   1  write a plain file                    (new path, valid b64)    no THREW, successful:true, bytes match
#   2  write with missing parent dirs        (a/b/c.bin, valid b64)   no THREW, parents created, bytes match
#   3  malformed payload                     (bad path, "not valid!!") THREW: IllegalArgumentException, no file
#   4  path is a directory                   (dir, valid b64)         THREW: EISDIR + path
#   5  empty payload                         (empty path, "")         no THREW, details "0 bytes written", 0-byte file
#
# All five go through `host:` because the three real call sites cannot drive
# them: file_converter.js:170 writes into its own selftest directory,
# minimax_draw.js:528 and openai_draw.js:235 write base64 that came out of an API
# response. None of them chooses a malformed payload, an empty payload or a
# directory as the target.
#
# THE ONE THAT LIES -- case 3. A host that hands the payload to a lenient decoder
# (java.util.Base64's *MIME* decoder ignores everything outside the alphabet)
# succeeds here, reports successful:true, and leaves a file of damaged bytes on
# disk. The failure mode is "no THREW line AND the file exists": for case 3 an
# exception is the PASS, and a written file is the FAIL.
#
# Case 4 is the shape check next to it: a host that checks isFile before
# isDirectory answers ENOENT for a directory and still looks like it threw.
# EISDIR is the PASS, ENOENT is the FAIL.
#
# Cases 3 and 4 are the two error rows, and only case 4 carries its path in the
# message (EISDIR is built from the path; the decoder's IllegalArgumentException
# is about the payload and names no file). So case 3's alignment rests on the
# line count and on its position, which is what the "not 5 lines" warning is for.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic log,
# because the dispatcher rethrows for this method (the Files family set in
# OperitHostDispatcher.kt -- `throwingMethods`).

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

WB="$BASE/wb"
PLAIN="$WB/plain.bin"      # case 1
DEEP="$WB/deep/a/b/deep.bin" # case 2, parents deliberately absent
BAD="$WB/bad.bin"          # case 3, must not exist afterwards
DIR="$WB/dir"              # case 4
EMPTYF="$WB/empty.bin"     # case 5
SRC="$WB/.src"             # the bytes the expected base64 is derived from
EXPECTB="$WB/.expect"      # the same bytes, built by printf, for the byte comparison

# 7 bytes, and the base64 of them. setup re-derives the base64 from $SRC when the
# device has `base64`, and falls back to this constant when it does not -- the
# fallback is checked against the byte content, not typed from memory twice.
WB_CONTENT=wb-case
WB_SIZE=7
WB_B64_FALLBACK=d2ItY2FzZQ==
BAD_PAYLOAD='not valid!!'
META="$BASE/.wb_expect"

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
    rm -rf "$WB"
    mkdir -p "$WB" "$DIR"
    printf '%s' "$WB_CONTENT" > "$SRC"
    printf '%s' "$WB_CONTENT" > "$EXPECTB"
    # $PLAIN, $DEEP, $BAD and $EMPTYF are deliberately absent: every case must
    # create its own file, and case 2 must create parents while doing it.
    # $DEEP's parents are absent too -- that is the point of case 2.

    expect_b64=""
    if command -v base64 >/dev/null 2>&1; then
        expect_b64=$(base64 -w0 "$SRC" 2>/dev/null | tr -d '\r\n')
    fi
    expect_src=derived
    if [ -z "$expect_b64" ]; then
        expect_b64="$WB_B64_FALLBACK"
        expect_src=constant
        echo "warn no usable 'base64' on the device -- using the constant" >&2
        echo "     $WB_B64_FALLBACK, which is the base64 of '$WB_CONTENT'" >&2
    fi
    size_now=$(wc -c < "$SRC" 2>/dev/null | tr -d ' ')
    if [ "$size_now" != "$WB_SIZE" ]; then
        echo "FAIL fixture $SRC is $size_now bytes, expected $WB_SIZE -- aborting" >&2
        echo "     before a round is spent on a fixture that is not what it claims." >&2
        exit 1
    fi
    printf '%s\n%s\n%s\n' "$expect_b64" "$WB_SIZE" "$expect_src" > "$META"

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.writeBinary ["$PLAIN","$expect_b64"]
#call host:Tools.Files.writeBinary ["$DEEP","$expect_b64"]
#call host:Tools.Files.writeBinary ["$BAD","$BAD_PAYLOAD"]
#call host:Tools.Files.writeBinary ["$DIR","$expect_b64"]
#call host:Tools.Files.writeBinary ["$EMPTYF",""]
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
    echo "  $PLAIN          (case 1, absent -> must appear)"
    echo "  $DEEP   (case 2, parents absent -> must be created)"
    echo "  $BAD            (case 3, absent -> must STILL be absent)"
    echo "  $DIR                              (case 4, directory)"
    echo "  $EMPTYF         (case 5, absent -> must appear, 0 bytes)"
    echo "payload: '$WB_CONTENT' = $WB_SIZE bytes = base64 $expect_b64 ($expect_src)"
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

# Same bytes as the fixture that produced the expected base64? `cmp` is the
# strong form; when the device has no cmp we fall back to a size check and say so,
# because a size match is not a byte match.
bytes_match() {
    if command -v cmp >/dev/null 2>&1; then
        cmp -s "$1" "$2" && echo yes || echo no
        return
    fi
    a=$(wc -c < "$1" 2>/dev/null | tr -d ' ')
    b=$(wc -c < "$2" 2>/dev/null | tr -d ' ')
    [ -n "$a" ] && [ "$a" = "$b" ] && echo "sizeonly" || echo no
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

    if [ ! -f "$META" ]; then
        echo "warn no $META -- was setup run for this round?" >&2
        echo "     falling back to the constant base64 $WB_B64_FALLBACK" >&2
        expect_b64=$WB_B64_FALLBACK
        expect_src=constant
    else
        expect_b64=$(sed -n '1p' "$META")
        expect_src=$(sed -n '3p' "$META")
    fi

    # The five lines run in order and share one prefix, so the cases are told
    # apart by position: 1 -> case 1, ... 5 -> case 5.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -5)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')

    # The marker text as it appears inside the escaped JSON string. The two fields
    # are matched separately: their order inside the object is org.json's business,
    # not part of the contract, so a host that emits details first must pass.
    n_ok='successful\":true'
    n_n='details\":\"'"$WB_SIZE"' bytes written\"'
    n_zero='details\":\"0 bytes written\"'

    # Cases 1/2/5 must not throw, and a line that did not run at all must not pass
    # by being empty, so they start out "missing".
    c1_msg=missing; c2_msg=missing; c5_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l2" in *THREW*) c2_msg=threw ;; *hostselftest*) c2_msg=payload ;; esac
    case "$l5" in *THREW*) c5_msg=threw ;; *hostselftest*) c5_msg=payload ;; esac

    c1_ok=no; case "$l1" in *"$n_ok"*) c1_ok=yes ;; esac
    c1_n=no;  case "$l1" in *"$n_n"*)  c1_n=yes ;; esac
    c2_ok=no; case "$l2" in *"$n_ok"*) c2_ok=yes ;; esac
    c2_n=no;  case "$l2" in *"$n_n"*)  c2_n=yes ;; esac
    c5_ok=no; case "$l5" in *"$n_ok"*) c5_ok=yes ;; esac
    c5_n=no;  case "$l5" in *"$n_zero"*) c5_n=yes ;; esac

    # Case 3: the code, and -- the point of the case -- that no file appeared.
    case "$l3" in *IllegalArgumentException*) c3_msg=IAE ;; *) c3_msg=other ;; esac
    # Case 4: the code and the path (EISDIR is built from the path).
    case "$l4" in *EISDIR*"$DIR"*) c4_msg=EISDIR ;; *) c4_msg=other ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "5" ]; then
        echo "warn this round wrote $n hostselftest lines, not 5. A missing line" >&2
        echo "     shifts the positions below: case 4's path anchor catches it, cases" >&2
        echo "     1/2/3/5 cannot be cross-checked that way." >&2
    fi

    c1_bytes=no
    [ -f "$PLAIN" ] && c1_bytes=$(bytes_match "$PLAIN" "$EXPECTB")
    c2_bytes=no
    if [ -f "$DEEP" ]; then
        c2_bytes=$(bytes_match "$DEEP" "$EXPECTB")
        [ -d "$WB/deep/a/b" ] && c2_parents=yes || c2_parents=no
    else
        c2_parents=no
    fi
    [ -f "$BAD" ] && c3_file=appeared || c3_file=absent
    [ -d "$DIR" ] && c4_dir=intact || c4_dir=gone
    if [ -f "$EMPTYF" ]; then
        sz=$(wc -c < "$EMPTYF" 2>/dev/null | tr -d ' ')
        [ "$sz" = "0" ] && c5_file="0bytes" || c5_file="${sz}bytes"
    else
        c5_file=absent
    fi

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_ok" = yes ] && [ "$c1_n" = yes ] &&
        [ "$c1_bytes" = yes ] && c1=PASS
    c2=FAIL
    [ "$c2_msg" = payload ] && [ "$c2_ok" = yes ] && [ "$c2_n" = yes ] &&
        [ "$c2_parents" = yes ] && [ "$c2_bytes" = yes ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = IAE ] && [ "$c3_file" = absent ] && c3=PASS
    c4=FAIL; [ "$c4_msg" = EISDIR ] && [ "$c4_dir" = intact ] && c4=PASS
    c5=FAIL
    [ "$c5_msg" = payload ] && [ "$c5_ok" = yes ] && [ "$c5_n" = yes ] &&
        [ "$c5_file" = 0bytes ] && c5=PASS

    echo "case  args               expected                                     actual"
    printf '%-5s %-19s %-44s %s\n' 1 '(file, valid b64)' 'no THREW, successful, bytes match' \
        "msg=$c1_msg ok=$c1_ok n=$c1_n bytes=$c1_bytes -> $c1"
    printf '%-5s %-19s %-44s %s\n' 2 '(deep path)' 'no THREW, parents created, bytes match' \
        "msg=$c2_msg ok=$c2_ok n=$c2_n parents=$c2_parents bytes=$c2_bytes -> $c2"
    printf '%-5s %-19s %-44s %s\n' 3 '(malformed b64)' 'THREW IllegalArgumentException, no file' \
        "msg=$c3_msg file=$c3_file -> $c3"
    printf '%-5s %-19s %-44s %s\n' 4 '(dir)' 'THREW EISDIR + path' \
        "msg=$c4_msg dir=$c4_dir -> $c4"
    printf '%-5s %-19s %-44s %s\n' 5 '(empty b64)' 'no THREW, "0 bytes written", 0-byte file' \
        "msg=$c5_msg ok=$c5_ok n=$c5_n file=$c5_file -> $c5"

    echo
    echo "payload source: $expect_src (base64 $expect_b64)"
    echo "evidence (last 5 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] &&
        [ "$c4" = PASS ] && [ "$c5" = PASS ]; then
        echo "all five PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + successful + details + $PLAIN byte-equal," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg ok=$c1_ok n=$c1_n bytes=$c1_bytes" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted no THREW + parents created + $DEEP byte-equal," >&2
    [ "$c2" = FAIL ] && echo "          got msg=$c2_msg parents=$c2_parents bytes=$c2_bytes" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted IllegalArgumentException + $BAD absent, got msg=$c3_msg file=$c3_file" >&2
    [ "$c3" = FAIL ] && echo "  case 3 is the one that lies: a lenient decoder reports success and" >&2
    [ "$c3" = FAIL ] && echo "          leaves damaged bytes on disk, so a written file is the FAIL" >&2
    [ "$c3" = FAIL ] && echo "          and the exception is the PASS." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted EISDIR + $DIR, got msg=$c4_msg dir=$c4_dir" >&2
    [ "$c4" = FAIL ] && echo "          a directory is not a file, so ENOENT here means the isDirectory" >&2
    [ "$c4" = FAIL ] && echo "          check ran second (or not at all)." >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted no THREW + \"0 bytes written\" + a 0-byte file, got" >&2
    [ "$c5" = FAIL ] && echo "          msg=$c5_msg ok=$c5_ok n=$c5_n file=$c5_file; zero bytes is not a failure." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,12p' "$0" ; exit 1 ;;
esac