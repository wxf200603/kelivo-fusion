#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_move.sh by `cp` -- the
# Android root shell cannot see /root, where the repo lives. The repo copy is
# authoritative, so after any edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_move.sh /sdcard/scripts/
#
# usage: sh acceptance_move.sh preflight | setup | restart | verify
#
#   #  case                          args                  expectation
#   1  file -> new path (same dev)   (src, dst)            no THREW, {}, dst == src, src gone, (dev,ino) PRESERVED
#   2  directory (same dev)          (dir, dst)            no THREW, {}, tree + per-file bytes, src tree gone, (dev,ino) preserved
#   3  source missing                (absent, dst)         THREW: ENOENT + source path, no dst
#   4  destination exists as a file  (src, existing)      no THREW, {}, dst replaced byte-for-byte, src gone
#   5  cross-device  /sdcard -> /data  (src, dst)         no THREW, {}, dst == src, src gone, (dev,ino) NOT preserved
#   6  cross-device  /data -> /sdcard  (src, dst)         same as 5
#   7  directory onto a populated directory               no THREW, {}, MERGED: a.txt replaced, b.txt survives, src tree gone
#   8  file onto an existing directory (src, dir)         THREW: EISDIR "destination is a directory", nothing touched
#   9  directory onto an existing file (dir, file)        THREW: EISDIR "destination is a file, not a directory", nothing touched
#
# WHY THE INSTRUMENTS ARE PART OF THE ACCEPTANCE
#
# The contract of this method is that {} means "the file is at the destination and the
# source is gone", never "we tried" -- daily_life.js:1050 logs "已保存到" on the strength
# of it. So "it answered {}" is not evidence. Every success case is a byte comparison
# against a copy recorded at setup, plus the source's absence.
#
# Cases 5 and 6 exist because crossing /sdcard (FUSE) and /data (ext4) is the ORDINARY
# case for the only caller (daily_life.js:1039 screenshots into the app's own storage,
# :1048 moves it to a user path). rename(2) cannot cross filesystems, so these two cases
# are the ones that actually exercise the copy-then-delete route.
#
# "Did the fallback run?" is answered by (st_dev, st_ino), not by the log:
#   - rename preserves the inode, and stays on one filesystem, so cases 1 and 2 must show
#     the pair UNCHANGED. If a same-device move went through copy+delete, the pair changes
#     and the case fails -- which is the point: it would mean the code took the slow route
#     where rename was available, or that rename silently never ran.
#   - across filesystems the destination is necessarily a NEW file on ANOTHER device, so
#     cases 5 and 6 must show st_dev CHANGED. Comparing the pair (not just the inode) is
#     deliberate: inode numbers come from different spaces on different filesystems, so an
#     inode-only comparison could coincide and prove nothing, while st_dev alone cannot
#     distinguish "same file renamed" from "new file on the same filesystem".
#   preflight refuses to run at all if st_dev(sdcard) == st_dev(data), because then cases
#   5 and 6 could pass without ever touching the fallback.
#
# CASES 8 AND 9 are the guards that keep case 3-7 messages honest: a file onto a directory
# and a directory onto a file are refused BEFORE anything runs, so "copy incomplete" later
# can only mean that something may have been written. Each therefore also asserts that
# nothing was touched: the destination keeps its contents and the source still exists.
#
# CASES 4 AND 7 ARE THE ONES THAT LIE.
#
# Case 4: a host that refuses to overwrite throws; a host that *appends* leaves a file that
# exists and is merely longer. 9 bytes over 8 gives 17 and cmp catches every other variant.
# Case 7: a host that clears the destination first answers {} and looks healthy, but b.txt
# -- which the source never carried -- is gone. That is why b.txt is byte-compared, not
# merely checked for existence.
PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

RD="$BASE/mv"
OUT="$RD/out"
S1="$RD/src1.txt"
TREE="$RD/tree"
NOSUCH="$RD/nosuch"
S4="$RD/src4.txt"
D4="$RD/dst4.txt"
S5="$RD/src5.txt"
S6="$FILES/mv6/src6.txt"
MTREE="$RD/mtree"
MDST="$RD/mdst"
S8="$RD/src8.txt"
DIR8="$RD/dir8"
TREE9="$RD/tree9"
FILE9="$RD/file9.txt"
D1="$OUT/dst1.txt"
TREE_DST="$OUT/tree_dst"
D3="$OUT/dst3.txt"
D5="$FILES/mv5/dst5.txt"
D6="$OUT/dst6.txt"

