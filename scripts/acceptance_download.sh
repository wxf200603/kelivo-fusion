#!/system/bin/sh
# NOTE: this file is deployed to /sdcard/scripts/acceptance_download.sh by `cp` -- the Android
# root shell cannot see /root, where the repo lives. The repo copy is authoritative, so after any
# edit here, re-sync:
#   cp /root/merge/work/OperitKelivo/scripts/acceptance_download.sh /sdcard/scripts/
#
# usage: sh acceptance_download.sh preflight | setup | restart | verify | stop
#
#   #  case                          call                                      expectation
#   1  plain download                download(url/ok.txt, D1)                  successful=true; bytes identical; details = template
#   2  destination chain missing     download(url/ok.txt, D2/deep/..)          parents created; success
#   3  destination already exists    download(url/ok.txt, D3)                  overwritten; bytes identical
#   4  scheme not http(s)            download("ftp://...", D4)                 successful=false; "URL must start with http:// or https://"
#   5  url blank                     download("", D5)                          successful=false; "Either url or (visit_key + link_number/image_number) is required"
#   6  destination blank             download(url/ok.txt, "")                  successful=false; "URL and destination parameters are required"
#   7  HTTP 404                      download(url/nope.txt, D7)                successful=false; "Error downloading file: HTTP 404"
#   8  HTTP 500                      download(url/cgi-bin/status500.sh, D8)    successful=false; "Error downloading file: HTTP 500"
#   9  connection refused            download(http://127.0.0.1:$REFUSE/ok.txt) successful=false; "Error downloading file: <msg>"
#  10  headers honoured              download(..., "android", {X-Kelivo-Probe}) success; the server saw the header
#  11  headers malformed (not an object) download(..., "android", {"X-Bad":123})  ignored; still success (fail-open)
#  12  destination is a directory     download(url/ok.txt, D12DIR)              successful=false; "Error downloading file: <msg>" (write fails)
#
# WHY "NON-THROWING" IS THE THING THIS ROUND EXISTS FOR
#
# Every other Files method in this family throws on failure, and the acceptance drivers for them
# assert `THREW`. download must NOT: the reference implementation returns
# FileOperationData(successful = false, details = ...) on every failure path
# (StandardFileSystemTools.kt:4326-4495), and all nine in-repo callers branch on `.successful`
# (e.g. zhipu_draw.js:165-168). So the judgement here is inverted: a line that contains `THREW`
# is a FAILURE, and the expected outcome lives inside the answered JSON object. No case in this
# round may throw.
#
# The static branch that is NOT runtime-reachable: `"Download completed but file was not
# created"` (KelivoWorkspaceHost.fileDownload) fires only when the response was read and the
# destination still does not exist. Measured: every runtime path either writes the file (success)
# or lands in the catch (transport sentence), so the branch is defensive. It is asserted against
# the source in preflight (instruments()) instead of being faked with a runtime case that would
# not exercise it -- a judgement must not claim more than its sample covers.
FIX_SCRIPT_SRC=1  # marker: this driver carries its fixtures as scripts, not base64 blobs

PKG=${PKG:-com.psyche.kelivo.fusion}
FILES=${FILES:-/data/data/$PKG/files}
BASE=${BASE:-/sdcard/operit-selftest}
MARKER="$FILES/operit_selftest.txt"
DIAG="$FILES/operit_js_diag.log"
BB=${BB:-/data/adb/ksu/bin/busybox}

RD="$BASE/dl"
WEB="$RD/web"
CGI="$WEB/cgi-bin"
OUT="$RD/out"
HDRLOG="$RD/hdrs.txt"
PIDFILE="$RD/httpd.pid"

PORT=${PORT:-8765}
REFUSE=${REFUSE:-8766}
URL="http://127.0.0.1:$PORT"
BADURL="$URL/nope.txt"
REFUSEURL="http://127.0.0.1:$REFUSE/ok.txt"

D1="$OUT/c1"
D2="$OUT/deep/nested/c2"
D3="$OUT/c3"
D4="$OUT/c4"
D5="$OUT/c5"
D6="$OUT/c6"
D7="$OUT/c7"
D8="$OUT/c8"
D9="$OUT/c9"
D10="$OUT/c10"
D11="$OUT/c11"
D12DIR="$OUT/c12dir"

