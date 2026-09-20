#!/usr/bin/env python3
"""Map Tools.Files.unzip onto KelivoHost.fileUnzip.

Measured, not assumed:
  extended_file_tools.js:63-70   unzip_files(source, destination, environment) --
                                 environment is the only optional parameter, there is no
                                 boolean. The zip round's isNull(3) trap has no analogue here.
  extended_file_tools.js:111-113 the only reader: `!!result` -> {success, message, data}.
                                 No field is read, so the answer is the family's `{}`.
  operit_editor.js:2810          the only real call site, inside resolve_toolpkg_source:
                                 `await Tools.Files.unzip(sourcePath, tempExtractDir, "android")`
                                 -- a bare await, result discarded, environment a string
                                 literal, and the destination is created one line earlier
                                 (:2809 ensure_android_directory -> Tools.Files.mkdir, already
                                 mapped at OperitHostDispatcher.kt:79-80).
  operit_editor.js:2814,2820-22  the consumer: the manifest must be found at the extraction
                                 ROOT, and the main entry must exist under it.
  extended_file_tools.js:143     the package's own self test skips this tool on purpose.

Device-side behaviour, probed rather than assumed (/sdcard/scripts/probe_zipslip.sh and
probe_zipslip2.sh, outputs kept at /sdcard/up_zipslip.out and /sdcard/up2_zipslip.out):
  * /system/bin/unzip REFUSES a member named "../escaped.txt", "/escaped_abs.txt" and
    "a/../../escaped_deep.txt" with `unzip: bad filename <name>`, exit 1, and writes nothing
    outside the target.
  * but it is a STREAMING extractor: in an archive of benign / hostile / benign it wrote the
    first (benign) member, then refused, leaving a PARTIAL destination and dropping the last
    (benign) member. Nothing escaped.
So the reference tool is fail-closed per entry and fail-open on the prefix. This host can be
strictly better because the archive is a seekable File: the entry table is read first and any
unsafe name refuses the whole call BEFORE anything is created. That is a promise the KDoc makes
and the acceptance driver measures (a benign member before the hostile one must NOT be on disk).

Rulings this patch implements (the round's, in the repo's voice):
  * destination is a file -> IllegalArgumentException "EISDIR: destination is a file, not a
    directory: <dst>", the same sentence fileMove uses for the same shape.
  * a symbolic-link member -> refused as an unsafe entry name, together with ".." and absolute
    names: a .toolpkg has no legitimate use for a link and a link target is the same escape in
    different clothes. java.util.zip does not expose the unix mode, so the central directory is
    read directly (external attributes, st_mode in the high 16 bits) -- and if that table cannot
    be read, the call refuses rather than guessing: no entry table, no extraction.
  * an empty archive -> success, no work: mkdirs the destination and answer {}. An empty input
    is not an error anywhere else in this family either (readBinary, writeBinary).
  * an archive inside its own destination -> IllegalArgumentException "source is inside
    destination: <src> under <dst>". This is the REVERSE of fileZip's guard, not a copy of it:
    there the packed tree contains the archive, here the destination contains the archive being
    read, and the two shapes need opposite predicates.
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
# The file ends on this declaration and has no trailing newline. Both the anchor and the
# replacement end without one, so that quirk is preserved rather than "fixed".
IFACE_ANCHOR = (
    "    fun fileZip(source: String, destination: String, includeRootDirectory: Boolean): JSONObject"
)
IFACE_UNZIP = """

    /**
     * Extracts a ZIP archive into [destination], answering `{}`.
     *
     * Signature and answer are the measured ones: the only call site
     * (`operit_editor.js:2810`, the `.toolpkg` install path) discards the result, and the
     * package wrapper only tests `!!result` (`extended_file_tools.js:111-113`), so no field is
     * invented for either of them to ignore.
     *
     * **Nothing is written when an entry name is unsafe.** The entry table is read first and
     * every name is checked -- a `..` segment, an absolute name, or a symbolic-link entry --
     * and the call is refused with `IllegalArgumentException("unsafe entry name: <name>")`
     * before the destination is touched at all. The device's own `/system/bin/unzip` refuses
     * those names too, but only as it reaches them, so an archive with a benign member first
     * leaves that member behind and drops what follows (probed: a benign / hostile / benign
     * archive extracts the first member, then exits 1). The archive here is a seekable file,
     * so this implementation can be stricter than the reference tool and does not leave a
     * partial destination behind. A symbolic-link entry belongs to the same family as `..`:
     * a `.toolpkg` has no legitimate use for one, and a link target is the same escape wearing
     * different clothes.
     *
     * [destination] is created if it does not exist (`mkdirs`), which is what the model-facing
     * path needs: `extended_file_tools.js:112` passes the caller's path through untested,
     * while the one real caller creates the directory itself one line before calling
     * (`operit_editor.js:2809`). A [destination] that exists as a **file** is refused with
     * `IllegalArgumentException("EISDIR: destination is a file, not a directory: <dst>")`,
     * which is [fileMove]'s sentence for the same shape.
     *
     * **A source inside its own destination is refused**, with
     * `IllegalArgumentException("source is inside destination: <src> under <dst>")`. That is
     * the reverse of [fileZip]'s guard rather than a copy of it: there the packed tree
     * contains the archive, here the destination contains the archive being read, and reading
     * a file while overwriting files around it is the same self-reference in the other
     * direction.
     *
     * An **empty archive** is not an error: the destination is created and `{}` is answered,
     * the same stance [fileReadBinary] and [fileWriteBinary] take on empty input.
     *
     * **Not promised:** permission bits, timestamps, zip64, encrypted archives, or any
     * property of the extracted files beyond their contents. The only consumer that was read
     * needs the manifest to appear at the extraction root (`operit_editor.js:2814`) and the
     * main entry to exist under it (`:2820-2822`), so that is the contract; entry order,
     * compression method and attributes are not.
     */
    fun fileUnzip(source: String, destination: String): JSONObject"""

# --- OperitHostDispatcher.kt: the branch ----------------------------------------------------
DISP_ANCHOR = """                "Tools.Files.zip" -> {"""
DISP_UNZIP = """                "Tools.Files.unzip" -> {
                    // args[2] would be `environment`; deliberately not read, as in the rest of
                    // this family -- one host, one namespace, nothing to route on.
                    //
                    // Note the shape: unzip_files(source, destination, environment)
                    // (extended_file_tools.js:112) has NO boolean, so unlike Files.zip there is
                    // no index to get wrong here. The zip round learned that lesson the hard
                    // way -- a marker that leaves the environment slot out moves every later
                    // argument one index left, and the host then reads the default instead of
                    // the caller's value.
                    val a = args ?: JSONArray()
                    host.fileUnzip(
                        a.optString(0),
                        a.optString(1),
                    ).toString()
                }
                "Tools.Files.zip" -> {"""

# --- OperitHostDispatcher.kt: the throwing list ---------------------------------------------
DISP_THROW_ANCHOR = """            "Tools.Files.move",
            "Tools.Files.zip","""
DISP_THROW_UNZIP = """            "Tools.Files.move",
            "Tools.Files.zip",
            "Tools.Files.unzip","""

# --- KelivoWorkspaceHost.kt: imports --------------------------------------------------------
HOST_IMPORT_ANCHOR = """import java.io.FileOutputStream
import java.io.IOException"""
HOST_IMPORT_UNZIP = """import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile"""

HOST_ZIP_IMPORT_ANCHOR = """import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream"""
HOST_ZIP_IMPORT_UNZIP = """import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream"""

# --- KelivoWorkspaceHost.kt: the implementation ---------------------------------------------
HOST_IMPL_ANCHOR = """    private fun collectZipEntries(source: File, prefix: String, out: MutableList<Pair<String, File>>) {"""
HOST_IMPL_UNZIP = '''    override fun fileUnzip(source: String, destination: String): JSONObject {
        val src = File(source)
        val dst = File(destination)
        // Same zero-validation stance as every other Files method here: both paths are the
        // caller's absolute paths, and there is no workspace root to check them against.
        if (!src.exists()) {
            throw FileNotFoundException("ENOENT: no such file or directory: $source")
        }
        // The reverse of fileZip's guard, and deliberately not its code. There the source tree
        // contains the archive being written; here the destination contains the archive being
        // read, so the predicate looks the other way: refuse when the source lies inside the
        // destination. Reading a file while writing files around it is self-referential in
        // exactly the same way, and the outcome would depend on filesystem timing.
        val srcPath = src.canonicalOrAbsolute()
        val dstPath = dst.canonicalOrAbsolute()
        if (srcPath == dstPath || srcPath.startsWith("$dstPath/")) {
            throw IllegalArgumentException(
                "source is inside destination: $source under $destination",
            )
        }
        // A destination that exists as a file cannot receive a tree. The sentence is
        // fileMove's, for the same shape -- the family names a wrongly-typed destination with
        // EISDIR and is not going to invent a second spelling for it.
        if (dst.exists() && !dst.isDirectory) {
            throw IllegalArgumentException(
                "EISDIR: destination is a file, not a directory: $destination",
            )
        }
        // The entry table is read BEFORE anything is created, so an unsafe name refuses the
        // whole call and leaves the destination untouched. That is the one place this
        // implementation is stricter than the device's own unzip, which refuses per entry and
        // therefore leaves the members it already wrote (probed: benign / hostile / benign
        // extracts the first member and then exits 1). An unreadable entry table is refused
        // too: no table, no extraction.
        val table = readZipEntryTable(src)
            ?: throw IllegalArgumentException("unsafe entry name: <unreadable entry table> in $source")
        for ((name, mode) in table) {
            if (isUnsafeZipEntry(name, mode)) {
                throw IllegalArgumentException("unsafe entry name: $name")
            }
        }
        dst.mkdirs()
        try {
            ZipFile(src).use { zip ->
                val entries = zip.entries()
                while (entries.hasMoreElements()) {
                    val entry = entries.nextElement()
                    val target = File(dst, entry.name)
                    if (entry.isDirectory) {
                        target.mkdirs()
                        continue
                    }
                    target.parentFile?.mkdirs()
                    zip.getInputStream(entry).use { input ->
                        BufferedOutputStream(FileOutputStream(target)).use { output ->
                            input.copyTo(output)
                        }
                    }
                }
            }
        } catch (t: Throwable) {
            // Names the damaged side, as the rest of the family does: the source is intact and
            // may be re-read, the destination may now hold a partial extraction.
            throw IOException("EIO: cannot extract: $destination: ${t.message}", t)
        }
        // An empty archive lands here with the destination created and nothing in it. Empty
        // input is not an error -- the same reading fileReadBinary and fileWriteBinary take.
        return JSONObject()
    }

    /**
     * Reads the central directory and returns (name, unix mode) for every entry, or null when
     * the table cannot be read.
     *
     * java.util.zip exposes neither the external attributes nor the unix mode, and the mode is
     * the only way to tell a symbolic-link entry from a regular file -- `ZipEntry.isDirectory`
     * cannot, and an entry that is a link would otherwise be extracted as a small regular file
     * containing its target. So the table is walked at byte level:
     *
     *   0x02014b50  central file header signature
     *   offset 28   file name length        (2 bytes)
     *   offset 30   extra field length      (2 bytes)
     *   offset 32   file comment length     (2 bytes)
     *   offset 38   external file attributes(4 bytes; st_mode in the high 16 bits for unix)
     *   total       46 + name + extra + comment
     *
     * The end-of-central-directory record (0x06054b50) is searched from the end of the file
     * over the largest comment a ZIP may carry. Anything unexpected -- a missing record, a
     * header that runs past the end, a name that is not valid UTF-8 -- answers null, and the
     * caller refuses: a guessed table would be a fail-open.
     */
    private fun readZipEntryTable(zipFile: File): List<Pair<String, Int>>? {
        val out = ArrayList<Pair<String, Int>>()
        RandomAccessFile(zipFile, "r").use { raf ->
            val length = raf.length()
            // 22 is the smallest possible end-of-central-directory record; a file shorter than
            // that cannot be a ZIP at all. The search window is that record plus the largest
            // comment a ZIP may carry (65535). Both are spelled out here rather than parked in
            // the class's companion object: this class already has one and Kotlin allows only
            // one, and a private constant used twice is not worth a second file-level home.
            if (length < 22) return null
            val window = minOf(length, 65535L + 22L).toInt()
            val buffer = ByteArray(window)
            raf.seek(length - window)
            raf.readFully(buffer)
            var eocd = -1
            var i = window - 22
            while (i >= 0) {
                if (buffer[i] == 0x50.toByte() && buffer[i + 1] == 0x4b.toByte() &&
                    buffer[i + 2] == 0x05.toByte() && buffer[i + 3] == 0x06.toByte()
                ) {
                    eocd = i
                    break
                }
                i--
            }
            if (eocd < 0) return null
            val total = le16(buffer, eocd + 10)
            var offset = le32(buffer, eocd + 16).toLong()
            if (offset < 0 || offset >= length) return null
            repeat(total) {
                val header = ByteArray(46)
                raf.seek(offset)
                if (raf.read(header) != 46) return null
                if (le32(header, 0) != 0x02014b50) return null
                val nameLength = le16(header, 28)
                val extraLength = le16(header, 30)
                val commentLength = le16(header, 32)
                val attributes = le32(header, 38)
                val nameBytes = ByteArray(nameLength)
                if (raf.read(nameBytes) != nameLength) return null
                val name = String(nameBytes, StandardCharsets.UTF_8)
                // A name that is not valid UTF-8 comes back with replacement characters, and a
                // replacement character is itself a reason to refuse rather than to guess.
                if (name.contains('\\uFFFD')) return null
                out.add(name to (attributes ushr 16))
                offset += 46L + nameLength + extraLength + commentLength
                if (offset > length) return null
            }
        }
        return out
    }

    private fun isUnsafeZipEntry(name: String, mode: Int): Boolean {
        if (name.isEmpty()) return true
        if (name.startsWith("/")) return true
        if (name.split('/').any { it == ".." }) return true
        // 0xA000 is S_IFLNK. The mode is only meaningful when the archive came from a unix
        // writer; a DOS-writer archive carries 0 there and is judged on its name alone.
        return (mode and 0xF000) == 0xA000
    }

    private fun le16(bytes: ByteArray, at: Int): Int =
        (bytes[at].toInt() and 0xFF) or ((bytes[at + 1].toInt() and 0xFF) shl 8)

    private fun le32(bytes: ByteArray, at: Int): Int =
        le16(bytes, at) or (le16(bytes, at + 2) shl 16)

'''  # noqa: E501

EDITS = [
    Edit(IFACE, "interface: fileUnzip declaration", IFACE_ANCHOR, IFACE_ANCHOR + IFACE_UNZIP),
    Edit(DISP, "dispatcher: unzip branch", DISP_ANCHOR, DISP_UNZIP),
    Edit(DISP, "dispatcher: throwingMethods member", DISP_THROW_ANCHOR, DISP_THROW_UNZIP),
    Edit(HOST, "workspace host: java.io imports", HOST_IMPORT_ANCHOR, HOST_IMPORT_UNZIP),
    Edit(HOST, "workspace host: java.util.zip imports", HOST_ZIP_IMPORT_ANCHOR, HOST_ZIP_IMPORT_UNZIP),
    Edit(HOST, "workspace host: fileUnzip implementation", HOST_IMPL_ANCHOR, HOST_IMPL_UNZIP + HOST_IMPL_ANCHOR),
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
    iface_tail_before = before[IFACE].endswith("\n")

    # --- Pass 2: write ----------------------------------------------------------------------
    # Accumulated per file, not per edit: three of these files take more than one edit, and
    # writing "the original text with this one edit applied" each time leaves only the last edit
    # standing. The dry run in the scratch tree caught exactly that -- the dispatcher branch and
    # the two import lines were silently dropped.
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
        # Some replacements are built ON the anchor (the interface declaration, the throwing
        # list, the implementation), so "the anchor must be gone" is only a real check for the
        # edits that consume it outright -- the dispatcher branch and the import lines.
        if edit.anchor not in edit.replacement:
            results.append((
                f"anchor gone: {edit.label}",
                edit.anchor in after[edit.path],
                False,
            ))
        results.append((
            f"replacement present: {edit.label}",
            edit.replacement in after[edit.path],
            True,
        ))

    iface = after[IFACE]
    results.append(("interface: fileUnzip declared", "fun fileUnzip(source: String, destination: String): JSONObject" in iface, True))
    results.append(("interface: trailing-newline quirk preserved", iface.endswith("\n"), iface_tail_before))
    results.append(("interface: KDoc states the zero-write promise", "Nothing is written when an entry name is unsafe." in iface, True))
    results.append(("interface: KDoc states the EISDIR sentence", "EISDIR: destination is a file, not a directory" in iface, True))
    results.append(("interface: KDoc states the source-inside-destination guard", "source is inside destination: <src> under <dst>" in iface, True))
    results.append(("interface: KDoc lists what is not promised", "zip64" in iface and "encrypted" in iface, True))

    host = after[HOST]
    results.append(("host: RandomAccessFile imported", "import java.io.RandomAccessFile" in host, True))
    results.append(("host: ZipFile imported", "import java.util.zip.ZipFile" in host, True))
    results.append(("host: guard predicate is the reverse of fileZip's", 'srcPath.startsWith("$dstPath/")' in host, True))
    results.append(("host: EISDIR sentence matches fileMove's", 'EISDIR: destination is a file, not a directory: $destination' in host, True))
    results.append(("host: unsafe-name refusal names the entry", 'IllegalArgumentException("unsafe entry name: $name")' in host, True))
    results.append(("host: pre-scan runs before mkdirs", host.index("isUnsafeZipEntry(name, mode)") < host.index("dst.mkdirs()"), True))
    results.append(("host: symlink mode bit is checked", "(mode and 0xF000) == 0xA000" in host, True))
    results.append(("host: an unreadable table is refused, not guessed", "unsafe entry name: <unreadable entry table>" in host, True))
    results.append(("host: empty archive answers {}", host.count("return JSONObject()") >= 3, True))

    disp = after[DISP]
    results.append(("dispatcher: unzip branch mapped", '"Tools.Files.unzip" -> {' in disp, True))
    results.append(("dispatcher: unzip joins throwingMethods", '            "Tools.Files.unzip",' in disp, True))
    results.append(("dispatcher: unzip branch reads index 0 and 1 only", "host.fileUnzip(\n                        a.optString(0),\n                        a.optString(1),\n                    )" in disp, True))

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
