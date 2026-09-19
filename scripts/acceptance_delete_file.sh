#!/system/bin/sh
# Acceptance driver for `Tools.Files.deleteFile` -- the five cases, two channels.
#
#   usage, as root on the device:
#     sh scripts/acceptance_delete_file.sh setup      # fixtures + marker file
#     sh scripts/acceptance_delete_file.sh restart    # force-stop + relaunch
#     sh scripts/acceptance_delete_file.sh verify     # expectation table, expected vs actual
#
#   the marker is one-shot: `maybeRunSelfTest` deletes it after reading, so
#   `setup` has to run again before every round.
#
# The five cases, and which channel drives each:
#
#   #  case                                  channel           expectation
#   1  delete a plain file                    package           file gone
#   2  non-empty dir, recursive=false         host:             THREW: EISDIR, dir intact
#   3  empty dir, recursive=false             host:             THREW: EISDIR, dir intact
#   4  delete a path that does not exist      host:             THREW: ENOENT
#   5  recursive delete of a non-empty dir    package           tree gone
#
# Cases 2/3/4 are driven by the `host:` prefix (worktree commit 7e2fcf3). They
# could not be driven before it: no package call site passes `recursive=false`
# or chooses its own path -- github.js:799 and file_converter.js:211 hardcode
# `true`, openai_draw.js:208 deletes an internal tmp, operit_editor.js:2599/2716
# hide the path in a cleanup helper, and extended_file_tools has no delete tool
# at all. Cases 1 and 5 stay on the package channel on purpose: they are what
# proves the normal route still works. This script lays out their fixtures but
# does not drive them, and says so in the table rather than claiming a pass.
#
# THE ONE THAT LIES -- case 3. `File.delete()` returns true for an empty
# directory. A host that checks `isDirectory && !recursive` *after* deleting
# therefore reports success and the directory disappears without a word. The
# failure mode for case 3 is "no THREW line AND the directory is gone". An
# exception here is the PASS, not the failure -- do not read "it threw" as a
# broken run.
#
# The failure of every case arrives as a `THREW: ...` line in the diagnostic
# log, because the dispatcher rethrows for this method (THROWING_METHODS).

PKG=${PKG:-com.psyche.kelivo}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"

# Fixtures. Cases 1 and 5 get their own trees so that running them later cannot
# disturb the cases this script does drive.
PLAIN="$BASE/plain/file.txt"
NONEMPTY="$BASE/nonempty"          # case 2
EMPTY="$BASE/empty"                # case 3
MISSING="$BASE/missing"            # case 4, deliberately never created
REC="$BASE/nonempty-rec"           # case 5

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

setup() {
    need_root
    rm -rf "$BASE"
    mkdir -p "$(dirname "$PLAIN")" "$NONEMPTY/sub" "$EMPTY" "$REC/sub"
    echo case1 > "$PLAIN"
    echo case2 > "$NONEMPTY/sub/file"
    echo case5 > "$REC/sub/file"
    # $MISSING is left absent on purpose.

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.deleteFile ["$NONEMPTY",false]
#call host:Tools.Files.deleteFile ["$EMPTY",false]
#call host:Tools.Files.deleteFile ["$MISSING",false]
EOF

    echo "fixtures:"
    echo "  $PLAIN                (case 1, package channel)"
    echo "  $NONEMPTY/sub/file    (case 2)"
    echo "  $EMPTY                (case 3, empty)"
    echo "  $MISSING              (case 4, absent)"
    echo "  $REC/sub/file         (case 5, package channel)"
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

    # The three host: lines run in order and share one prefix, so the cases are
    # told apart by position: 1 -> case 2, 2 -> case 3, 3 -> case 4.
    out=$(grep 'hostselftest' "$DIAG" | tail -3)
    l1=$(printf '%s\n' "$out" | sed -n '1p')
    l2=$(printf '%s\n' "$out" | sed -n '2p')
    l3=$(printf '%s\n' "$out" | sed -n '3p')

    case "$l1" in *EISDIR*) c2_msg=pass ;; *) c2_msg=fail ;; esac
    case "$l2" in *EISDIR*) c3_msg=pass ;; *) c3_msg=fail ;; esac
    case "$l3" in *ENOENT*) c4_msg=pass ;; *) c4_msg=fail ;; esac
    [ -d "$NONEMPTY" ] && c2_dir=intact || c2_dir=gone
    [ -d "$EMPTY" ] && c3_dir=intact || c3_dir=gone
    [ -e "$MISSING" ] && c4_dir=appeared || c4_dir=absent

    [ "$c2_msg" = pass ] && [ "$c2_dir" = intact ] && c2=PASS || c2=FAIL
    [ "$c3_msg" = pass ] && [ "$c3_dir" = intact ] && c3=PASS || c3=FAIL
    c4=FAIL
    [ "$c4_msg" = pass ] && [ "$c4_dir" = absent ] && c4=PASS

    echo "case  channel  expected                        actual"
    printf '%-5s %-8s %-31s %s\n' 1 package  'file gone' \
        "$([ -e "$PLAIN" ] && echo 'present' || echo 'gone (fixture, not driven here)')"
    printf '%-5s %-8s %-31s %s\n' 2 host: 'THREW: EISDIR, dir intact' \
        "msg=$c2_msg dir=$c2_dir -> $c2"
    printf '%-5s %-8s %-31s %s\n' 3 host: 'THREW: EISDIR, dir intact' \
        "msg=$c3_msg dir=$c3_dir -> $c3"
    printf '%-5s %-8s %-31s %s\n' 4 host: 'THREW: ENOENT' \
        "msg=$c4_msg path=$c4_dir -> $c4"
    printf '%-5s %-8s %-31s %s\n' 5 package  'tree gone' \
        "$([ -d "$REC" ] && echo 'present (fixture, not driven here)' || echo 'gone')"

    echo
    echo "evidence (last 3 hostselftest lines):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ]; then
        echo "2/3/4 PASS. 1 and 5 still need their package channel driven."
        return 0
    fi
    echo "2/3/4 NOT all passing -- see the rows above." >&2
    if [ "$c3" = FAIL ]; then
        echo "case 3 failed: no THREW line and/or $EMPTY is not intact." >&2
        echo "the mirror of that is the trap -- for case 3, 'it threw' is the" >&2
        echo "PASS: a silent success means File.delete() removed the empty dir." >&2
    fi
    return 1
}

case "${1:-}" in
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    *) sed -n '2,10p' "$0" ; exit 1 ;;
esac