C_OK=ORDERFLOW-DOWNLOAD-OK-0123456789

need_root() {
    if [ "$(id -u)" != "0" ]; then
        echo "need root: the marker and the log live in $FILES" >&2
        exit 1
    fi
}

instruments() {
    bad=0
    for t in curl nc busybox; do
        if [ "$t" = "busybox" ]; then
            if [ ! -x "$BB" ]; then
                echo "FAIL no busybox at $BB -- the fixture server cannot start, so this round" >&2
                echo "     would test nothing. Stopping." >&2
                bad=1
            else
                echo "ok   instrument: busybox is $BB"
            fi
        elif ! command -v "$t" >/dev/null 2>&1; then
            echo "FAIL no $t on the device -- needed by this round. Stopping." >&2
            bad=1
        else
            echo "ok   instrument: $t is $(command -v "$t")"
        fi
    done
    # The defensive branch that no runtime case can reach is asserted here, against the source of
    # truth. If this string is gone, the branch was dropped and the driver should say so rather
    # than silently stop covering it.
    here=$(dirname "$0")
    src=""
    for cand in "$here/../android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt" \
                /sdcard/scripts/acceptance_download.sh; do
        [ -f "$cand" ] && src="$cand" && break
    done
    if [ -f "$here/../android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt" ]; then
        if grep -q 'Download completed but file was not created' \
            "$here/../android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt" 2>/dev/null; then
            echo "ok   instrument: the defensive 'file was not created' branch is present in source"
        else
            echo "warn cannot confirm the defensive branch in source (not building from the repo tree)" >&2
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
        # The decisive check: the dex literal says whether the new method is here. Same reasoning
        # as the unzip round -- APK builds are not reproducible, so a size/hash comparison proves
        # nothing.
        dex=/data/local/tmp/acceptance_probe_dl.dex
        unzip -p "$installed" 'classes*.dex' > "$dex" 2>/dev/null
        size=$(wc -c < "$dex" 2>/dev/null || echo 0)
        if [ "${size:-0}" -lt 100000 ]; then
            echo "warn cannot read the dex out of the installed apk -- build check skipped"
        else
            has_dl=$(grep -c -e 'Tools.Files.download' "$dex")
            if [ "$has_dl" -ge 1 ]; then
                echo "ok   installed build carries Tools.Files.download ($has_dl)"
            else
                echo "FAIL the installed build carries Tools.Files.download=$has_dl -- it predates" >&2
                echo "     the commit under test." >&2
                hard=1
            fi
        fi
        rm -f "$dex"
    fi

    op=$(appops get "$PKG" MANAGE_EXTERNAL_STORAGE 2>/dev/null)
    case "$op" in
        *allow*) echo "ok   MANAGE_EXTERNAL_STORAGE: allow" ;;
        *) echo "warn MANAGE_EXTERNAL_STORAGE not confirmed (${op:-no answer})" ;;
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

start_server() {
    # The fixtures are files + tiny CGI scripts, served by the device's own busybox httpd. The host
    # under test reaches 127.0.0.1:$PORT because it runs on the same device; the refused case uses
    # $REFUSE, where nothing is listening.
    "$BB" httpd -p "127.0.0.1:$PORT" -h "$WEB" >/dev/null 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1
}

stop_server() {
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null
        rm -f "$PIDFILE"
        echo "fixture server stopped"
    else
        echo "no fixture server pid recorded"
    fi
}