# ASCII on purpose (the log line carries the payload JSON-escaped) and 9 bytes so that an
# append or a truncation shows up in the byte comparison.
C_S1=move-case
C_S4=move-four
C_S5=cross-out
C_S6=cross-in
C_OLD=old-here
C_M_A=src-side
C_M_B=keep-this
C_M_Z=dst-side
C_S8=file-eight
C_T9=tree-nine
C_F9=keep-me

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

# The two instruments this round depends on. Both are fatal, not warnings: without them
# cases 1/2 and 5/6 degrade into "some bytes ended up somewhere", which is exactly the
# kind of pass this round exists to refuse.
instruments() {
    bad=0
    probe="$BASE/.probe_devino"
    printf x > "$probe" 2>/dev/null || { echo "FAIL cannot write $BASE for the instrument probe" >&2; return 1; }
    pair=$(stat -c '%d %i' "$probe" 2>/dev/null)
    rm -f "$probe"
    case "$pair" in
        '' | *[!0-9\ ]*) echo "FAIL stat -c '%d %i' is unavailable here (got '${pair:-nothing}')" >&2; bad=1 ;;
        *) set -- $pair; [ -n "$1" ] && [ -n "$2" ] && echo "ok   instrument: stat -c '%d %i' -> $pair" ;;
    esac
    d_sd=$(stat -c %d "$BASE" 2>/dev/null)
    d_dt=$(stat -c %d "$FILES" 2>/dev/null)
    if [ -z "$d_sd" ] || [ -z "$d_dt" ]; then
        echo "FAIL cannot read st_dev of both roots ($BASE, $FILES)" >&2
        bad=1
    elif [ "$d_sd" = "$d_dt" ]; then
        echo "FAIL st_dev($BASE)=$d_sd equals st_dev($FILES)=$d_dt -- the cross-device cases" >&2
        echo "     would pass without ever exercising the fallback, so this round cannot" >&2
        echo "     prove what it claims. Stopping rather than banking a false pass." >&2
        bad=1
    else
        echo "ok   instrument: /sdcard st_dev=$d_sd != /data st_dev=$d_dt"
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

        # The decisive check, and the only one that cannot be fooled by names: both apps
        # report versionName 1.2.7, and staged APK file names only say which commit they
        # claim to be. Read the hook out of the installed dex instead.
        dex=/data/local/tmp/acceptance_probe.dex
        unzip -p "$installed" 'classes*.dex' > "$dex" 2>/dev/null
        size=$(wc -c < "$dex" 2>/dev/null || echo 0)
        if [ "${size:-0}" -lt 100000 ]; then
            echo "warn cannot read the dex out of the installed apk -- build check skipped"
        elif grep -q hostselftest "$dex" && grep -q 'Tools.Files.move' "$dex"; then
            echo "ok   installed build carries both the host: hook and the move mapping"
        elif grep -q hostselftest "$dex"; then
            echo "FAIL the installed build has the host: hook but NOT Tools.Files.move --" >&2
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

