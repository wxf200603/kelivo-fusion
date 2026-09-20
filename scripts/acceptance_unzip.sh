#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_unzip.sh by `cp` -- the Android
# root shell cannot see /root, where the repo lives. The repo copy is authoritative, so after any
# edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_unzip.sh /sdcard/scripts/
#
# usage: sh acceptance_unzip.sh preflight | setup | restart | verify
#
#   #  case                          call                             expectation
#   1  plain archive                 unzip(f_plain, out/c1, "linux")  one.txt extracted, bytes identical
#   2  directory entries             unzip(f_tree, out/c2)            a/keep.txt, dir/, dir/empty.txt
#   3  destination chain missing     unzip(f_plain, out/deep/…/c3)    parents created, file extracted
#   4  destination is a file         unzip(f_plain, out/c4file)       THREW EISDIR "…is a file, not a directory"
#   5  source missing                unzip(nosuch, out/c5)            THREW ENOENT; destination NOT created
#   6  "../" escape                  unzip(f_slip, out/c6)            THREW "unsafe entry name: ../escaped.txt"; NOTHING written
#   7  absolute escape               unzip(f_abs, out/c7)             THREW "unsafe entry name: /escaped_abs.txt"; NOTHING written
#   8  deep escape                   unzip(f_deep, out/c8)            THREW "unsafe entry name: a/../../escaped_deep.txt"; NOTHING written
#   9  round trip                    zip(stage) then unzip(rt.zip)    the extracted tree equals the staged tree
#  10  empty archive                 unzip(f_empty, out/c10)          {}; destination created and empty
#  11  symlink entry                 unzip(f_symlink, out/c11)        THREW "unsafe entry name: link"; NOTHING written
#
# WHY CASE 6 IS THE ONE THIS ROUND EXISTS FOR
#
# The device's own /system/bin/unzip refuses an unsafe member name -- `unzip: bad filename
# ../escaped.txt`, exit 1 -- but it is a STREAMING extractor: probed, an archive of benign /
# hostile / benign had its first member written to disk before the refusal, and the third member
# dropped. So the reference tool is fail-closed per entry and fail-open on the prefix. This host
# reads the entry table first (the archive is a seekable file), so a refusal must leave the
# destination exactly as it was -- which is why f_slip.zip carries a benign member FIRST and the
# judgement is "no a/keep.txt on disk", not "the call threw". A test that only checked the throw
# would pass on an implementation that wrote half the archive first. Case 7 and case 11 are built
# the same way, for the same reason.
#
# WHY THE FIXTURES ARE BASE64 IN THIS FILE
#
# The hostile archives cannot be built on the device: it has no `zip` and no `python` (checked;
# busybox there carries gzip/tar/unzip but not zip). They are also not shipped as .zip blobs,
# because a binary blob in a diff shows as "Bin 0 -> 348 bytes" and nobody can review the bytes
# that the security cases rest on. Each fixture is therefore one base64 line, decoded at setup by
# the device's own /system/bin/base64, and the decoded bytes are then checked against `unzip -l`
# so a truncated paste fails the round instead of passing it quietly.
FIX_PLAIN='UEsDBBQAAAAIAAAAIQCWxtN7CgAAAAgAAAAHAAAAb25lLnR4dMvPS9VNy8xJBQBQSwECFAMUAAAACAAAACEAlsbTewoAAAAIAAAABwAAAAAAAAAAAAAApIEAAAAAb25lLnR4dFBLBQYAAAAAAQABADUAAAAvAAAAAAA='
FIX_TREE='UEsDBBQAAAAIAAAAIQArzfRpBwAAAAUAAAAKAAAAYS9rZWVwLnR4dPN2dQ3gAgBQSwMEFAAAAAgAAAAhAAAAAAACAAAAAAAAAAQAAABkaXIvAwBQSwMEFAAAAAgAAAAhAEkgIGUIAAAABgAAAA0AAABkaXIvZW1wdHkudHh0c/UNCInkAgBQSwECFAMUAAAACAAAACEAK830aQcAAAAFAAAACgAAAAAAAAAAAAAApIEAAAAAYS9rZWVwLnR4dFBLAQIUAxQAAAAIAAAAIQAAAAAAAgAAAAAAAAAEAAAAAAAAAAAAAADtQS8AAABkaXIvUEsBAhQDFAAAAAgAAAAhAEkgIGUIAAAABgAAAA0AAAAAAAAAAAAAAKSBUwAAAGRpci9lbXB0eS50eHRQSwUGAAAAAAMAAwClAAAAhgAAAAAA'
FIX_SLIP='UEsDBBQAAAAIAAAAIQC2+yo0DQAAAAsAAAAKAAAAYS9rZWVwLnR4dPN2dQ3QdfMMCg7hAgBQSwMEFAAAAAgAAAAhAGfKoTMKAAAACAAAAA4AAAAuLi9lc2NhcGVkLnR4dHMNdnYMcHXhAgBQSwMEFAAAAAgAAAAhAD+p534HAAAABQAAAAoAAABhL2xhdGUudHh083EMceUCAFBLAQIUAxQAAAAIAAAAIQC2+yo0DQAAAAsAAAAKAAAAAAAAAAAAAACkgQAAAABhL2tlZXAudHh0UEsBAhQDFAAAAAgAAAAhAGfKoTMKAAAACAAAAA4AAAAAAAAAAAAAAKSBNQAAAC4uL2VzY2FwZWQudHh0UEsBAhQDFAAAAAgAAAAhAD+p534HAAAABQAAAAoAAAAAAAAAAAAAAKSBawAAAGEvbGF0ZS50eHRQSwUGAAAAAAMAAwCsAAAAmgAAAAAA'
FIX_ABS='UEsDBBQAAAAIAAAAIQBeOYNEBgAAAAQAAAAHAAAAdG9wLnR4dAvxD+ACAFBLAwQUAAAACAAAACEA5Z1VQQ4AAAAMAAAAEAAAAC9lc2NhcGVkX2Ficy50eHRzDXZ2DHB10XV0CuYCAFBLAQIUAxQAAAAIAAAAIQBeOYNEBgAAAAQAAAAHAAAAAAAAAAAAAACkgQAAAAB0b3AudHh0UEsBAhQDFAAAAAgAAAAhAOWdVUEOAAAADAAAABAAAAAAAAAAAAAAAKSBKwAAAC9lc2NhcGVkX2Ficy50eHRQSwUGAAAAAAIAAgBzAAAAZwAAAAAA'
FIX_DEEP='UEsDBBQAAAAIAAAAIQAsmD7vDwAAAA0AAAAYAAAAYS8uLi8uLi9lc2NhcGVkX2RlZXAudHh0cw12dgxwddF1cXUN4AIAUEsBAhQDFAAAAAgAAAAhACyYPu8PAAAADQAAABgAAAAAAAAAAAAAAKSBAAAAAGEvLi4vLi4vZXNjYXBlZF9kZWVwLnR4dFBLBQYAAAAAAQABAEYAAABFAAAAAAA='
FIX_SYMLINK='UEsDBBQAAAAIAAAAIQArzfRpBwAAAAUAAAAKAAAAYS9rZWVwLnR4dPN2dQ3gAgBQSwMEFAAAAAgAAAAhAJUbeTEMAAAACgAAAAQAAABsaW5r008tSdbPyC8uKQYAUEsBAhQDFAAAAAgAAAAhACvN9GkHAAAABQAAAAoAAAAAAAAAAAAAAKSBAAAAAGEva2VlcC50eHRQSwECFAMUAAAACAAAACEAlRt5MQwAAAAKAAAABAAAAAAAAAAAAAAA/6EvAAAAbGlua1BLBQYAAAAAAgACAGoAAABdAAAAAAA='
FIX_EMPTY='UEsFBgAAAAAAAAAAAAAAAAAAAAAAAA=='

PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

RD="$BASE/uz"
OUT="$RD/out"
FIX="$RD/fix"
STAGE="$RD/rt/src"
RTZIP="$RD/rt/rt.zip"
NOSUCH="$RD/nosuch.zip"
D4FILE="$OUT/c4file"
ROOT_ESC=/escaped_abs.txt

D1="$OUT/c1"
D2="$OUT/c2"
D3="$OUT/deep/nested/c3"
D5="$OUT/c5"
D6="$OUT/c6"
D7="$OUT/c7"
D8="$OUT/c8"
D9="$OUT/c9"
D10="$OUT/c10"
D11="$OUT/c11"

C_ONE=one-file
C_KEEP=KEEP
C_EMPTY=EMPTY
C_TOP=TOP

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

# The instruments are the device's own: base64 to materialise the fixtures, unzip to prove they
# are what they claim to be. Nothing here needs -Z.
instruments() {
    bad=0
    if ! command -v base64 >/dev/null 2>&1; then
        echo "FAIL no base64 on the device -- the fixtures cannot be materialised, so this round" >&2
        echo "     would test nothing. Stopping." >&2
        return 1
    fi
    echo "ok   instrument: base64 is $(command -v base64)"
    if ! command -v unzip >/dev/null 2>&1; then
        echo "FAIL no unzip on the device -- the fixture check below could not run." >&2
        return 1
    fi
    echo "ok   instrument: unzip is $(command -v unzip)"
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
        # versionName 1.2.7, and APK builds of this project are NOT reproducible across runs
        # (same commit, different bytes), so a size/hash comparison against a previous round's
        # artifact proves nothing. The dex literal is what says whether the new method is here.
        # Tools.Files.zip is required as well: case 9 drives the zip method this round does not
        # own.
        dex=/data/local/tmp/acceptance_probe.dex
        unzip -p "$installed" 'classes*.dex' > "$dex" 2>/dev/null
        size=$(wc -c < "$dex" 2>/dev/null || echo 0)
        if [ "${size:-0}" -lt 100000 ]; then
            echo "warn cannot read the dex out of the installed apk -- build check skipped"
        else
            has_unzip=$(grep -c -e 'Tools.Files.unzip' "$dex")
            has_zip=$(grep -c -e 'Tools.Files.zip' "$dex")
            if [ "$has_unzip" -ge 1 ] && [ "$has_zip" -ge 1 ]; then
                echo "ok   installed build carries Tools.Files.unzip ($has_unzip) and Tools.Files.zip ($has_zip)"
            else
                echo "FAIL the installed build carries Tools.Files.unzip=$has_unzip and" >&2
                echo "     Tools.Files.zip=$has_zip -- it predates the commit under test." >&2
                hard=1
            fi
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

# One fixture per line, decoded by the device, then checked with the round's own instrument: if
# what came back is not an archive with the expected entry names, the round stops here rather
# than reporting a host failure that is really a paste error.
lay_fixture() {
    # lay_fixture <name> <base64> <expected entry...>
    name=$1
    blob=$2
    shift 2
    printf '%s' "$blob" | base64 -d > "$FIX/$name" 2>/dev/null
    if [ ! -s "$FIX/$name" ]; then
        echo "FAIL $name did not decode -- aborting" >&2
        exit 1
    fi
    listing=$(unzip -l "$FIX/$name" 2>/dev/null)
    for want in "$@"; do
        got=$(printf '%s\n' "$listing" | grep -c -e "[[:space:]]$want\$")
        if [ "$got" != "1" ]; then
            echo "FAIL $name does not list '$want' exactly once -- the fixture is not the archive" >&2
            echo "     this round needs. Aborting." >&2
            exit 1
        fi
    done
    echo "ok   fixture $name ($(wc -c < "$FIX/$name") bytes, $(printf '%s\n' "$listing" | tail -1 | awk '{print $1, $2}') entries)"
    return 0
}

setup() {
    need_root
    preflight || {
        echo "aborting: fix what preflight flagged above, or set SKIP_PREFLIGHT=1" >&2
        echo "to lay the fixtures down anyway." >&2
        exit 1
    }
    rm -rf "$RD"
    mkdir -p "$OUT" "$FIX" "$STAGE/sub"

    lay_fixture f_plain.zip "$FIX_PLAIN" 'one.txt'
    lay_fixture f_tree.zip "$FIX_TREE" 'a/keep.txt' 'dir/' 'dir/empty.txt'
    lay_fixture f_slip.zip "$FIX_SLIP" 'a/keep.txt' '../escaped.txt' 'a/late.txt'
    lay_fixture f_abs.zip "$FIX_ABS" 'top.txt' '/escaped_abs.txt'
    lay_fixture f_deep.zip "$FIX_DEEP" 'a/../../escaped_deep.txt'
    lay_fixture f_symlink.zip "$FIX_SYMLINK" 'a/keep.txt' 'link'
    lay_fixture f_empty.zip "$FIX_EMPTY"

    # Expected contents, recorded as files rather than as strings in the judgements.
    printf '%s' "$C_ONE" > "$RD/.exp_one"
    printf '%s' "$C_KEEP" > "$RD/.exp_keep"
    printf '%s' "$C_EMPTY" > "$RD/.exp_empty"
    printf '%s' "$C_TOP" > "$RD/.exp_top"

    # Case 4's destination: an existing FILE where a directory is needed, plus the copy of its
    # bytes that the judgement compares against (so "the refusal left the file alone" is measured
    # rather than assumed).
    printf '%s' 'not a directory' > "$D4FILE"
    printf '%s' 'not a directory' > "$RD/.exp_c4"

    # Case 9's staging tree: two files, one nested, zipped with relative entry names (which is
    # what the package's own ToolPkg path does) and then unzipped again.
    printf '%s' "$C_ONE" > "$STAGE/one.txt"
    printf '%s' "$C_TOP" > "$STAGE/sub/two.txt"

    for d in "$D1" "$D2" "$D3" "$D5" "$D6" "$D7" "$D8" "$D9" "$D10" "$D11" "$RTZIP"; do
        if [ -e "$d" ]; then
            echo "FAIL destination $d already exists before the round -- aborting" >&2
            exit 1
        fi
    done
    for f in "$NOSUCH" "$ROOT_ESC" "$OUT/escaped.txt" "$OUT/escaped_deep.txt"; do
        if [ -e "$f" ]; then
            echo "FAIL $f exists before the round -- the escape judgements would be vacuous." >&2
            exit 1
        fi
    done

    mkdir -p "$FILES"
    # Case 1 asks with "linux" rather than "android": this host serves one namespace and must not
    # route on the environment, so the value is deliberately not the one the real caller sends.
    cat > "$MARKER" <<EOF
#call host:Tools.Files.zip ["$STAGE","$RTZIP",,false]
#call host:Tools.Files.unzip ["$FIX/f_plain.zip","$D1","linux"]
#call host:Tools.Files.unzip ["$FIX/f_tree.zip","$D2","android"]
#call host:Tools.Files.unzip ["$FIX/f_plain.zip","$D3","android"]
#call host:Tools.Files.unzip ["$FIX/f_plain.zip","$D4FILE","android"]
#call host:Tools.Files.unzip ["$NOSUCH","$D5","android"]
#call host:Tools.Files.unzip ["$FIX/f_slip.zip","$D6","android"]
#call host:Tools.Files.unzip ["$FIX/f_abs.zip","$D7","android"]
#call host:Tools.Files.unzip ["$FIX/f_deep.zip","$D8","android"]
#call host:Tools.Files.unzip ["$RTZIP","$D9","android"]
#call host:Tools.Files.unzip ["$FIX/f_empty.zip","$D10","android"]
#call host:Tools.Files.unzip ["$FIX/f_symlink.zip","$D11","android"]
EOF

    # Where this round starts in the append-only log. Recorded here, acted on in verify.
    if [ -f "$DIAG" ]; then
        wc -l < "$DIAG" 2>/dev/null | tr -d ' ' > "$BASE/.log_offset"
    else
        echo 0 > "$BASE/.log_offset"
    fi

    echo "destinations (none exist yet, except the file case 4 must trip over):"
    echo "  c1 $D1        c2 $D2        c3 $D3 (under a missing chain)"
    echo "  c4 $D4FILE  (an existing FILE)"
    echo "  c5 $D5 (stays absent: ENOENT is thrown before anything is created)"
    echo "  c6 $D6   c7 $D7   c8 $D8   c11 $D11  (hostile archives: must stay EMPTY)"
    echo "  c9 $D9 (round trip)     c10 $D10 (empty archive: created, empty)"
    echo "now restart the app so configure() runs the marker, then: verify"
}

restart() {
    need_root
    am force-stop "$PKG"
    monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "relaunched $PKG -- open the JS tools screen if configure() does not run on launch"
}

# intact | changed | missing
cmp_ok() {
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

# empty | absent | has-files -- the zero-write judgement for the hostile cases.
dir_state() {
    if [ ! -e "$1" ]; then
        echo absent
    elif [ -z "$(ls -A "$1" 2>/dev/null)" ]; then
        echo empty
    else
        echo has-files
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

    # Only this method's lines: case 9 also drives Tools.Files.zip, and that line must not shift
    # the eleven positions.
    round=$(tail -n +"$((offset + 1))" "$DIAG" | grep -e 'Tools.Files.unzip')
    out=$(printf '%s\n' "$round" | tail -11)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')
    l4=$(printf '%s\n' "$out" | sed -n '4p')
    l5=$(printf '%s\n' "$out" | sed -n '5p')
    l6=$(printf '%s\n' "$out" | sed -n '6p')
    l7=$(printf '%s\n' "$out" | sed -n '7p')
    l8=$(printf '%s\n' "$out" | sed -n '8p')
    l9=$(printf '%s\n' "$out" | sed -n '9p')
    l10=$(printf '%s\n' "$out" | sed -n '10p')
    l11=$(printf '%s\n' "$out" | sed -n '11p')

    n_ok='-> "{}"'
    m1=missing; m2=missing; m3=missing; m9=missing; m10=missing
    p1=no; p2=no; p3=no; p9=no; p10=no
    case "$l1" in *THREW*) m1=threw ;; *hostselftest*) m1=payload ;; esac
    case "$l2" in *THREW*) m2=threw ;; *hostselftest*) m2=payload ;; esac
    case "$l3" in *THREW*) m3=threw ;; *hostselftest*) m3=payload ;; esac
    case "$l9" in *THREW*) m9=threw ;; *hostselftest*) m9=payload ;; esac
    case "$l10" in *THREW*) m10=threw ;; *hostselftest*) m10=payload ;; esac
    case "$l1" in *"$n_ok"*) p1=yes ;; esac
    case "$l2" in *"$n_ok"*) p2=yes ;; esac
    case "$l3" in *"$n_ok"*) p3=yes ;; esac
    case "$l9" in *"$n_ok"*) p9=yes ;; esac
    case "$l10" in *"$n_ok"*) p10=yes ;; esac

    case "$l4" in *EISDIR*'destination is a file, not a directory'*"$D4FILE"*) m4=EISDIR ;; *THREW*) m4=other ;; *) m4=payload ;; esac
    case "$l5" in *ENOENT*"$NOSUCH"*) m5=ENOENT ;; *THREW*) m5=other ;; *) m5=payload ;; esac
    case "$l6" in *'unsafe entry name: ../escaped.txt'*) m6=unsafe ;; *THREW*) m6=other ;; *) m6=payload ;; esac
    case "$l7" in *'unsafe entry name: /escaped_abs.txt'*) m7=unsafe ;; *THREW*) m7=other ;; *) m7=payload ;; esac
    case "$l8" in *'unsafe entry name: a/../../escaped_deep.txt'*) m8=unsafe ;; *THREW*) m8=other ;; *) m8=payload ;; esac
    case "$l11" in *'unsafe entry name: link'*) m11=unsafe ;; *THREW*) m11=other ;; *) m11=payload ;; esac

    n=$(printf '%s\n' "$round" | grep -c hostselftest)
    if [ "$n" != "11" ]; then
        echo "warn this round wrote $n unzip lines, not 11. A missing line shifts the positions" >&2
        echo "     below: every case is checked by its own message or its own bytes, so a shift" >&2
        echo "     shows up in all eleven." >&2
    fi

    # --- case 1: the plain archive -----------------------------------------------------------------
    c1_file=$(cmp_ok "$D1/one.txt" "$RD/.exp_one")
    c1=FAIL
    [ "$m1" = payload ] && [ "$p1" = yes ] && [ "$c1_file" = intact ] && c1=PASS

    # --- case 2: directory entries, including one that exists only as an entry ---------------------
    c2_a=$(cmp_ok "$D2/a/keep.txt" "$RD/.exp_keep")
    c2_e=$(cmp_ok "$D2/dir/empty.txt" "$RD/.exp_empty")
    [ -d "$D2/dir" ] && c2_dir=yes || c2_dir=no
    c2=FAIL
    [ "$m2" = payload ] && [ "$p2" = yes ] && [ "$c2_a" = intact ] && [ "$c2_e" = intact ] &&
        [ "$c2_dir" = yes ] && c2=PASS

    # --- case 3: the destination chain is created by the host --------------------------------------
    c3_file=$(cmp_ok "$D3/one.txt" "$RD/.exp_one")
    c3=FAIL
    [ "$m3" = payload ] && [ "$p3" = yes ] && [ "$c3_file" = intact ] && c3=PASS

    # --- case 4: destination is a file ------------------------------------------------------------
    [ -f "$D4FILE" ] && c4_kind=file || c4_kind=other
    c4_content=$(cmp_ok "$D4FILE" "$RD/.exp_c4")
    c4=FAIL
    [ "$m4" = EISDIR ] && [ "$c4_kind" = file ] && [ "$c4_content" = intact ] && c4=PASS

    # --- case 5: source missing -------------------------------------------------------------------
    [ -e "$D5" ] && c5_dst=created || c5_dst=absent
    c5=FAIL
    [ "$m5" = ENOENT ] && [ "$c5_dst" = absent ] && c5=PASS

    # --- cases 6/7/8/11: unsafe names, and the zero-write promise ----------------------------------
    c6_state=$(dir_state "$D6")
    c6_escape=$(dir_state "$OUT/escaped.txt")
    c6=FAIL
    [ "$m6" = unsafe ] && [ "$c6_state" != has-files ] && [ "$c6_escape" = absent ] && c6=PASS

    c7_state=$(dir_state "$D7")
    [ -e "$ROOT_ESC" ] && c7_root=present || c7_root=absent
    c7=FAIL
    [ "$m7" = unsafe ] && [ "$c7_state" != has-files ] && [ "$c7_root" = absent ] && c7=PASS

    c8_state=$(dir_state "$D8")
    c8_escape=$(dir_state "$OUT/escaped_deep.txt")
    c8=FAIL
    [ "$m8" = unsafe ] && [ "$c8_state" != has-files ] && [ "$c8_escape" = absent ] && c8=PASS

    # --- case 9: the round trip through this project's own zip ------------------------------------
    c9_a=$(cmp_ok "$D9/one.txt" "$STAGE/one.txt")
    c9_b=$(cmp_ok "$D9/sub/two.txt" "$STAGE/sub/two.txt")
    c9=FAIL
    [ "$m9" = payload ] && [ "$p9" = yes ] && [ "$c9_a" = intact ] && [ "$c9_b" = intact ] && c9=PASS

    # --- case 10: an empty archive is not an error ------------------------------------------------
    c10_state=$(dir_state "$D10")
    c10=FAIL
    [ "$m10" = payload ] && [ "$p10" = yes ] && [ "$c10_state" = empty ] && c10=PASS

    # --- case 11: a symlink entry ----------------------------------------------------------------
    c11_state=$(dir_state "$D11")
    c11=FAIL
    [ "$m11" = unsafe ] && [ "$c11_state" != has-files ] && c11=PASS

    echo "case  call                          expected                                  actual"
    printf '%-5s %-29s %-41s %s\n' 1 '(plain, env="linux")' '{}; one.txt extracted, bytes identical' \
        "msg=$m1 payload=$p1 one.txt=$c1_file -> $c1"
    printf '%-5s %-29s %-41s %s\n' 2 '(directory entries)' '{}; a/keep.txt, dir/, dir/empty.txt' \
        "msg=$m2 payload=$p2 a/keep.txt=$c2_a dir/exists=$c2_dir dir/empty.txt=$c2_e -> $c2"
    printf '%-5s %-29s %-41s %s\n' 3 '(destination chain)' '{}; parents created; file extracted' \
        "msg=$m3 payload=$p3 one.txt=$c3_file -> $c3"
    printf '%-5s %-29s %-41s %s\n' 4 '(destination is a file)' 'THREW EISDIR; the file is untouched' \
        "msg=$m4 kind=$c4_kind content=$c4_content -> $c4"
    printf '%-5s %-29s %-41s %s\n' 5 '(source missing)' 'THREW ENOENT; destination NOT created' \
        "msg=$m5 destination=$c5_dst -> $c5"
    printf '%-5s %-29s %-41s %s\n' 6 '("../ escape)"' 'THREW unsafe entry name; NOTHING written' \
        "msg=$m6 destination=$c6_state escaped-to-parent=$c6_escape -> $c6"
    printf '%-5s %-29s %-41s %s\n' 7 '(absolute escape)' 'THREW unsafe entry name; NOTHING written' \
        "msg=$m7 destination=$c7_state $ROOT_ESC=$c7_root -> $c7"
    printf '%-5s %-29s %-41s %s\n' 8 '(deep escape)' 'THREW unsafe entry name; NOTHING written' \
        "msg=$m8 destination=$c8_state escaped-to-parent=$c8_escape -> $c8"
    printf '%-5s %-29s %-41s %s\n' 9 '(round trip via zip)' '{}; the extracted tree equals the staged one' \
        "msg=$m9 payload=$p9 one.txt=$c9_a sub/two.txt=$c9_b -> $c9"
    printf '%-5s %-29s %-41s %s\n' 10 '(empty archive)' '{}; destination created and empty' \
        "msg=$m10 payload=$p10 destination=$c10_state -> $c10"
    printf '%-5s %-29s %-41s %s\n' 11 '(symlink entry)' 'THREW unsafe entry name; NOTHING written' \
        "msg=$m11 destination=$c11_state -> $c11"

    echo
    echo "evidence (last 11 of $n unzip lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ] &&
        [ "$c5" = PASS ] && [ "$c6" = PASS ] && [ "$c7" = PASS ] && [ "$c8" = PASS ] &&
        [ "$c9" = PASS ] && [ "$c10" = PASS ] && [ "$c11" = PASS ]; then
        echo "all eleven PASS."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted {} with one.txt intact (environment is ignored, not routed on)" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted a/keep.txt=$c2_a dir=$c2_dir dir/empty.txt=$c2_e (empty dirs are entries)" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted the missing chain created and one.txt extracted, got $c3_file" >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted EISDIR naming the file, it still a file with its bytes, got msg=$m4 kind=$c4_kind content=$c4_content" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted ENOENT + the source path and no destination, got msg=$m5 destination=$c5_dst" >&2
    [ "$c6" = FAIL ] && echo "  case 6 (the round's key case): wanted an unsafe-name refusal and ZERO writes." >&2
    [ "$c6" = FAIL ] && echo "          destination=$c6_state (has-files means the benign member before the hostile one landed)" >&2
    [ "$c6" = FAIL ] && echo "          escaped-to-parent=$c6_escape (has-files means the hostile member escaped)" >&2
    [ "$c7" = FAIL ] && echo "  case 7: wanted an unsafe-name refusal and ZERO writes, got destination=$c7_state root-file=$c7_root" >&2
    [ "$c8" = FAIL ] && echo "  case 8: wanted an unsafe-name refusal and ZERO writes, got destination=$c8_state escaped=$c8_escape" >&2
    [ "$c9" = FAIL ] && echo "  case 9: the zip -> unzip round trip, got msg=$m9 payload=$p9 one.txt=$c9_a sub/two.txt=$c9_b" >&2
    [ "$c9" = FAIL ] && [ "$m9" = threw ] && echo "          a throw here means the zip call that feeds this case did not produce $RTZIP" >&2
    [ "$c10" = FAIL ] && echo "  case 10: wanted a success with a created, empty destination, got msg=$m10 payload=$p10 state=$c10_state" >&2
    [ "$c11" = FAIL ] && echo "  case 11: wanted the symlink entry refused and ZERO writes, got msg=$m11 destination=$c11_state" >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,25p' "$0" ; exit 1 ;;
esac