setup() {
    need_root
    preflight || {
        echo "aborting: fix what preflight flagged above, or set SKIP_PREFLIGHT=1." >&2
        exit 1
    }
    stop_server >/dev/null 2>&1
    rm -rf "$RD"
    mkdir -p "$OUT" "$CGI"

    # --- fixtures -------------------------------------------------------------------------------
    printf '%s' "$C_OK" > "$WEB/ok.txt"
    printf '%s' "$C_OK" > "$RD/.exp_ok"
    # and the size the file itself reports -- one source, so a re-cut fixture cannot drift.
    [ "$(wc -c < "$WEB/ok.txt" | tr -d ' ')" = "$(wc -c < "$RD/.exp_ok" | tr -d ' ')" ] || {
        echo "FAIL .exp_ok is not the size of ok.txt" >&2; exit 1; }

    cat > "$CGI/with_headers.sh" <<EOF
#!/system/bin/sh
env | grep '^HTTP_' > "$HDRLOG" 2>/dev/null
echo 'Content-Type: text/plain'
echo
echo 'HEADERS-CASE-BODY'
EOF
    cat > "$CGI/status500.sh" <<'EOF'
#!/system/bin/sh
echo 'Status: 500 Internal Test Error'
echo 'Content-Type: text/plain'
echo
echo 'boom'
EOF
    chmod 755 "$CGI/with_headers.sh" "$CGI/status500.sh"
    : > "$HDRLOG"

    # case 3's pre-existing destination, and its copy for the "the bytes are the server's" judgement
    printf '%s' 'stale-content' > "$D3"

    # case 12: a destination that exists as a DIRECTORY -- the open-for-write fails inside the try
    mkdir -p "$D12DIR"

    for d in "$D1" "$D2" "$D4" "$D5" "$D6" "$D7" "$D8" "$D9" "$D10" "$D11"; do
        if [ -e "$d" ]; then
            echo "FAIL destination $d already exists before the round -- aborting" >&2
            exit 1
        fi
    done

    start_server
    if ! curl -s -o /dev/null "$URL/ok.txt"; then
        echo "FAIL the fixture server on $URL did not answer -- stopping" >&2
        exit 1
    fi
    echo "ok   fixture server on $URL (web=$WEB)"

    mkdir -p "$FILES"
    cat > "$MARKER" <<EOF
#call host:Tools.Files.download ["$URL/ok.txt","$D1","android"]
#call host:Tools.Files.download ["$URL/ok.txt","$D2","android"]
#call host:Tools.Files.download ["$URL/ok.txt","$D3","android"]
#call host:Tools.Files.download ["ftp://example.invalid/x","$D4","android"]
#call host:Tools.Files.download ["","$D5","android"]
#call host:Tools.Files.download ["$URL/ok.txt","","android"]
#call host:Tools.Files.download ["$BADURL","$D7","android"]
#call host:Tools.Files.download ["$URL/cgi-bin/status500.sh","$D8","android"]
#call host:Tools.Files.download ["$REFUSEURL","$D9","android"]
#call host:Tools.Files.download ["$URL/cgi-bin/with_headers.sh","$D10","android",{"X-Kelivo-Probe":"yes"}]
#call host:Tools.Files.download ["$URL/ok.txt","$D11","android",{"X-Bad":123}]
#call host:Tools.Files.download ["$URL/ok.txt","$D12DIR","android"]
EOF

    if [ -f "$DIAG" ]; then
        wc -l < "$DIAG" 2>/dev/null | tr -d ' ' > "$BASE/.log_offset"
    else
        echo 0 > "$BASE/.log_offset"
    fi

    echo "destinations (none exist yet, except c3's stale file and c12's directory):"
    echo "  c1 .. c11; c12 $D12DIR (an existing DIRECTORY)"
    echo "now restart the app so configure() runs the marker, then: verify"
}

restart() {
    need_root
    am force-stop "$PKG"
    monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "relaunched $PKG -- open the JS tools screen if configure() does not run on launch"
}

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

# The log carries the answered object as a JSON *string*, so its quotes are backslash-escaped:
#   hostselftest Tools.Files.download -> "{\"successful\":true,\"details\":\"...\"}"
# Every judgement therefore reads an unescaped copy. (The unzip round could match `-> "{}"` raw
# because an empty object has no inner quotes; a payload with fields does.)
plain() {
    printf '%s' "$1" | tr -d '\\'
}

