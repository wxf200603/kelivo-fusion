#!/usr/bin/env python3
"""Record the two residuals the zip round ruled on, in fileZip's KDoc.

The rulings, and what they require to be visible to a reader of the interface:

  * a failure may leave a **partial archive** at [destination]. The method does not delete it:
    that is the same stance as fileCopy and fileMove, which do not roll back either, and the
    difference is worth stating -- a half-written archive is inert garbage, while rolling back
    a move's destination can destroy entries the source never carried. Not deleting is only
    acceptable if it is not silent, so it is written down.
  * a destination **equal** to the source is not guarded and its behaviour is **undefined**.
    The ruling's criterion is "the source is an ancestor of the destination's parent, or that
    parent itself", which is what the guard implements; the equal case has no observed shape
    (the only caller reads a staging directory while writing into a temp build directory), and
    an unobserved shape does not get a guard.

Anchors: one, required unique before a byte is written. Three passes, and the self-check
refuses a diff that removes any line other than that anchor.

Same needle discipline as the last three rounds: every check string must be unique in the
whole file and must not be a bare word that prose can also contain.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
HOST = KT / "quickjs/KelivoHost.kt"

H_OLD = '''     * an unlistable source or an archive that cannot be written -> EIO. A destination
     * equal to the source is **not** guarded -- no caller produces that shape, and the
     * guard above is the one the round asked for.
'''

H_NEW = '''     * an unlistable source or an archive that cannot be written -> EIO.
     *
     * **A failure can leave a partial archive at [destination].** This method does not delete
     * it, the same stance as [fileCopy] and [fileMove], which do not roll back either -- the
     * difference is that a half-written archive is inert garbage rather than somebody's data,
     * which is why not deleting it is acceptable at all. It is not acceptable for it to be
     * silent, hence this paragraph.
     *
     * A destination **equal** to the source is not guarded, and its behaviour is
     * **undefined**: the guard above covers the shape the round asked for (the source is an
     * ancestor of the destination's parent, or that parent itself), and this shape has no
     * observed caller -- the only one reads a staging directory while writing its archive
     * into a separate temp build directory.
'''

EDITS = [
    (HOST, H_OLD, H_NEW, "fileZip residuals paragraph"),
]

TOUCHED = {HOST}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def main() -> None:
    staged = {p: p.read_text(encoding="utf-8") for p in TOUCHED}

    # Pass 1: the anchor is unique in its file, before anything touches disk.
    for path, old, new, label in EDITS:
        n = staged[path].count(old)
        if n != 1:
            raise SystemExit(f"{path.name}: {label}: expected 1 anchor, found {n}")
        staged[path] = staged[path].replace(old, new)

    # Pass 2: write.
    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")

    # Pass 3: self-check.
    h = HOST.read_text(encoding="utf-8")

    diff = git("diff", "--", ".", *[str(p.relative_to(ROOT)) for p in TOUCHED])
    removed = [ln[1:] for ln in diff.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    anchor_lines = {ln for _p, old, _n, _l in EDITS for ln in old.splitlines()}
    stray_removals = [ln for ln in removed if ln.strip() and ln not in anchor_lines]
    changed_files = set(git("diff", "--name-only").split())

    checks = [
        ("host: the partial-archive sentence is there", h.count("**A failure can leave a partial archive at [destination].**"), 1),
        ("host: it names the family stance it follows", h.count("the same stance as [fileCopy] and [fileMove], which do not roll back either"), 1),
        ("host: and states why not deleting is acceptable at all", h.count("which is why not deleting it is acceptable at all."), 1),
        ("host: and closes it with the silence argument", h.count("hence this paragraph."), 1),
        ("host: the equal-path sentence now says undefined", h.count("A destination **equal** to the source is not guarded, and its behaviour is"), 1),
        ("host: it still names the criterion that IS implemented", h.count("the source is an\n     * ancestor of the destination's parent, or that parent itself"), 1),
        ("host: the old hedging sentence is gone", h.count("guard above is the one the round asked for"), 0),
        ("host: the Throws list keeps its three codes", h.count("an unlistable source or an archive that cannot be written -> EIO."), 1),
        ("host: fileZip is still declared exactly once", h.count("fun fileZip"), 1),
        ("host: the no-trailing-newline quirk preserved", 1 if h.endswith("}") else 0, 1),
        ("diff: only the one file changed", len(changed_files), 1),
        ("diff: only the one anchor was replaced", len(stray_removals), 0),
    ]
    bad = [(name, got, want) for name, got, want in checks if got != want]
    if bad:
        for name, got, want in bad:
            print(f"FAIL {name}: got {got}, want {want}")
        for ln in stray_removals:
            print(f"     stray removal: {ln}")
        for f in sorted(changed_files):
            print(f"     changed file: {f}")
        raise SystemExit("self-check failed after write")

    for path, _old, _new, label in EDITS:
        print(f"ok   {path.name} ({label})")
    for name, got, want in checks:
        print(f"     {name}: {got}")


if __name__ == "__main__":
    main()