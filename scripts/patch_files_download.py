#!/usr/bin/env python3
"""Map Tools.Files.download onto KelivoHost.fileDownload.

Measured, not assumed:
  files.d.ts:240        download(url, destination, environment?, headers?): Promise<FileOperationData>
  files.d.ts:242        the options overload (visit_key / link_number / image_number) -- see below
  results.d.ts:143      FileOperationData { env, operation, path, successful, details }
  StandardFileSystemTools.kt:4285-4497   the reference implementation.
                        It returns FileOperationData(operation="download", path, successful,
                        details) on EVERY path -- validation, transport error and success --
                        and never throws. Failure sentences (quoted, not paraphrased):
                          "Either url or (visit_key + link_number/image_number) is required"
                          "Invalid visit key."
                          "Index out of bounds."
                          "URL and destination parameters are required"
                          "URL must start with http:// or https://"
                          "Download completed but file was not created"
                          "Error downloading file: <e.message>"
                        Success sentence:
                          "File downloaded successfully: <url> -> <dest> (file size: <size>)"
                        Parent directory mkdirs when missing (:4423-4426); headers are parsed
                        inside a try/catch and fall back to an empty map (:4298-4312); an
                        existing destination is overwritten (no guard).

The caller surface (assets/operit_packages/), all nine of it, is positional and reads
`successful` / `details`:
  minimax_draw.js:547, nanobanana_draw.js:590, openai_draw.js:198, qwen_draw.js:321,
  siliconflow_draw.js:439 and :509, xai_draw.js:474 and :547, zhipu_draw.js:165
  e.g. zhipu_draw.js:165-168 -- `if (!downloadResult.successful) throw ... details`.
Options-object calls: 0. headers calls: 0.

Rulings this patch implements (the round's, in the repo's voice):
  * R2 -- download is NOT in `throwingMethods`. The reference never throws and all nine callers
    branch on `.successful`; putting it in the set would make that branch unreachable and let
    the dispatcher's catch downgrade `details` to a generic error. It joins read / list / info
    on the answering side.
  * R3 -- the options overload is NOT implemented, and is declared-absent on purpose (the
    visit_key form is backed upstream by a browser-visit cache this host has no equivalent for,
    `StandardFileSystemTools.kt:4340`; 0 callers). A blank url answers the reference
    implementation's own sentence instead of silently mis-reading an options object. This is a
    recorded gap, not a silent hole.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IFACE = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/KelivoHost.kt"
DISP = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/quickjs/OperitHostDispatcher.kt"
HOST = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo/workspace/KelivoWorkspaceHost.kt"


class Edit:
    def __init__(self, path: Path, label: str, anchor: str, replacement: str):
        self.path = path
        self.label = label
        self.anchor = anchor
        self.replacement = replacement


# --- KelivoHost.kt: the interface declaration -----------------------------------------------
# `fileUnzip` is the last declaration in the file. The anchor is inserted before the closing
# brace of the interface, and the anchor line itself stays put.
IFACE_ANCHOR = (
    "    fun fileUnzip(source: String, destination: String): JSONObject"
)
IFACE_DOWNLOAD = """

    /**
     * Downloads [url] to [destination], answering a `FileOperationData`-shaped object.
     *
     * **A failure is answered, not thrown.** The reference implementation returns
     * `FileOperationData(operation = "download", path, successful = false, details)` on every
     * failure path (`StandardFileSystemTools.kt:4326-4495`), and every in-repo caller branches
     * on `successful` / reads `details` (`zhipu_draw.js:165-168` and eight siblings), so this
     * member is deliberately **not** in the dispatcher's `throwingMethods` -- it sits with
     * [fileRead] / [fileList] / [fileInfo], not with [fileDelete] / [fileWriteBinary]. The
     * answered keys are `operation`, `env`, `path`, `successful`, `details`; the last two are
     * the ones the JS reads.
     *
     * Only `http://` and `https://` are accepted; anything else is refused with the reference
     * tool's own sentence (`"URL must start with http:// or https://"`). The parent directory of
     * [destination] is created when missing and an existing file is overwritten -- neither more
     * nor less than the reference tool. A [headers] object is applied as request properties, and
     * a malformed one is ignored rather than refused (fail-open, matching `:4298-4312`).
     *
     * Implemented with `java.net.HttpURLConnection` and no new dependency: the Android module
     * carries no HTTP client at all (0 hits for `HttpURLConnection` / `okhttp` / `retrofit` /
     * `ktor` / `volley`), and the manifest already allows cleartext (`AndroidManifest.xml:5`
     * INTERNET, `:50 usesCleartextTraffic="true"`).
     *
     * **Not implemented on purpose: the options overload.** `files.d.ts:242` also declares
     * `download({ url?, visit_key?, link_number?, image_number?, destination, environment?,
     * headers? })`; its `visit_key` / `link_number` / `image_number` form is backed upstream by a
     * browser-visit cache (`StandardWebVisitTool.getCachedVisitResult`, `:4340`) that this host
     * has no equivalent for, and nothing under `assets/operit_packages/` calls that form (0
     * hits). It is therefore absent here **and said so**, rather than left as a form that looks
     * usable and is not: a call with a blank url answers the reference tool's own sentence. This
     * is a recorded gap -- see the download round's handoff note.
     *
     * **Not promised:** progress reporting, segmented download, retries, resume, size limits,
     * timeout tuning, or any property of the bytes beyond "the response body was written to
     * [destination]".
     */
    fun fileDownload(
        url: String,
        destination: String,
        environment: String?,
        headers: JSONObject?,
    ): JSONObject"""

# --- OperitHostDispatcher.kt: the branch ----------------------------------------------------
DISP_ANCHOR = """                "Tools.Files.zip" -> {"""
DISP_DOWNLOAD = """                "Tools.Files.download" -> {
                    // Positional form: download(url, destination, environment?, headers?).
                    // `environment` is read only to skip a null slot -- one host, one namespace,
                    // nothing to route on (same stance as Files.unzip above). `headers` arrives
                    // as an object when the caller supplies one, and null otherwise.
                    //
                    // No index arithmetic to get wrong the way the zip round did: there is no
                    // boolean between destination and environment here.
                    val a = args ?: JSONArray()
                    host.fileDownload(
                        a.optString(0),
                        a.optString(1),
                        if (a.isNull(2)) null else a.optString(2),
                        a.optJSONObject(3),
                    ).toString()
                }
                "Tools.Files.zip" -> {"""

# --- KelivoWorkspaceHost.kt: imports --------------------------------------------------------
HOST_IMPORT_ANCHOR = """import java.io.RandomAccessFile"""
HOST_IMPORT_DOWNLOAD = """import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL"""

# --- KelivoWorkspaceHost.kt: the implementation ---------------------------------------------
HOST_IMPL_ANCHOR = """    private fun collectZipEntries(source: File, prefix: String, out: MutableList<Pair<String, File>>) {"""
HOST_IMPL_DOWNLOAD = '''    override fun fileDownload(
        url: String,
        destination: String,
        environment: String?,
        headers: JSONObject?,
    ): JSONObject {
        // `environment` is deliberately not read (one host, one namespace), and `headers` is
        // already a JSONObject by the time it arrives.
        //
        // Unlike every other Files method, this one ANSWERS a failure instead of throwing it.
        // That is the measured contract, not a preference: the reference implementation returns
        // FileOperationData(successful = false, details = ...) on every failure path
        // (StandardFileSystemTools.kt:4326-4495), and all nine in-repo callers branch on
        // `.successful` / read `.details` (zhipu_draw.js:165-168 and eight siblings).
        if (url.isBlank()) {
            // The options overload (visit_key + link_number/image_number) is not implemented
            // (R3); a blank url therefore lands on the reference implementation's own sentence
            // for "no url and no usable options object".
            return downloadFailure(
                destination,
                "Either url or (visit_key + link_number/image_number) is required",
            )
        }
        if (destination.isBlank()) {
            return downloadFailure(destination, "URL and destination parameters are required")
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            return downloadFailure(destination, "URL must start with http:// or https://")
        }
        val dest = File(destination)
        // Parent created when missing, as the reference tool does; an existing destination is
        // overwritten (the reference tool has no guard for it either).
        dest.parentFile?.let { if (!it.exists()) it.mkdirs() }
        try {
            val connection = URL(url).openConnection() as HttpURLConnection
            connection.connectTimeout = 15_000
            connection.readTimeout = 60_000
            connection.instanceFollowRedirects = true
            applyDownloadHeaders(connection, headers)
            connection.requestMethod = "GET"
            val code = connection.responseCode
            if (code < 200 || code > 299) {
                return downloadFailure(destination, "Error downloading file: HTTP $code")
            }
            connection.inputStream.use { input ->
                FileOutputStream(dest).use { output ->
                    input.copyTo(output)
                }
            }
        } catch (t: Throwable) {
            // The damaged side is named the way the reference tool names it.
            return downloadFailure(destination, "Error downloading file: ${t.message}")
        }
        if (!dest.exists()) {
            return downloadFailure(destination, "Download completed but file was not created")
        }
        return JSONObject()
            .put("operation", "download")
            .put("env", "android")
            .put("path", destination)
            .put("successful", true)
            .put(
                "details",
                "File downloaded successfully: $url -> $destination (file size: ${formatSize(dest.length())})",
            )
    }

    /**
     * Copies [headers] onto [connection], ignoring anything that cannot be read.
     *
     * The reference implementation parses the headers parameter inside a try/catch and falls
     * back to an empty map when it cannot (`StandardFileSystemTools.kt:4298-4312`), so a
     * malformed headers value is fail-open there and fail-open here: a request with fewer
     * headers is still attempted rather than refused.
     */
    private fun applyDownloadHeaders(connection: HttpURLConnection, headers: JSONObject?) {
        if (headers == null) return
        try {
            val keys = headers.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                connection.setRequestProperty(key, headers.getString(key))
            }
        } catch (_: Throwable) {
            // Deliberately swallowed: see above. Whatever was copied before the bad entry stays.
        }
    }

    private fun downloadFailure(path: String, details: String): JSONObject =
        JSONObject()
            .put("operation", "download")
            .put("env", "android")
            .put("path", path)
            .put("successful", false)
            .put("details", details)

    private fun formatSize(bytes: Long): String = when {
        bytes > 1024 * 1024 -> String.format("%.2f MB", bytes / (1024.0 * 1024.0))
        bytes > 1024 -> String.format("%.2f KB", bytes / 1024.0)
        else -> "$bytes bytes"
    }

'''  # noqa: E501

EDITS = [
    Edit(IFACE, "interface: fileDownload declaration", IFACE_ANCHOR, IFACE_ANCHOR + IFACE_DOWNLOAD),
    Edit(DISP, "dispatcher: download branch", DISP_ANCHOR, DISP_DOWNLOAD),
    Edit(HOST, "workspace host: java.net imports", HOST_IMPORT_ANCHOR, HOST_IMPORT_DOWNLOAD),
    Edit(HOST, "workspace host: fileDownload implementation", HOST_IMPL_ANCHOR, HOST_IMPL_DOWNLOAD + HOST_IMPL_ANCHOR),
]


def git(*args: str) -> str:
    return subprocess.run(
        ("git",) + args, cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def main() -> None:
    # --- Pass 1: every anchor unique in its own file, before anything touches disk ----------
    for edit in EDITS:
        text = edit.path.read_text(encoding="utf-8")
        n = text.count(edit.anchor)
        if n != 1:
            raise SystemExit(f"{edit.path.name}: {edit.label}: expected 1 anchor, found {n}")

    before = {p: p.read_text(encoding="utf-8") for p in {e.path for e in EDITS}}

    # --- Pass 2: write ----------------------------------------------------------------------
    # Accumulated per file, not per edit: two of these files take more than one edit, and
    # writing "the original text with this one edit applied" each time leaves only the last
    # standing. The unzip round's dry run caught exactly that.
    working = dict(before)
    for edit in EDITS:
        text = working[edit.path]
        if edit.anchor not in text:
            raise SystemExit(f"{edit.path.name}: {edit.label}: anchor lost while accumulating")
        working[edit.path] = text.replace(edit.anchor, edit.replacement, 1)
    for path, text in working.items():
        path.write_text(text, encoding="utf-8")

    # --- Pass 3: self-check -----------------------------------------------------------------
    after = {p: p.read_text(encoding="utf-8") for p in before}
    results: list[tuple[str, object, object]] = []

    for edit in EDITS:
        if edit.anchor not in edit.replacement:
            results.append((f"anchor gone: {edit.label}", edit.anchor in after[edit.path], False))
        results.append((
            f"replacement present: {edit.label}",
            edit.replacement in after[edit.path],
            True,
        ))

    iface = after[IFACE]
    results.append(("interface: fileDownload declared", "fun fileDownload(" in iface, True))
    results.append(("interface: answers, does not throw (R2 stated)", "A failure is answered, not thrown." in iface, True))
    results.append(("interface: R2 names throwingMethods rejection", "not** in the dispatcher's `throwingMethods`" in iface, True))
    results.append(("interface: R3 options overload declared-absent", "Not implemented on purpose: the options overload." in iface, True))
    results.append(("interface: unsupported scheme sentence quoted", "URL must start with http:// or https://" in iface, True))
    results.append(("interface: headers fail-open promised", "fail-open" in iface, True))
    results.append(("interface: not-promised list present", "segmented download" in iface and "resume" in iface, True))

    host = after[HOST]
    results.append(("host: HttpURLConnection imported", "import java.net.HttpURLConnection" in host, True))
    results.append(("host: java.net.URL imported", "import java.net.URL" in host, True))
    results.append(("host: scheme refused with the reference sentence", '"URL must start with http:// or https://"' in host, True))
    results.append(("host: blank url answers the options sentence", "Either url or (visit_key + link_number/image_number) is required" in host, True))
    results.append(("host: parent mkdirs when missing", "dest.parentFile?.let { if (!it.exists()) it.mkdirs() }" in host, True))
    results.append(("host: non-2xx answered, not thrown", "if (code < 200 || code > 299) {" in host, True))
    results.append(("host: transport error answered", 'return downloadFailure(destination, "Error downloading file: ${t.message}")' in host, True))
    results.append(("host: success carries the reference sentence", "File downloaded successfully: $url -> $destination" in host, True))
    results.append(("host: headers applied fail-open", "private fun applyDownloadHeaders(" in host, True))
    results.append(("host: five answered keys present", all(k in host for k in ['"operation"', '"env"', '"path"', '"successful"', '"details"']), True))

    disp = after[DISP]
    results.append(("dispatcher: download branch mapped", '"Tools.Files.download" -> {' in disp, True))
    results.append(("dispatcher: download NOT in throwingMethods (R2)", '\n            "Tools.Files.download",\n' not in disp, True))
    results.append(("dispatcher: branch reads index 0/1 and optional 2/3", "host.fileDownload(\n                        a.optString(0),\n                        a.optString(1),\n                        if (a.isNull(2)) null else a.optString(2),\n                        a.optJSONObject(3),\n                    )" in disp, True))

    # The diff itself: every removed line must belong to an anchor.
    anchor_lines = {ln for e in EDITS for ln in e.anchor.splitlines()}
    for path in sorted({e.path for e in EDITS}):
        diff = git("diff", "-U0", "--", str(path.relative_to(ROOT)))
        removed = [ln[1:] for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---")]
        stray = [ln for ln in removed if ln.strip() and ln not in anchor_lines]
        results.append((f"diff: {path.name}: only anchors were replaced", len(stray), 0))
        added = [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        results.append((f"diff: {path.name}: something was added", len(added) > 0, True))

    bad = 0
    for label, got, want in results:
        ok = got == want
        if not ok:
            bad += 1
        print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r} (wanted {want!r})")
    print()
    print(f"self-checks: {len(results) - bad}/{len(results)} green")
    if bad:
        raise SystemExit(1)
    print("PATCH APPLIED")


if __name__ == "__main__":
    main()