# The marker is one-shot -- `maybeRunSelfTest` reads it and deletes it -- so this has to
# run again before every round. Reusing a previous round's fixtures is the quiet way to end
# up with a table describing a run that never happened.
setup() {
    need_root
    preflight || {
        echo "aborting: fix what preflight flagged above, or set SKIP_PREFLIGHT=1" >&2
        echo "to lay the fixtures down anyway." >&2
        exit 1
    }
    rm -rf "$RD" "$FILES/mv5" "$FILES/mv6"
    mkdir -p "$OUT" "$TREE/sub" "$MTREE" "$MDST" "$TREE9" "$DIR8" "$FILES/mv5" "$FILES/mv6"

    printf '%s' "$C_S1" > "$S1"
    printf '%s' "$C_S4" > "$S4"
    printf '%s' "$C_S5" > "$S5"
    printf '%s' "$C_S6" > "$S6"
    printf '%s' "$C_OLD" > "$D4"
    printf 'A' > "$TREE/a.txt"
    printf 'BB' > "$TREE/sub/b.txt"
    printf '%s' "$C_M_A" > "$MTREE/a.txt"
    printf '%s' "$C_M_Z" > "$MDST/a.txt"
    printf '%s' "$C_M_B" > "$MDST/b.txt"
    printf '%s' "$C_S8" > "$S8"
    printf 'guard' > "$DIR8/keep.txt"
    printf '%s' "$C_T9" > "$TREE9/a.txt"
    printf '%s' "$C_F9" > "$FILE9"

    # The /data-side fixtures belong to the APP, not to root. This driver runs as root, so
    # anything it creates under /data/data/<pkg>/files is root-owned unless it says
    # otherwise -- and the app then cannot write into mv5/ or unlink inside mv6/, which is
    # exactly how the first device round failed cases 5 and 6 (EACCES on open; "failed to
    # delete"), with the implementation reporting those two failures correctly and this
    # setup being the thing that was wrong. Ownership is checked after the chown rather
    # than assumed, so this cannot silently come back.
    app_uid=$(stat -c %u "$FILES" 2>/dev/null)
    app_gid=$(stat -c %g "$FILES" 2>/dev/null)
    if [ -z "$app_uid" ] || [ -z "$app_gid" ]; then
        echo "FAIL cannot read the owner of $FILES -- the cross-device fixtures cannot be" >&2
        echo "     handed to the app, so cases 5 and 6 would fail for a reason unrelated" >&2
        echo "     to the code under test. Stopping." >&2
        exit 1
    fi
    chown -R "$app_uid:$app_gid" "$FILES/mv5" "$FILES/mv6" 2>/dev/null
    for d in "$FILES/mv5" "$FILES/mv6" "$S6"; do
        u=$(stat -c %u "$d" 2>/dev/null)
        if [ "$u" != "$app_uid" ]; then
            echo "FAIL $d is owned by uid ${u:-?}, not by the app (uid $app_uid) -- cases 5 and 6" >&2
            echo "     would fail on permissions rather than on the code under test." >&2
            exit 1
        fi
    done
    echo "fixtures on the /data side are app-owned (uid $app_uid, gid $app_gid):"
    echo "  $FILES/mv5 (case 5 destination directory)"
    echo "  $FILES/mv6 (case 6 source directory)  src6.txt"

    # The expectation copies. Nothing in verify() compares against the fixture itself: a
    # move removes the source, so the only honest reference is a copy taken before the run.
    cp "$S1" "$RD/.exp_s1"
    cp "$S4" "$RD/.exp_s4"
    cp "$S5" "$RD/.exp_s5"
    cp "$S6" "$RD/.exp_s6"
    cp "$D4" "$RD/.exp_old4"
    cp "$TREE/a.txt" "$RD/.exp_t_a"
    cp "$TREE/sub/b.txt" "$RD/.exp_t_b"
    cp "$MTREE/a.txt" "$RD/.exp_m_a"
    cp "$MDST/b.txt" "$RD/.exp_m_b"
    cp "$MDST/a.txt" "$RD/.exp_m_z"
    cp "$DIR8/keep.txt" "$RD/.exp_d8_keep"
    cp "$TREE9/a.txt" "$RD/.exp_t9_a"
    cp "$FILE9" "$RD/.exp_f9"

    # (st_dev st_ino) of the four sources whose route matters, recorded while they exist.
    stat -c '%d %i' "$S1"   > "$RD/.dv1"
    stat -c '%d %i' "$TREE" > "$RD/.dv2"
    stat -c '%d %i' "$S5"   > "$RD/.dv5"
    stat -c '%d %i' "$S6"   > "$RD/.dv6"
    echo "fixtures: recorded source (dev ino):"
    echo "  s1  $(cat "$RD/.dv1")   tree $(cat "$RD/.dv2")"
    echo "  s5  $(cat "$RD/.dv5")   s6   $(cat "$RD/.dv6")"

    for f in "$S1" "$S4" "$S5" "$S6" "$TREE/a.txt" "$TREE/sub/b.txt" "$MTREE/a.txt" \
             "$MDST/a.txt" "$MDST/b.txt" "$S8" "$DIR8/keep.txt" "$TREE9/a.txt" "$FILE9"; do
        if [ ! -f "$f" ]; then
            echo "FAIL fixture $f was not written -- aborting" >&2
            exit 1
        fi
    done
    sz=$(wc -c < "$S1" | tr -d ' ')
    [ "$sz" = "9" ] || { echo "FAIL $S1 is $sz bytes, expected 9 -- aborting" >&2; exit 1; }
    sz=$(wc -c < "$D4" | tr -d ' ')
    [ "$sz" = "8" ] || { echo "FAIL $D4 is $sz bytes, expected 8 -- aborting" >&2; exit 1; }

    for d in "$D1" "$TREE_DST" "$D3" "$D5" "$D6"; do
        if [ -e "$d" ]; then
            echo "FAIL destination $d already exists before the round -- aborting" >&2
            exit 1
        fi
    done
    [ -e "$NOSUCH" ] && { echo "FAIL $NOSUCH exists -- case 3 would not test ENOENT" >&2; exit 1; }
    [ -d "$DIR8" ] || { echo "FAIL $DIR8 is not a directory -- case 8 needs one" >&2; exit 1; }
    [ -f "$FILE9" ] || { echo "FAIL $FILE9 is not a file -- case 9 needs one" >&2; exit 1; }

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.move ["$S1","$D1"]
#call host:Tools.Files.move ["$TREE","$TREE_DST"]
#call host:Tools.Files.move ["$NOSUCH","$D3"]
#call host:Tools.Files.move ["$S4","$D4"]
#call host:Tools.Files.move ["$S5","$D5"]
#call host:Tools.Files.move ["$S6","$D6"]
#call host:Tools.Files.move ["$MTREE","$MDST"]
#call host:Tools.Files.move ["$S8","$DIR8"]
#call host:Tools.Files.move ["$TREE9","$FILE9"]
EOF

    # Where this round starts in the append-only log. Recorded here, acted on in verify --
    # the log is not moved aside, so this is the only way to read just this round's lines.
    if [ -f "$DIAG" ]; then
        wc -l < "$DIAG" 2>/dev/null | tr -d ' ' > "$BASE/.log_offset"
    else
        echo 0 > "$BASE/.log_offset"
    fi

    echo "destinations (none exist yet, except where the case needs one):"
    echo "  $D1   $TREE_DST   $D3   $D5 (under /data)   $D6"
    echo "case 4 target (pre-existing, '$C_OLD'): $D4"
    echo "case 7 target (pre-existing): $MDST/{a.txt='$C_M_Z',b.txt='$C_M_B'}"
    echo "case 8 target (pre-existing directory): $DIR8/keep.txt"
    echo "case 9 target (pre-existing file, '$C_F9'): $FILE9"
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

    # The nine lines run in order and share one prefix, so the cases are told apart by
    # position: 1 -> case 1, ... 9 -> case 9.
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
    m1=missing; m2=missing; m3=missing; m4=missing; m5=missing
    m6=missing; m7=missing; m8=missing; m9=missing
    p1=no; p2=no; p4=no; p5=no; p6=no; p7=no
    case "$l1" in *THREW*) m1=threw ;; *hostselftest*) m1=payload ;; esac
    case "$l2" in *THREW*) m2=threw ;; *hostselftest*) m2=payload ;; esac
    case "$l4" in *THREW*) m4=threw ;; *hostselftest*) m4=payload ;; esac
    case "$l5" in *THREW*) m5=threw ;; *hostselftest*) m5=payload ;; esac
    case "$l6" in *THREW*) m6=threw ;; *hostselftest*) m6=payload ;; esac
    case "$l7" in *THREW*) m7=threw ;; *hostselftest*) m7=payload ;; esac
    case "$l1" in *"$n_ok"*) p1=yes ;; esac
    case "$l2" in *"$n_ok"*) p2=yes ;; esac
    case "$l4" in *"$n_ok"*) p4=yes ;; esac
    case "$l5" in *"$n_ok"*) p5=yes ;; esac
    case "$l6" in *"$n_ok"*) p6=yes ;; esac
    case "$l7" in *"$n_ok"*) p7=yes ;; esac

    case "$l3" in *ENOENT*"$NOSUCH"*) m3=ENOENT ;; *EISDIR*) m3=EISDIR ;; *THREW*) m3=other ;; *) m3=payload ;; esac
    # Cases 8 and 9 carry the copy family's own two sentences, character for character.
    case "$l8" in *EISDIR*'destination is a directory'*"$DIR8"*) m8=EISDIR_DIR ;; *ENOENT*) m8=ENOENT ;; *THREW*) m8=other ;; *) m8=payload ;; esac
    case "$l9" in *EISDIR*'destination is a file, not a directory'*"$FILE9"*) m9=EISDIR_FILE ;; *ENOENT*) m9=ENOENT ;; *THREW*) m9=other ;; *) m9=payload ;; esac

    n=$(printf '%s\n' "$round" | grep -c hostselftest)
    if [ "$n" != "9" ]; then
        echo "warn this round wrote $n hostselftest lines, not 9. A missing line shifts" >&2
        echo "     the positions below: every case is checked by its own message or its" >&2
        echo "     own bytes, so a shift shows up in all nine." >&2
    fi

    # Independent state checks. Nothing here trusts the log: it reads the disk.
    c1_dst=$(cmp_ok "$RD/.exp_s1" "$D1")
    [ -e "$S1" ] && c1_src=present || c1_src=gone
    dv1_now=$(stat -c '%d %i' "$D1" 2>/dev/null)
    [ "$dv1_now" = "$(cat "$RD/.dv1")" ] && c1_route=preserved || c1_route="$dv1_now"

    c2_a=$(cmp_ok "$RD/.exp_t_a" "$TREE_DST/a.txt")
    c2_b=$(cmp_ok "$RD/.exp_t_b" "$TREE_DST/sub/b.txt")
    [ -e "$TREE" ] && c2_src=present || c2_src=gone
    dv2_now=$(stat -c '%d %i' "$TREE_DST" 2>/dev/null)
    [ "$dv2_now" = "$(cat "$RD/.dv2")" ] && c2_route=preserved || c2_route="$dv2_now"

    [ -e "$D3" ] && c3_litter=yes || c3_litter=no

    c4_dst=$(cmp_ok "$RD/.exp_s4" "$D4")
    c4_old=$(cmp_ok "$RD/.exp_old4" "$D4")
    sz4=$(wc -c < "$D4" 2>/dev/null | tr -d ' ')
    [ -e "$S4" ] && c4_src=present || c4_src=gone

    c5_dst=$(cmp_ok "$RD/.exp_s5" "$D5")
    [ -e "$S5" ] && c5_src=present || c5_src=gone
    dv5_now=$(stat -c '%d %i' "$D5" 2>/dev/null)
    d5_now=$(stat -c %d "$D5" 2>/dev/null)
    d5_was=$(awk '{print $1}' "$RD/.dv5")
    [ -n "$d5_now" ] && [ "$d5_now" != "$d5_was" ] && c5_route=newfs || c5_route="dev=$d5_now was=$d5_was"

    c6_dst=$(cmp_ok "$RD/.exp_s6" "$D6")
    [ -e "$S6" ] && c6_src=present || c6_src=gone
    d6_now=$(stat -c %d "$D6" 2>/dev/null)
    d6_was=$(awk '{print $1}' "$RD/.dv6")
    [ -n "$d6_now" ] && [ "$d6_now" != "$d6_was" ] && c6_route=newfs || c6_route="dev=$d6_now was=$d6_was"

    c7_a=$(cmp_ok "$RD/.exp_m_a" "$MDST/a.txt")
    c7_b=$(cmp_ok "$RD/.exp_m_b" "$MDST/b.txt")
    [ -e "$MTREE" ] && c7_src=present || c7_src=gone

    [ -d "$DIR8" ] && c8_dst=still_a_directory || c8_dst=gone
    c8_keep=$(cmp_ok "$RD/.exp_d8_keep" "$DIR8/keep.txt")
    [ -e "$S8" ] && c8_src=present || c8_src=gone

    [ -f "$FILE9" ] && c9_dst=still_a_file || c9_dst=gone
    c9_keep=$(cmp_ok "$RD/.exp_f9" "$FILE9")
    [ -e "$TREE9" ] && c9_src=present || c9_src=gone
    c9_tree=$(cmp_ok "$RD/.exp_t9_a" "$TREE9/a.txt")

    c1=FAIL
    [ "$m1" = payload ] && [ "$p1" = yes ] && [ "$c1_dst" = intact ] &&
        [ "$c1_src" = gone ] && [ "$c1_route" = preserved ] && c1=PASS
    c2=FAIL
    [ "$m2" = payload ] && [ "$p2" = yes ] && [ "$c2_a" = intact ] && [ "$c2_b" = intact ] &&
        [ "$c2_src" = gone ] && [ "$c2_route" = preserved ] && c2=PASS
    c3=FAIL
    [ "$m3" = ENOENT ] && [ "$c3_litter" = no ] && c3=PASS
    c4=FAIL
    [ "$m4" = payload ] && [ "$p4" = yes ] && [ "$c4_dst" = intact ] &&
        [ "$sz4" = "9" ] && [ "$c4_src" = gone ] && c4=PASS
    c5=FAIL
    [ "$m5" = payload ] && [ "$p5" = yes ] && [ "$c5_dst" = intact ] &&
        [ "$c5_src" = gone ] && [ "$c5_route" = newfs ] && c5=PASS
    c6=FAIL
    [ "$m6" = payload ] && [ "$p6" = yes ] && [ "$c6_dst" = intact ] &&
        [ "$c6_src" = gone ] && [ "$c6_route" = newfs ] && c6=PASS
    c7=FAIL
    [ "$m7" = payload ] && [ "$p7" = yes ] && [ "$c7_a" = intact ] &&
        [ "$c7_b" = intact ] && [ "$c7_src" = gone ] && c7=PASS
    c8=FAIL
    [ "$m8" = EISDIR_DIR ] && [ "$c8_dst" = still_a_directory ] &&
        [ "$c8_keep" = intact ] && [ "$c8_src" = present ] && c8=PASS
    c9=FAIL
    [ "$m9" = EISDIR_FILE ] && [ "$c9_dst" = still_a_file ] && [ "$c9_keep" = intact ] &&
        [ "$c9_src" = present ] && [ "$c9_tree" = intact ] && c9=PASS

    echo "case  args                expected                                     actual"
    printf '%-5s %-19s %-44s %s\n' 1 '(file -> new)' 'no THREW, {}, dst==src, src gone, (dev,ino) kept' \
        "msg=$m1 payload=$p1 dst=$c1_dst src=$c1_src devino=$c1_route -> $c1"
    printf '%-5s %-19s %-44s %s\n' 2 '(dir -> new)' 'no THREW, {}, tree bytes, src tree gone, devino kept' \
        "msg=$m2 payload=$p2 a=$c2_a sub/b=$c2_b src=$c2_src devino=$c2_route -> $c2"
    printf '%-5s %-19s %-44s %s\n' 3 '(absent source)' 'THREW: ENOENT + path, no dst' \
        "msg=$m3 dst_created=$c3_litter -> $c3"
    printf '%-5s %-19s %-44s %s\n' 4 '(dst is a file)' 'no THREW, {}, replaced 9 bytes not 17, src gone' \
        "msg=$m4 payload=$p4 dst=$c4_dst size=$sz4 old_bytes=$c4_old src=$c4_src -> $c4"
    printf '%-5s %-19s %-44s %s\n' 5 '(sdcard -> data)' 'no THREW, {}, dst==src, src gone, st_dev CHANGED' \
        "msg=$m5 payload=$p5 dst=$c5_dst src=$c5_src route=$c5_route -> $c5"
    printf '%-5s %-19s %-44s %s\n' 6 '(data -> sdcard)' 'same as 5' \
        "msg=$m6 payload=$p6 dst=$c6_dst src=$c6_src route=$c6_route -> $c6"
    printf '%-5s %-19s %-44s %s\n' 7 '(dir onto dir)' 'no THREW, {}, a.txt replaced, b.txt SURVIVES, src gone' \
        "msg=$m7 payload=$p7 a=$c7_a b=$c7_b src=$c7_src -> $c7"
    printf '%-5s %-19s %-44s %s\n' 8 '(file onto dir)' 'THREW: EISDIR destination is a directory, nothing touched' \
        "msg=$m8 dir=$c8_dst keep.txt=$c8_keep src=$c8_src -> $c8"
    printf '%-5s %-19s %-44s %s\n' 9 '(dir onto file)' 'THREW: EISDIR destination is a file, not a directory' \
        "msg=$m9 file=$c9_dst content=$c9_keep src_tree=$c9_src -> $c9"

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
    [ "$c1" = FAIL ] && echo "  case 1: wanted {}, $D1 == the recorded bytes, $S1 gone, and (dev,ino) preserved" >&2
    [ "$c1" = FAIL ] && echo "          got msg=$m1 payload=$p1 dst=$c1_dst src=$c1_src devino=$c1_route" >&2
    [ "$c1" = FAIL ] && [ "$c1_route" != preserved ] && echo "          a CHANGED (dev,ino) on a same-device move means rename did not run and copy+delete did." >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted {}, both files intact, $TREE gone, (dev,ino) preserved" >&2
    [ "$c2" = FAIL ] && echo "          got msg=$m2 payload=$p2 a=$c2_a sub/b=$c2_b src=$c2_src devino=$c2_route" >&2
    [ "$c2" = FAIL ] && [ "$c2_a" = missing ] && [ "$c2_b" = missing ] && echo "          both missing means the walk did not descend." >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted ENOENT + $NOSUCH, got msg=$m3 dst_created=$c3_litter" >&2
    [ "$c3" = FAIL ] && [ "$m3" = payload ] && echo "          a {} here means a missing source was reported as a success." >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted {}, 9 bytes, src gone, got msg=$m4 payload=$p4 dst=$c4_dst size=$sz4 src=$c4_src" >&2
    [ "$c4" = FAIL ] && [ "$sz4" = "17" ] && echo "          size 17 = the old 8 bytes are still there: the destination was APPENDED to, not replaced." >&2
    [ "$c4" = FAIL ] && [ "$c4_old" = intact ] && echo "          the old bytes are untouched: nothing was moved." >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted {}, dst==src, src gone, st_dev changed, got msg=$m5 payload=$p5 dst=$c5_dst src=$c5_src route=$c5_route" >&2
    [ "$c5" = FAIL ] && [ "$c5_src" = present ] && echo "          the source is still there: the copy half ran and the delete half did not." >&2
    [ "$c5" = FAIL ] && [ "$c5_dst" = missing ] && echo "          no destination at all: rename failed and the fallback never ran -- the exact" >&2
    [ "$c5" = FAIL ] && [ "$c5_dst" = missing ] && echo "          outcome the {} contract exists to forbid (daily_life.js:1050 would still say 已保存到)." >&2
    [ "$c6" = FAIL ] && echo "  case 6: wanted {}, dst==src, src gone, st_dev changed, got msg=$m6 payload=$p6 dst=$c6_dst src=$c6_src route=$c6_route" >&2
    [ "$c6" = FAIL ] && [ "$c6_src" = present ] && echo "          the source is still there: the copy half ran and the delete half did not." >&2
    [ "$c6" = FAIL ] && [ "$c6_dst" = missing ] && echo "          no destination at all: rename failed and the fallback never ran." >&2
    [ "$c7" = FAIL ] && echo "  case 7: wanted a.txt replaced, b.txt SURVIVING, src gone, got msg=$m7 payload=$p7 a=$c7_a b=$c7_b src=$c7_src" >&2
    [ "$c7" = FAIL ] && [ "$c7_b" = missing ] && echo "          b.txt is gone: the destination was CLEARED before the copy instead of merged into." >&2
    [ "$c8" = FAIL ] && echo "  case 8: wanted EISDIR 'destination is a directory' + nothing touched, got msg=$m8 dir=$c8_dst keep.txt=$c8_keep src=$c8_src" >&2
    [ "$c8" = FAIL ] && [ "$c8_keep" != intact ] && echo "          the guard ran too late: the pre-existing directory lost content." >&2
    [ "$c9" = FAIL ] && echo "  case 9: wanted EISDIR 'destination is a file, not a directory' + nothing touched, got msg=$m9 file=$c9_dst content=$c9_keep src_tree=$c9_src" >&2
    [ "$c9" = FAIL ] && [ "$c9_keep" != intact ] && echo "          the pre-existing file was modified by a move that had to fail." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,16p' "$0" ; exit 1 ;;
esac