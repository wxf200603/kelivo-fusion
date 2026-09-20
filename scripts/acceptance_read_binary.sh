#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_read_binary.sh by
# `cp` -- the Android root shell cannot see /root, where the repo lives. The repo
# copy is authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_read_binary.sh /sdcard/scripts/
#
# Acceptance driver for `Tools.Files.readBinary` -- four cases, all of them
# through the `host:` prefix.
#
#   usage, as root on the device:
#     sh scripts/acceptance_read_binary.sh preflight  # package / permission / fixture root
#     sh scripts/acceptance_read_binary.sh setup      # preflight + fixtures + marker file
#     sh scripts/acceptance_read_binary.sh restart    # force-stop + relaunch
#     sh scripts/acceptance_read_binary.sh verify     # expectation table, expected vs actual
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
#   #  case                                args         expectation
#   1  read a file that exists              (file)       no THREW, contentBase64 == base64(file), size == byte count
#   2  read a path that does not exist      (absent)     THREW: ENOENT + the path
#   3  read a directory                     (dir)        THREW: EISDIR + the path
#   4  read an empty file                   (empty)      no THREW, contentBase64 == "", size == 0
#
# All four go through `host:` because no package call site can drive 2/3/4:
# the four real call sites (file_converter.js:177, openai_draw.js:202,
# siliconflow_draw.js:283, xai_draw.js:279) each read a file they just produced
# or already asserted with `exists`, so the path is never the test's to choose.
# The day a package exposes a read whose path comes from the outside, each line
# below becomes that package's call and the prefix goes away.
#
# THE ONE THAT LIES -- case 3. A directory is not a file, so a host that checks
# `!isFile` *before* `isDirectory` answers ENOENT for a directory and looks
# almost right: the line still says "it threw", and only the code differs. For
# case 3 EISDIR is the PASS and ENOENT is the FAIL.
#
# Case 4 is the other way round: the empty file must NOT throw. A host that
# treats "no bytes" as a failure fails here even though cases 1-3 pass.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic
# log, because the dispatcher rethrows for this method (the Files family set in
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

# Fixtures. Only case 1 has content to compare against; the other three are about
# the shape of the answer, so they stay as small as they can be.
RB="$BASE/rb"
FILE="$RB/file.txt"      # case 1, content below
EMPTY="$RB/empty.txt"    # case 4, deliberately zero bytes
DIR="$RB/dir"            # case 3
MISSING="$RB/missing.txt" # case 2, deliberately never created

