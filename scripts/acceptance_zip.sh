#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_zip.sh by `cp` -- the Android
# root shell cannot see /root, where the repo lives. The repo copy is authoritative, so
# after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_zip.sh /sdcard/scripts/
#
# usage: sh acceptance_zip.sh preflight | setup | restart | verify
#
#   #  case                          call                          expectation
#   1  directory, flag=false         zip(tree, t1, false)          entries RELATIVE to tree; bytes round-trip
#   2  directory, flag=true          zip(tree, t2, true)           entries prefixed "tree/"
#   3  directory, flag OMITTED       zip(tree, t3)                 same as 2 -- the declared default is true
#   4  file source                  zip(one.txt, t4, false)        one entry, the file's own name; bytes round-trip
#   5  empty directory, flag=true    zip(voidroot, t5, true)       exactly one entry, "voidroot/"
#   6  destination inside source     zip(tree2, tree2/inside.zip)  THREW IllegalArgumentException; nothing written
#   7  destination parent missing    zip(tree, out/deep/nested/t7) parents created; archive written
#   8  source missing                zip(nosuch, t8, false)        THREW ENOENT; no archive
#   9  flag left in the env slot     zip(tree, t9, false@[2])      entries PREFIXED -- the default answers, not the flag
#
# WHY THE MARKER'S ARGUMENT POSITIONS ARE PART OF THE ACCEPTANCE
#
# The marker line reaches NativeInterface.__call verbatim (OperitJsRuntime.kt:373-413), so the
# positions in it have to match the JS wrapper's arguments, not the dispatcher's readable ones.
# extended_file_tools.js:108 sends (source, destination, environment, include_root_directory)
# and OperitHostDispatcher.kt:215 reads index 3. A marker with only three elements therefore puts
# the boolean in the environment slot, leaves index 3 absent, and isNull(3) answers with the
# DEFAULT true. The first run of this driver did exactly that -- it copied the shape the copy
# round uses, where the boolean really is at index 2 (extended_file_tools.js:100, dispatcher:183)
# -- and cases 1 and 7 failed while cases 2 and 5 passed for the wrong reason: with the boolean
# in the wrong slot they were the same test as case 3, so their PASS said nothing about an
# explicit true. Case 9 keeps that mistake on purpose and expects the PREFIXED archive, so a
# future three-element marker fails loudly instead of quietly measuring the default. Case 3 keeps
# its two-element shape on purpose too: it is the most thorough omission -- not even the
# environment is sent -- which is a different shape from case 9 and worth a case of its own.
#
# WHY THE MARKER'S ARGUMENT POSITIONS ARE PART OF THE ACCEPTANCE
#
# The marker text reaches __call verbatim (OperitJsRuntime.kt:373-413) and the dispatcher parses
# it with JSONArray(...), so a marker only asks the question its case means if its elements sit
# at the same indices the package uses. The wrappers spell the positions out:
#
#   move (source, destination, environment)                     extended_file_tools.js:96
#   copy (source, destination, recursive, srcEnv, dstEnv)        :100
#   zip  (source, destination, environment, include_root_dir)    :108
#
# So `include_root_directory` sits at index 3 -- one slot LATER than copy's `recursive` at
# index 2 -- and the first version of this driver shipped the copy-shaped three-element marker,
# which put `false` in the environment slot. The dispatcher, correctly reading index 3, then saw
# an absent element and answered with the documented default: every archive came out prefixed,
# cases 1 and 7 failed, and cases 2 and 5 passed *through the default* rather than by testing an
# explicit true (case 2 and case 3 were the same test -- that is the part no PASS revealed).
# That run is preserved at /sdcard/verify_out_zip_marker_argv_FAIL.txt: t1, t2, t3 and t7 were
# byte-identical, five prefixed entries each.
#
# Hence: every line carrying a boolean writes the environment slot out as an explicit null; case
# 3 keeps the shortest shape (nothing at index 3 at all, which is what the platform produces
# when a caller leaves the parameter out); and case 9 keeps the old WRONG shape on purpose, so
# the layout is a tested fact rather than a comment. A rehearsal with fabricated log lines
# cannot see any of this: it validates what verify() decides about evidence, and the argument
# positions never reach it. argv layout, device permissions and the device's filesystem
# semantics are the three things only a device round can measure.
#
# WHY THE INSTRUMENTS ARE PART OF THE ACCEPTANCE
#
# Case 3 is the round's decisive one. `include_root_directory` is the only boolean in this
# family whose declared default is true (extended_file_tools.js:59), and the dispatcher must
# therefore read it with `isNull(3) || optBoolean(3)` -- org.json answers false for a missing
# argument, which would silently invert the documented behaviour. A marker line with only two
# arguments is what makes that line observable: if the dispatcher used bare optBoolean, case 3
# would produce relative entries and case 2 would still pass. Neither case alone is evidence.
#
# Cases 1 and 5 pin the two halves of the entry-name contract: that flag=false is relative to
# the source (which is what the ToolPkg packer needs -- operit_editor.js:2870/2873-2877/2810-2819)
# and that an empty directory is written as its own entry, because otherwise it simply would not
# exist after unzipping.
#
# THE ENTRY INSTRUMENT, PROBED BEFORE IT WAS USED
#
# The device's unzip is /system/bin/unzip -> ziptool. It lists entries with -l (including an
# empty directory entry, which is how case 5 is observable), extracts a single entry with -p,
# and does NOT support -Z, so there is no zipinfo-style listing to parse. It counts its entries
# in the summary line as "N files" for every N except 1, which it calls "1 file": a count
# parser that knows only the plural answers "?" and makes cases 4 and 5 -- the two single-entry
# shapes -- unsatisfiable. Entry names are therefore matched at end-of-line
# ("[[:space:]]<name>$"), which is what keeps "a.txt" from matching the line for "sub/a.txt".
# The parser is exercised by the very archives under test: if the host wrote something the
# device cannot read, these cases fail, which is the correct answer rather than an instrument
# problem.
#
# Byte checks never compare against the fixture in place: they extract the entry with -p and
# cmp it against a copy recorded at setup.
PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