verify() {
    need_root
    if [ ! -f "$DIAG" ]; then
        echo "no $DIAG -- the marker never ran" >&2
        exit 1
    fi

    offset=0
    if [ -f "$BASE/.log_offset" ]; then
        offset=$(tr -d ' ' < "$BASE/.log_offset")
    fi
    case "${offset:-}" in
        '' | *[!0-9]*) offset=0 ;;
    esac

    round=$(tail -n +"$((offset + 1))" "$DIAG" | grep -e 'Tools.Files.download')
    out=$(printf '%s\n' "$round" | tail -12)
    n=$(printf '%s\n' "$round" | grep -c -e 'Tools.Files.download')
    if [ "$n" != "12" ]; then
        echo "warn this round wrote $n download lines, not 12. Each case is checked by its own" >&2
        echo "     payload, so a shift shows up in the cases it moves." >&2
    fi

    # Any `THREW` is a failure for this method. Counted once, up front.
    threw=$(printf '%s\n' "$out" | grep -c 'THREW')

    line() { printf '%s\n' "$out" | sed -n "${1}p"; }
    L1=$(plain "$(line 1)"); L2=$(plain "$(line 2)"); L3=$(plain "$(line 3)")
    L4=$(plain "$(line 4)"); L5=$(plain "$(line 5)"); L6=$(plain "$(line 6)")
    L7=$(plain "$(line 7)"); L8=$(plain "$(line 8)"); L9=$(plain "$(line 9)")
    L10=$(plain "$(line 10)"); L11=$(plain "$(line 11)"); L12=$(plain "$(line 12)")

    # A success line carries these three, always.
    is_ok() {
        case "$1" in *'"successful":true'*) ;; *) echo no; return ;; esac
        case "$1" in *'"operation":"download"'*) ;; *) echo no; return ;; esac
        case "$1" in *'"details":"File downloaded successfully: '* ) echo yes ;; *) echo no ;; esac
    }
    # A failure line carries successful=false and a details string with the wanted sentence.
    is_fail() { # is_fail <line> <sentence>
        case "$1" in *'"successful":false'*) ;; *) echo no; return ;; esac
        case "$1" in *"$2"*) echo yes ;; *) echo no ;; esac
    }

    # --- cases 1..3: success paths ------------------------------------------------------------------
    c1_bytes=$(cmp_ok "$D1" "$RD/.exp_ok"); c1=FAIL
    [ "$(is_ok "$L1")" = yes ] && [ "$c1_bytes" = intact ] && c1=PASS
    c2_bytes=$(cmp_ok "$D2" "$RD/.exp_ok"); c2=FAIL
    [ "$(is_ok "$L2")" = yes ] && [ "$c2_bytes" = intact ] && c2=PASS
    c3_bytes=$(cmp_ok "$D3" "$RD/.exp_ok"); c3=FAIL
    [ "$(is_ok "$L3")" = yes ] && [ "$c3_bytes" = intact ] && c3=PASS

    # --- case 4: scheme -----------------------------------------------------------------------------
    c4=$(is_fail "$L4" 'URL must start with http:// or https://')

    # --- cases 5/6: the two missing-parameter sentences ---------------------------------------------
    c5=$(is_fail "$L5" 'Either url or (visit_key + link_number/image_number) is required')
    c6=$(is_fail "$L6" 'URL and destination parameters are required')

    # --- cases 7/8/9: transport failures, answered not thrown ---------------------------------------
    c7=$(is_fail "$L7" 'Error downloading file: HTTP 404')
    c8=$(is_fail "$L8" 'Error downloading file: HTTP 500')
    c9=$(is_fail "$L9" 'Error downloading file: ')

    # --- case 10: headers honoured ------------------------------------------------------------------
    c10_seen=no
    [ -f "$HDRLOG" ] && grep -q -i 'X_KELIVO_PROBE' "$HDRLOG" 2>/dev/null && c10_seen=yes
    c10=FAIL
    [ "$(is_ok "$L10")" = yes ] && [ "$c10_seen" = yes ] && c10=PASS

    # --- case 11: malformed headers ignored (fail-open) ---------------------------------------------
    c11=FAIL
    [ "$(is_ok "$L11")" = yes ] && c11=PASS

    # --- case 12: the write fails -> answered, not thrown -------------------------------------------
    c12=$(is_fail "$L12" 'Error downloading file: ')

    c13=FAIL
    [ "$threw" = "0" ] && c13=PASS

    echo "case  call                                expected                                       actual"
    printf '%-5s %-37s %-46s %s\n' 1 '(plain)' 'success; bytes identical' "success=$(is_ok "$L1") bytes=$c1_bytes -> $c1"
    printf '%-5s %-37s %-46s %s\n' 2 '(missing chain)' 'success; parents created' "success=$(is_ok "$L2") bytes=$c2_bytes -> $c2"
    printf '%-5s %-37s %-46s %s\n' 3 '(overwrite)' 'success; bytes identical' "success=$(is_ok "$L3") bytes=$c3_bytes -> $c3"
    printf '%-5s %-37s %-46s %s\n' 4 '(scheme ftp)' 'successful=false; URL must start with...' "-> $c4"
    printf '%-5s %-37s %-46s %s\n' 5 '(url blank)' 'successful=false; Either url or...' "-> $c5"
    printf '%-5s %-37s %-46s %s\n' 6 '(dest blank)' 'successful=false; URL and destination...' "-> $c6"
    printf '%-5s %-37s %-46s %s\n' 7 '(404)' 'successful=false; ...HTTP 404' "-> $c7"
    printf '%-5s %-37s %-46s %s\n' 8 '(500)' 'successful=false; ...HTTP 500' "-> $c8"
    printf '%-5s %-37s %-46s %s\n' 9 '(refused)' 'successful=false; Error downloading file:' "-> $c9"
    printf '%-5s %-37s %-46s %s\n' 10 '(headers ok)' 'success; server saw the header' "success=$(is_ok "$L10") server_saw=$c10_seen -> $c10"
    printf '%-5s %-37s %-46s %s\n' 11 '(headers bad)' 'success; headers ignored' "success=$(is_ok "$L11") -> $c11"
    printf '%-5s %-37s %-46s %s\n' 12 '(dest is dir)' 'successful=false; Error downloading file:' "-> $c12"
    printf '%-5s %-37s %-46s %s\n' 13 '(non-throwing)' 'no case threw' "threw=$threw -> $c13"

    echo
    echo "evidence (last 12 of $n download lines this round, log offset $offset):"
    printf '%s\n' "$out" | sed 's/^/  /'

    echo
    if [ "$c1" = PASS ] && [ "$c2" = PASS ] && [ "$c3" = PASS ] && [ "$c4" = PASS ] &&
        [ "$c5" = PASS ] && [ "$c6" = PASS ] && [ "$c7" = PASS ] && [ "$c8" = PASS ] &&
        [ "$c9" = PASS ] && [ "$c10" = PASS ] && [ "$c11" = PASS ] && [ "$c12" = PASS ] &&
        [ "$c13" = PASS ]; then
        echo "all cases PASS (12 runtime + 1 non-throwing)."
        return 0
    fi
    echo "not all passing -- see the rows above." >&2
    [ "$c1" = FAIL ] && echo "  case 1: wanted successful=true, bytes identical, details template" >&2
    [ "$c2" = FAIL ] && echo "  case 2: wanted the missing chain created and a success, got bytes=$c2_bytes" >&2
    [ "$c3" = FAIL ] && echo "  case 3: wanted the existing file overwritten, got bytes=$c3_bytes" >&2
    [ "$c4" = FAIL ] && echo "  case 4: wanted 'URL must start with http:// or https://'" >&2
    [ "$c5" = FAIL ] && echo "  case 5: wanted 'Either url or (visit_key + link_number/image_number) is required'" >&2
    [ "$c6" = FAIL ] && echo "  case 6: wanted 'URL and destination parameters are required'" >&2
    [ "$c7" = FAIL ] && echo "  case 7: wanted 'Error downloading file: HTTP 404'" >&2
    [ "$c8" = FAIL ] && echo "  case 8: wanted 'Error downloading file: HTTP 500'" >&2
    [ "$c9" = FAIL ] && echo "  case 9: wanted 'Error downloading file: <msg>' for a refused connection" >&2
    [ "$c10" = FAIL ] && echo "  case 10: wanted a success AND the server to have seen X-Kelivo-Probe (log=$HDRLOG)" >&2
    [ "$c11" = FAIL ] && echo "  case 11: wanted a success with malformed headers ignored (fail-open)" >&2
    [ "$c12" = FAIL ] && echo "  case 12: wanted 'Error downloading file: <msg>' for a destination that is a directory" >&2
    [ "$c13" = FAIL ] && echo "  case 13 (the round's key case): wanted ZERO THREW lines; this method answers failures." >&2
    return 1
}

case "${1:-}" in
    preflight) need_root; preflight ;;
    setup) setup ;;
    restart) restart ;;
    verify) verify ;;
    stop) stop_server ;;
    *) sed -n '2,40p' "$0" ; exit 1 ;;
esac