# 7 bytes, and the base64 of them. setup re-derives the base64 from the file when
# the device has `base64`, and falls back to this constant when it does not --
# the fallback is verified against the byte content above, not typed from memory
# twice.
FILE_CONTENT=rb-case
FILE_SIZE=7
FILE_B64_FALLBACK=cmItY2FzZQ==
EXPECT="$BASE/.rb_expect"

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
    rm -rf "$RB"
    mkdir -p "$RB" "$DIR"
    printf '%s' "$FILE_CONTENT" > "$FILE"
    : > "$EMPTY"
    # $MISSING is left absent on purpose.

    # Derive the expected base64 from the file when the device can, so the case
    # compares against the bytes on disk rather than against a constant someone
    # typed. The constant is the fallback, and it is the same value.
    expect_b64=""
    if command -v base64 >/dev/null 2>&1; then
        expect_b64=$(base64 -w0 "$FILE" 2>/dev/null | tr -d '\r\n')
    fi
    expect_src=derived
    if [ -z "$expect_b64" ]; then
        expect_b64="$FILE_B64_FALLBACK"
        expect_src=constant
        echo "warn no usable 'base64' on the device -- comparing against the constant" >&2
        echo "     $FILE_B64_FALLBACK instead of the bytes on disk" >&2
    fi
    size_now=$(wc -c < "$FILE" 2>/dev/null | tr -d ' ')
    if [ "$size_now" != "$FILE_SIZE" ]; then
        echo "FAIL fixture $FILE is $size_now bytes, expected $FILE_SIZE -- aborting" >&2
        echo "     before a round is spent on a fixture that is not what it claims." >&2
        exit 1
    fi
    printf '%s\n%s\n%s\n' "$expect_b64" "$FILE_SIZE" "$expect_src" > "$EXPECT"

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.readBinary ["$FILE"]
#call host:Tools.Files.readBinary ["$MISSING"]
#call host:Tools.Files.readBinary ["$DIR"]
#call host:Tools.Files.readBinary ["$EMPTY"]
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
    echo "  $FILE   (case 1, '$FILE_CONTENT', $FILE_SIZE bytes, base64 $expect_b64 via $expect_src)"
    echo "  $MISSING   (case 2, absent)"
    echo "  $DIR                             (case 3, directory)"
    echo "  $EMPTY   (case 4, empty)"
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

    if [ ! -f "$EXPECT" ]; then
        echo "warn no $EXPECT -- was setup run for this round?" >&2
        echo "     falling back to the constant base64 $FILE_B64_FALLBACK" >&2
        expect_b64=$FILE_B64_FALLBACK
        expect_src=constant
    else
        expect_b64=$(sed -n '1p' "$EXPECT")
        expect_src=$(sed -n '3p' "$EXPECT")
    fi

    # The four lines run in order and share one prefix, so the cases are told
    # apart by position: 1 -> case 1, ... 4 -> case 4.
    out=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest | tail -4)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')

    # The marker text as it appears inside the escaped JSON string. The two fields
    # are matched separately: their order inside the object is org.json's business,
    # not part of the contract, so a host that emits size first must still pass.
    n_b64='contentBase64\":\"'"$expect_b64"'\"'
    n_b64_empty='contentBase64\":\"\"'
    n_size='size\":'"$FILE_SIZE"
    n_size_zero='size\":0'

    # Cases 1 and 4 must not throw, and a line that did not run at all must not
    # pass by being empty, so they start out "missing".
    c1_msg=missing
    c4_msg=missing
    case "$l1" in *THREW*) c1_msg=threw ;; *hostselftest*) c1_msg=payload ;; esac
    case "$l4" in *THREW*) c4_msg=threw ;; *hostselftest*) c4_msg=payload ;; esac

    # 2 and 3 carry the path inside the error message, so the path doubles as the
    # alignment check -- the log is append-only, and a shifted position or a stale
    # line from an earlier round cannot match both the code and the path.
    case "$l2" in *ENOENT*"$MISSING"*) c2_msg=ENOENT ;; *) c2_msg=other ;; esac
    case "$l3" in *EISDIR*"$DIR"*) c3_msg=EISDIR ;; *) c3_msg=other ;; esac

    # Field-level verdicts for 1 and 4, kept apart so a failure says which half
    # was wrong instead of just "the JSON looked odd".
    c1_b64=no
    case "$l1" in *"$n_b64"*) c1_b64=yes ;; esac
    c1_size=no
    case "$l1" in *"$n_size"*) c1_size=yes ;; esac
    c4_b64=no
    case "$l4" in *"$n_b64_empty"*) c4_b64=yes ;; esac
    c4_size=no
    case "$l4" in *"$n_size_zero"*) c4_size=yes ;; esac

    n=$(tail -n +"$((offset + 1))" "$DIAG" | grep -c hostselftest)
    if [ "$n" != "4" ]; then
        echo "warn this round wrote $n hostselftest lines, not 4. A missing line" >&2
        echo "     shifts the positions below: the code+path anchors on 2/3 catch" >&2
        echo "     it, cases 1 and 4 cannot be cross-checked that way." >&2
    fi

    # Reading is not supposed to touch anything: a host that moved or truncated
    # the file on the way past would otherwise still match a payload check.
    size_after=$(wc -c < "$FILE" 2>/dev/null | tr -d ' ')
    [ "$size_after" = "$FILE_SIZE" ] && c1_file=intact || c1_file="changed(${size_after:-gone})"
    [ -f "$EMPTY" ] && c4_file=intact || c4_file=gone
    [ -d "$DIR" ] && c3_dir=intact || c3_dir=gone
    [ -e "$MISSING" ] && c2_path=appeared || c2_path=absent

    c1=FAIL
    [ "$c1_msg" = payload ] && [ "$c1_b64" = yes ] && [ "$c1_size" = yes ] &&
        [ "$c1_file" = intact ] && c1=PASS
    c2=FAIL; [ "$c2_msg" = ENOENT ] && c2=PASS
    c3=FAIL; [ "$c3_msg" = EISDIR ] && [ "$c3_dir" = intact ] && c3=PASS
    c4=FAIL
    [ "$c4_msg" = payload ] && [ "$c4_b64" = yes ] && [ "$c4_size" = yes ] &&
        [ "$c4_file" = intact ] && c4=PASS

    echo "case  args      expected                                          actual"
    printf '%-5s %-9s %-49s %s\n' 1 '(file)' \
        "no THREW, b64+size=$FILE_SIZE, file intact" \
        "msg=$c1_msg b64=$c1_b64 size=$c1_size file=$c1_file -> $c1"
    printf '%-5s %-9s %-49s %s\n' 2 '(absent)' 'THREW: ENOENT + path' \
        "msg=$c2_msg path=$c2_path -> $c2"
    printf '%-5s %-9s %-49s %s\n' 3 '(dir)' 'THREW: EISDIR + path (not ENOENT)' \
        "msg=$c3_msg dir=$c3_dir -> $c3"
    printf '%-5s %-9s %-49s %s\n' 4 '(empty)' 'no THREW, b64="", size=0, file intact' \
        "msg=$c4_msg b64=$c4_b64 size=$c4_size file=$c4_file -> $c4"

    echo
    echo "expectation source: $expect_src (base64 $expect_b64)"
    echo "evidence (last 4 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ]; then
        echo "all four PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted no THREW + contentBase64=$expect_b64 + size=$FILE_SIZE + $FILE intact," >&2
    [ "$c1" = FAIL ] && echo "          got msg=$c1_msg b64=$c1_b64 size=$c1_size file=$c1_file" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted ENOENT + $MISSING, got msg=$c2_msg path=$c2_path" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted EISDIR + $DIR, got msg=$c3_msg dir=$c3_dir" >&2
    [ "$c3" = FAIL ] && echo "  case 3 is the one that lies: a directory is caught by the isFile check" >&2
    [ "$c3" = FAIL ] && echo "          first, so 'it threw' is not enough -- ENOENT here means the" >&2
    [ "$c3" = FAIL ] && echo "          isDirectory check ran second (or not at all)." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted no THREW + contentBase64=\"\" + size=0 + $EMPTY intact," >&2
    [ "$c4" = FAIL ] && echo "          got msg=$c4_msg b64=$c4_b64 size=$c4_size file=$c4_file" >&2
    [ "$c4" = FAIL ] && echo "  case 4 is the other way round: zero bytes is a successful read, so a" >&2
    [ "$c4" = FAIL ] && echo "          throw here is the bug, not the strictness." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,12p' "$0" ; exit 1 ;;
esac