RD="$BASE/zp"
OUT="$RD/out"
TREE="$RD/tree"
TREE2="$RD/tree2"
ONE="$RD/one.txt"
VOID="$RD/voidroot"
NOSUCH="$RD/nosuch"
T1="$OUT/t1.zip"
T2="$OUT/t2.zip"
T3="$OUT/t3.zip"
T4="$OUT/t4.zip"
T5="$OUT/t5.zip"
INSIDE="$TREE2/inside.zip"
T7="$OUT/deep/nested/t7.zip"
T8="$OUT/t8.zip"
# Named for what it tests: the boolean left in the environment slot (index 2), which is the
# shape this driver shipped once by accident. See the argument-position section in the header.
T9_STALE_POSITION="$OUT/t9.zip"

C_A=A
C_B=BB
C_ONE=one-file
C_KEEP=keep-me

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

# The instrument this round rests on: a listing parser, and nothing that needs -Z.
instruments() {
    bad=0
    if ! command -v unzip >/dev/null 2>&1; then
        echo "FAIL no unzip on the device -- entry names cannot be observed at all, so this" >&2
        echo "     round would prove nothing. Stopping." >&2
        return 1
    fi
    echo "ok   instrument: unzip is $(command -v unzip)"
    apk=$(pm path "$PKG" 2>/dev/null | sed -n '1p' | sed 's/^package://')
    if [ -n "$apk" ]; then
        n=$(unzip -l "$apk" 2>/dev/null | wc -l)
        if [ "${n:-0}" -ge 3 ]; then
            echo "ok   instrument: unzip -l lists entries ($n lines on the installed apk)"
        else
            echo "FAIL unzip -l produced no listing -- the entry parser would read nothing and" >&2
            echo "     every name check would pass vacuously. Stopping." >&2
            bad=1
        fi
        # End-of-line matching is what keeps a.txt from matching sub/a.txt; prove it here so a
        # parser change cannot quietly turn every name check into a substring search.
        if unzip -l "$apk" 2>/dev/null | grep -q -e '[[:space:]]classes\.dex$'; then
            echo "ok   instrument: end-of-line name matching works"
        else
            echo "warn cannot confirm end-of-line name matching on this unzip -- name checks may" >&2
            echo "     be substring matches, which is weaker than the driver intends" >&2
        fi
    fi
    return "$bad"
}

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

        # The decisive check, and the only one that cannot be fooled by names: both apps report
        # versionName 1.2.7, and staged APK file names only say which commit they claim to be.
        dex=/data/local/tmp/acceptance_probe.dex
        unzip -p "$installed" 'classes*.dex' > "$dex" 2>/dev/null
        size=$(wc -c < "$dex" 2>/dev/null || echo 0)
        if [ "${size:-0}" -lt 100000 ]; then
            echo "warn cannot read the dex out of the installed apk -- build check skipped"
        elif grep -q hostselftest "$dex" && grep -q 'Tools.Files.zip' "$dex"; then
            echo "ok   installed build carries both the host: hook and the zip mapping"
        elif grep -q hostselftest "$dex"; then
            echo "FAIL the installed build has the host: hook but NOT Tools.Files.zip --" >&2
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

    instruments || hard=1

    return "$hard"
}

# The marker is one-shot -- `maybeRunSelfTest` reads it and deletes it -- so this has to run
# again before every round. Reusing a previous round's fixtures is the quiet way to end up with
# a table describing a run that never happened.
setup() {
    need_root
    preflight || {
        echo "aborting: fix what preflight flagged above, or set SKIP_PREFLIGHT=1" >&2
        echo "to lay the fixtures down anyway." >&2
        exit 1
    }
    rm -rf "$RD"
    mkdir -p "$OUT" "$TREE/sub" "$TREE/void" "$TREE2" "$VOID"

    printf '%s' "$C_A" > "$TREE/a.txt"
    printf '%s' "$C_B" > "$TREE/sub/b.txt"
    printf '%s' "$C_KEEP" > "$TREE2/keep.txt"
    printf '%s' "$C_ONE" > "$ONE"
    # $TREE/void and $VOID are left empty on purpose; $NOSUCH is never created.

    cp "$TREE/a.txt" "$RD/.exp_a"
    cp "$TREE/sub/b.txt" "$RD/.exp_b"
    cp "$TREE2/keep.txt" "$RD/.exp_keep"
    cp "$ONE" "$RD/.exp_one"

    for f in "$TREE/a.txt" "$TREE/sub/b.txt" "$TREE2/keep.txt" "$ONE" "$RD/.exp_a" "$RD/.exp_b" "$RD/.exp_keep" "$RD/.exp_one"; do
        if [ ! -f "$f" ]; then
            echo "FAIL fixture $f was not written -- aborting" >&2
            exit 1
        fi
    done
    if [ -n "$(ls -A "$TREE/void" 2>/dev/null)" ]; then
        echo "FAIL $TREE/void is not empty -- case 1 would not test the empty-directory entry" >&2
        exit 1
    fi
    if [ -n "$(ls -A "$VOID" 2>/dev/null)" ]; then
        echo "FAIL $VOID is not empty -- case 5 would not test the empty root directory" >&2
        exit 1
    fi

    for d in "$T1" "$T2" "$T3" "$T4" "$T5" "$INSIDE" "$T7" "$T8" "$T9_STALE_POSITION"; do
        if [ -e "$d" ]; then
            echo "FAIL destination $d already exists before the round -- aborting" >&2
            exit 1
        fi
    done
    [ -e "$NOSUCH" ] && { echo "FAIL $NOSUCH exists -- case 8 would not test ENOENT" >&2; exit 1; }
    [ -e "$OUT/deep" ] && { echo "FAIL $OUT/deep exists -- case 7 needs a missing parent" >&2; exit 1; }

    mkdir -p "$FILES"
# The environment slot (index 2) is written out as an explicit null in every line that carries a
# boolean: the marker text reaches __call verbatim, so what is omitted is not "the value the
# caller would have sent" but "an element that is not there at all". Case 3 keeps the shorter
# shape deliberately (see the header), and case 9 keeps the OLD WRONG shape deliberately.
cat > "$MARKER" <<EOF
#call host:Tools.Files.zip ["$TREE","$T1",,false]
#call host:Tools.Files.zip ["$TREE","$T2",,true]
#call host:Tools.Files.zip ["$TREE","$T3"]
#call host:Tools.Files.zip ["$ONE","$T4",,false]
#call host:Tools.Files.zip ["$VOID","$T5",,true]
#call host:Tools.Files.zip ["$TREE2","$INSIDE",,false]
#call host:Tools.Files.zip ["$TREE","$T7",,false]
#call host:Tools.Files.zip ["$NOSUCH","$T8",,false]
#call host:Tools.Files.zip ["$TREE","$T9_STALE_POSITION",false]
EOF

    # Where this round starts in the append-only log. Recorded here, acted on in verify.
    if [ -f "$DIAG" ]; then
        wc -l < "$DIAG" 2>/dev/null | tr -d ' ' > "$BASE/.log_offset"
    else
        echo 0 > "$BASE/.log_offset"
    fi

    echo "fixtures:"
    echo "  $TREE      (a.txt='$C_A', sub/b.txt='$C_B', void/ EMPTY)"
    echo "  $TREE2     (keep.txt='$C_KEEP' -- the guard's source, must survive untouched)"
    echo "  $ONE       ('$C_ONE')"
    echo "  $VOID      (EMPTY directory, case 5's source)"
    echo "  $NOSUCH    (absent)"
    echo "destinations (none exist yet):"
    echo "  $T1 $T2 $T3 $T4 $T5"
    echo "  $INSIDE  (inside its own source -- case 6 must refuse)"
    echo "  $T7      (under $OUT/deep/nested, which does not exist -- case 7 must create it)"
    echo "  $T8"
    echo "  $T9_STALE_POSITION  (case 9: the marker leaves the boolean at index 2 -- the old wrong shape)"
    echo "marker (note case 3 has NO fourth argument):"
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

# End-of-line match, so "a.txt" cannot be satisfied by the entry "sub/a.txt".
entry_present() {
    # entry_present <zip> <name> -> 1 | 0
    unzip -l "$1" 2>/dev/null | grep -c -e "[[:space:]]$2\$"
}

# Both spellings: the device writes "1 file" for a single entry and "N files" otherwise. An
# unrecognised summary answers "?", which fails the case rather than passing it quietly.
entry_count() {
    unzip -l "$1" 2>/dev/null | tail -1 | awk '{ if ($NF == "files" || $NF == "file") print $(NF-1); else print "?" }'
}

entry_bytes() {
    # entry_bytes <zip> <name> <expected file> -> intact | changed | missing
    unzip -p "$1" "$2" > "$RD/.unz" 2>/dev/null
    cmp_ok "$RD/.unz" "$3"
}

verify() {
    need_root
    if [ ! -f "$DIAG" ]; then
        echo "no $DIAG -- the marker never ran" >&2
        exit 1
    fi

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

    round=$(tail -n +"$((offset + 1))" "$DIAG" | grep hostselftest)
    out=$(printf '%s\n' "$round" | tail -9)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')
    l6=$(printf '%s\n' "$out" | sed -n '6p')
    l7=$(printf '%s\n' "$out" | sed -n '7p')
    l8=$(printf '%s\n' "$out" | sed -n '8p')
    l9=$(printf '%s\n' "$out" | sed -n '9p')

    n_ok='-> "{}"'
    m1=missing; m2=missing; m4=missing; m5=missing; m7=missing
    p1=no; p2=no; p4=no; p5=no; p7=no
    case "$l1" in *THREW*) m1=threw ;; *hostselftest*) m1=payload ;; esac
    case "$l2" in *THREW*) m2=threw ;; *hostselftest*) m2=payload ;; esac
    case "$l4" in *THREW*) m4=threw ;; *hostselftest*) m4=payload ;; esac
    case "$l5" in *THREW*) m5=threw ;; *hostselftest*) m5=payload ;; esac
    case "$l7" in *THREW*) m7=threw ;; *hostselftest*) m7=payload ;; esac
    case "$l1" in *"$n_ok"*) p1=yes ;; esac
    case "$l2" in *"$n_ok"*) p2=yes ;; esac
    case "$l4" in *"$n_ok"*) p4=yes ;; esac
    case "$l5" in *"$n_ok"*) p5=yes ;; esac
    case "$l7" in *"$n_ok"*) p7=yes ;; esac
    case "$l3" in *THREW*) m3=threw ;; *hostselftest*) m3=payload ;; *) m3=missing ;; esac
    case "$l3" in *"$n_ok"*) p3=yes ;; *) p3=no ;; esac
    case "$l6" in *IllegalArgumentException*'destination is inside source'*"$INSIDE"*) m6=inside ;; *THREW*) m6=other ;; *) m6=payload ;; esac
    case "$l8" in *ENOENT*"$NOSUCH"*) m8=ENOENT ;; *THREW*) m8=other ;; *) m8=payload ;; esac
    # Case 9 is expected to SUCCEED: a misaligned marker is not an error, it is a call whose
    # boolean fell one slot short, so the host answers {} and writes the default shape. Its row
    # therefore fails on the EVIDENCE -- a prefixed archive where a relative one was wanted --
    # and never on the message.
    case "$l9" in *THREW*) m9=threw ;; *hostselftest*) m9=payload ;; *) m9=missing ;; esac
    case "$l9" in *"$n_ok"*) p9=yes ;; *) p9=no ;; esac

    n=$(printf '%s\n' "$round" | grep -c hostselftest)
    if [ "$n" != "9" ]; then
        echo "warn this round wrote $n hostselftest lines, not 9. A missing line shifts the" >&2
        echo "     positions below: every case is checked by its own message or its own bytes," >&2
        echo "     so a shift shows up in all nine." >&2
    fi

    # Independent state checks. Nothing here trusts the log: it reads the archives on disk.
    e1_a=$(entry_present "$T1" "a.txt")
    e1_b=$(entry_present "$T1" "sub/b.txt")
    e1_d=$(entry_present "$T1" "sub/")
    e1_v=$(entry_present "$T1" "void/")
    e1_prefix=$(unzip -l "$T1" 2>/dev/null | grep -c -e '[[:space:]]tree/')
    b1_a=$(entry_bytes "$T1" "a.txt" "$RD/.exp_a")
    b1_b=$(entry_bytes "$T1" "sub/b.txt" "$RD/.exp_b")

    e2_a=$(entry_present "$T2" "tree/a.txt")
    e2_b=$(entry_present "$T2" "tree/sub/b.txt")
    e2_v=$(entry_present "$T2" "tree/void/")
    b2_a=$(entry_bytes "$T2" "tree/a.txt" "$RD/.exp_a")

    e3_a=$(entry_present "$T3" "tree/a.txt")
    e3_b=$(entry_present "$T3" "tree/sub/b.txt")
    e3_v=$(entry_present "$T3" "tree/void/")
    e3_rel=$(entry_present "$T3" "a.txt")
    b3_a=$(entry_bytes "$T3" "tree/a.txt" "$RD/.exp_a")

    # n4/n5 and not c4/c5: c4/c5 are the verdicts a few lines below, and while the counts shared
    # those names the verdict was assigned before the comparison, so `[ "$c4" = "1" ]` compared
    # the string FAIL to 1 and cases 4 and 5 could not pass whatever the host wrote. An
    # instrument and a verdict are two different claims and now have two different names.
    n4=$(entry_count "$T4")
    e4=$(entry_present "$T4" "one.txt")
    b4=$(entry_bytes "$T4" "one.txt" "$RD/.exp_one")

    n5=$(entry_count "$T5")
    e5=$(entry_present "$T5" "voidroot/")

    [ -e "$INSIDE" ] && c6_file=created || c6_file=absent
    c6_keep=$(cmp_ok "$RD/.exp_keep" "$TREE2/keep.txt")

    [ -f "$T7" ] && c7_file=yes || c7_file=no
    e7=$(entry_present "$T7" "a.txt")
    b7=$(entry_bytes "$T7" "a.txt" "$RD/.exp_a")

    [ -e "$T8" ] && c8_file=created || c8_file=absent

    # Case 9, the control for the argument positions. Its marker leaves the boolean in the
    # environment slot, so index 3 is absent and the documented default (true) answers: the
    # archive must be the PREFIXED shape, byte-identical to case 2's. A relative entry here
    # means the host read index 2, which is exactly what this case exists to detect.
    n9=$(entry_count "$T9_STALE_POSITION")
    e9_a=$(entry_present "$T9_STALE_POSITION" "tree/a.txt")
    e9_b=$(entry_present "$T9_STALE_POSITION" "tree/sub/b.txt")
    e9_v=$(entry_present "$T9_STALE_POSITION" "tree/void/")
    e9_rel=$(entry_present "$T9_STALE_POSITION" "a.txt")
    b9_a=$(entry_bytes "$T9_STALE_POSITION" "tree/a.txt" "$RD/.exp_a")

    c1=FAIL
    [ "$m1" = payload ] && [ "$p1" = yes ] && [ "$e1_a" = 1 ] && [ "$e1_b" = 1 ] &&
        [ "$e1_d" = 1 ] && [ "$e1_v" = 1 ] && [ "$e1_prefix" = 0 ] &&
        [ "$b1_a" = intact ] && [ "$b1_b" = intact ] && c1=PASS
    c2=FAIL
    [ "$m2" = payload ] && [ "$p2" = yes ] && [ "$e2_a" = 1 ] && [ "$e2_b" = 1 ] &&
        [ "$e2_v" = 1 ] && [ "$b2_a" = intact ] && c2=PASS
    c3=FAIL
    [ "$m3" = payload ] && [ "$p3" = yes ] && [ "$e3_a" = 1 ] && [ "$e3_b" = 1 ] &&
        [ "$e3_v" = 1 ] && [ "$e3_rel" = 0 ] && [ "$b3_a" = intact ] && c3=PASS
    c4=FAIL
    [ "$m4" = payload ] && [ "$p4" = yes ] && [ "$n4" = "1" ] && [ "$e4" = 1 ] &&
        [ "$b4" = intact ] && c4=PASS
    c5=FAIL
    [ "$m5" = payload ] && [ "$p5" = yes ] && [ "$n5" = "1" ] && [ "$e5" = 1 ] && c5=PASS
    c6=FAIL
    [ "$m6" = inside ] && [ "$c6_file" = absent ] && [ "$c6_keep" = intact ] && c6=PASS
    c7=FAIL
    [ "$m7" = payload ] && [ "$p7" = yes ] && [ "$c7_file" = yes ] && [ "$e7" = 1 ] &&
        [ "$b7" = intact ] && c7=PASS
    c8=FAIL
    [ "$m8" = ENOENT ] && [ "$c8_file" = absent ] && c8=PASS
    c9=FAIL
    [ "$m9" = payload ] && [ "$p9" = yes ] && [ "$e9_a" = 1 ] && [ "$e9_b" = 1 ] &&
        [ "$e9_v" = 1 ] && [ "$e9_rel" = 0 ] && [ "$b9_a" = intact ] && c9=PASS

    echo "case  call                          expected                                  actual"
    printf '%-5s %-29s %-41s %s\n' 1 '(dir, flag=false)' '{}; entries relative; bytes round-trip' \
        "msg=$m1 payload=$p1 a.txt=$e1_a sub/b.txt=$e1_b sub/=$e1_d void/=$e1_v tree-prefix=$e1_prefix bytes=$b1_a/$b1_b -> $c1"
    printf '%-5s %-29s %-41s %s\n' 2 '(dir, flag=true)' '{}; entries prefixed with tree/' \
        "msg=$m2 payload=$p2 tree/a.txt=$e2_a tree/sub/b.txt=$e2_b tree/void/=$e2_v bytes=$b2_a -> $c2"
    printf '%-5s %-29s %-41s %s\n' 3 '(dir, flag OMITTED)' '{}; same as 2 -- default is true' \
        "msg=$m3 payload=$p3 tree/a.txt=$e3_a tree/sub/b.txt=$e3_b tree/void/=$e3_v bare-a.txt=$e3_rel bytes=$b3_a -> $c3"
    printf '%-5s %-29s %-41s %s\n' 4 '(file source)' '{}; one entry named one.txt; bytes' \
        "msg=$m4 payload=$p4 entries=$n4 one.txt=$e4 bytes=$b4 -> $c4"
    printf '%-5s %-29s %-41s %s\n' 5 '(empty dir, flag=true)' '{}; exactly one entry voidroot/' \
        "msg=$m5 payload=$p5 entries=$n5 voidroot/=$e5 -> $c5"
    printf '%-5s %-29s %-41s %s\n' 6 '(dst inside source)' 'THREW IllegalArgumentException; no archive' \
        "msg=$m6 archive=$c6_file keep.txt=$c6_keep -> $c6"
    printf '%-5s %-29s %-41s %s\n' 7 '(dst parent missing)' '{}; parents created; relative entry' \
        "msg=$m7 payload=$p7 archive=$c7_file a.txt=$e7 bytes=$b7 -> $c7"
    printf '%-5s %-29s %-41s %s\n' 8 '(source missing)' 'THREW ENOENT; no archive' \
        "msg=$m8 archive=$c8_file -> $c8"
    printf '%-5s %-29s %-41s %s\n' 9 '(flag left in env slot)' '{}; entries PREFIXED -- the default answers' \
        "msg=$m9 payload=$p9 entries=$n9 tree/a.txt=$e9_a tree/sub/b.txt=$e9_b tree/void/=$e9_v bare-a.txt=$e9_rel bytes=$b9_a -> $c9"

    echo
    echo "evidence (last 9 of $n hostselftest lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ] &&
        [ "$c5" = PASS ] && [ "$c6" = PASS ] && [ "$c7" = PASS ] && [ "$c8" = PASS ] &&
        [ "$c9" = PASS ]; then
        echo "all nine PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted {}, a.txt+sub/+sub/b.txt+void/ present, no tree/ prefix, both bytes intact" >&2
    [ "$c1" = FAIL ] && echo "          got a.txt=$e1_a sub/b.txt=$e1_b sub/=$e1_d void/=$e1_v prefix=$e1_prefix bytes=$b1_a/$b1_b" >&2
    [ "$c1" = FAIL ] && [ "$e1_prefix" != 0 ] && echo "          a tree/ entry means flag=false behaved like true: the names are not relative." >&2
    [ "$c1" = FAIL ] && [ "$e1_v" = 0 ] && echo "          no void/ entry: an empty directory was skipped and would vanish on extraction." >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted {}, entries prefixed tree/, got a=$e2_a sub/b=$e2_b void=$e2_v bytes=$b2_a" >&2
    [ "$c3" = FAIL ] && echo "  case 3 (the default-true case): wanted tree/-prefixed entries from a call with NO fourth" >&2
    [ "$c3" = FAIL ] && echo "          argument, got a=$e3_a sub/b=$e3_b void=$e3_v bare-a.txt=$e3_rel bytes=$b3_a" >&2
    [ "$c3" = FAIL ] && [ "$e3_rel" = 1 ] && echo "          a bare a.txt here means the flag was read with optBoolean: the documented" >&2
    [ "$c3" = FAIL ] && [ "$e3_rel" = 1 ] && echo "          default true was silently inverted. isNull(3) is the fix." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted one entry named one.txt with intact bytes, got entries=$n4 one.txt=$e4 bytes=$b4" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted exactly one entry voidroot/, got entries=$n5 voidroot/=$e5" >&2
    [ "$c5" = FAIL ] && [ "$n5" = "0" ] && echo "          an empty archive means the source directory itself was not written." >&2
    [ "$c6" = FAIL ] && echo "  case 6: wanted IllegalArgumentException 'destination is inside source', got msg=$m6 archive=$c6_file keep.txt=$c6_keep" >&2
    [ "$c6" = FAIL ] && [ "$c6_keep" != intact ] && echo "          the guard ran too late: the source was modified." >&2
    [ "$c7" = FAIL ] && echo "  case 7: wanted the archive created under a missing parent, got archive=$c7_file a.txt=$e7 bytes=$b7" >&2
    [ "$c8" = FAIL ] && echo "  case 8: wanted ENOENT + $NOSUCH, got msg=$m8 archive=$c8_file" >&2
    [ "$c9" = FAIL ] && echo "  case 9 (the argument-position control): the marker deliberately leaves the boolean" >&2
    [ "$c9" = FAIL ] && echo "          in the environment slot, so the archive must come back PREFIXED -- the default" >&2
    [ "$c9" = FAIL ] && echo "          is what answers. got msg=$m9 entries=$n9 tree/a.txt=$e9_a tree/sub/b.txt=$e9_b" >&2
    [ "$c9" = FAIL ] && echo "          tree/void/=$e9_v bare-a.txt=$e9_rel bytes=$b9_a" >&2
    [ "$c9" = FAIL ] && [ "$e9_rel" = 1 ] && echo "          a bare a.txt here means the boolean WAS read from index 2, the environment" >&2
    [ "$c9" = FAIL ] && [ "$e9_rel" = 1 ] && echo "          slot -- which is not where the real caller puts it (extended_file_tools.js:108)." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,18p' "$0" ; exit 1 ;;
esac
