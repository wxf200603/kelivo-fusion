#!/usr/bin/env python3
"""Stop two more comments from copying the throw set -- the residues the previous pen left.

`patch_prose_throwing_list.py` stopped two comments from *naming* the list, and its docstring
said exactly what it was leaving behind:

  "scripts/acceptance_info.sh:27 pins a count ("now six members") that went stale the moment
   Files.copy landed. Same class of debt, different repair -- the count has to go, not the
   name -- so it is left for its own sweep rather than folded in here."

This is that sweep, and it takes a second residue with it:

  1. scripts/acceptance_info.sh:25-27 -- "the Files family set ..., now six members". A count
     that rotted the moment the set grew. The count goes, and a sentence saying *why* no count
     is given goes in, so that nobody adds one back.
  2. OperitHostDispatcher.kt:247-249 -- the KDoc enumerated nine members of a set that now
     holds ten (Files.unzip joined it in 1763a1c). The enumeration goes: the set itself, below,
     is the only place the membership is written down.

Same disease (prose copied the set), same repair (stop copying it), so one commit -- split into
two, they would read as two problems.

One adaptation to the ruling's wording, and why: the second site's old third line ends
"The Files family convention is: file", which the *next* line completes with "operations that
touch the real filesystem". Replacing through "...written down." would orphan that sentence, so
the convention clause is kept as the last line here, and the ruling's "that touches the real
filesystem" is dropped from the first sentence because the very next sentence says it.

Deliberately NOT in this commit, by the previous pen's standing ruling:
scripts/patch_files_info.py:189 still says "throwingMethods has six members". It is a historical
patch script's anchor, and rewriting one makes the record describe a tree that never existed.

Anchors: two, one per file, each required unique before a byte is written. Three passes:
(1) uniqueness, (2) write, (3) self-check, which refuses the diff if it touches a line that is
not a comment. Both sites are comments and acceptance_info.sh:27 sits outside the range that
file's `usage` prints (sed -n '2,15p'), so this commit changes no output and no behaviour --
worth proving rather than asserting.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
DISPATCHER = KT / "quickjs/OperitHostDispatcher.kt"
DRIVER = ROOT / "scripts/acceptance_info.sh"

# --- acceptance_info.sh: the count that rotted -------------------------------

A_OLD = (
    "# The failure of case 3 arrives as a `THREW: ...` line in the diagnostic log, the\n"
    "# same as the other rounds: the dispatcher rethrows for this method (the Files\n"
    "# family set in OperitHostDispatcher.kt -- `throwingMethods`, now six members).\n"
)

A_NEW = (
    "# The failure of case 3 arrives as a `THREW: ...` line in the diagnostic log, the\n"
    "# same as the other rounds: the dispatcher rethrows for this method (the Files\n"
    "# family set in OperitHostDispatcher.kt -- `throwingMethods`). No count is given\n"
    "# on purpose: the list gains one member per Files method.\n"
)

# --- OperitHostDispatcher.kt: the enumeration that rotted --------------------

D_OLD = (
    "         * This started with Files.deleteFile and now includes Files.readBinary,\n"
    "         * Files.writeBinary, Files.read, Files.list, Files.info, Files.copy,\n"
    "         * Files.move and Files.zip. The Files family convention is: file\n"
)

D_NEW = (
    "         * This started with Files.deleteFile and has grown with each Files method.\n"
    "         * `throwingMethods` below is the list, and the only place the membership is\n"
    "         * written down. The Files family convention is: file\n"
)

EDITS = [
    (DRIVER, A_OLD, A_NEW, "acceptance_info.sh: the rotted count"),
    (DISPATCHER, D_OLD, D_NEW, "dispatcher KDoc: the rotted enumeration"),
]

SET_RE = re.compile(r"private val throwingMethods = setOf\((?P<body>.*?)\n *\)\n", re.S)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def set_count(text: str, needle: str) -> int:
    """Count `needle` inside the `throwingMethods` set -- and only inside it.

    Scoped on purpose: `"Tools.Files.unzip"` also appears in the dispatcher's branch
    table, so a whole-file count answers a different question than the one asked here.
    """
    m = SET_RE.search(text)
    if m is None:
        raise SystemExit("cannot find the throwingMethods set -- refusing to guess")
    return m.group("body").count(needle)


def set_members(text: str) -> int:
    return set_count(text, '"Tools.Files.')


def main() -> None:
    staged = {DRIVER: DRIVER.read_text(encoding="utf-8"),
              DISPATCHER: DISPATCHER.read_text(encoding="utf-8")}
    before = set_members(staged[DISPATCHER])

    # Pass 1: each anchor unique in its own file, before anything touches disk.
    for path, old, new, label in EDITS:
        n = staged[path].count(old)
        if n != 1:
            raise SystemExit(f"{path.name}: {label}: expected 1 anchor, found {n}")

    # Pass 2: write.
    for path, old, new, label in EDITS:
        staged[path] = staged[path].replace(old, new)
    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")

    # Pass 3: self-check.
    a = DRIVER.read_text(encoding="utf-8")
    d = DISPATCHER.read_text(encoding="utf-8")

    diff = git("diff", "-U0", "--",
               str(DRIVER.relative_to(ROOT)), str(DISPATCHER.relative_to(ROOT)))
    changed = [ln for ln in diff.splitlines()
               if (ln.startswith("+") or ln.startswith("-"))
               and not ln.startswith(("+++", "---"))]
    offenders = [ln for ln in changed
                 if not ln[1:].lstrip().startswith(("//", "#", "*"))]

    syntax = subprocess.run(["sh", "-n", str(DRIVER)], capture_output=True)

    checks = [
        ("driver: the count is gone", a.count("now six members"), 0),
        ("driver: says no count on purpose", a.count("No count is given"), 1),
        ("driver: the THREW sentence it belongs to kept", a.count("dispatcher rethrows for this method"), 1),
        ("driver: shebang intact", a.count("#!/system/bin/sh"), 1),
        ("driver: usage line intact", a.count("usage: sh acceptance_info.sh preflight | setup | restart | verify"), 1),
        ("driver: case-2 prose kept", a.count('So case 2 is where the value domain is actually pinned'), 1),
        ("driver: need_root call sites", a.count("need_root"), 5),
        ("driver: sh -n", syntax.returncode, 0),
        ("dispatcher: old enumeration gone", d.count("Files.move and Files.zip."), 0),
        ("dispatcher: names no members", d.count("Files.deleteFile and has grown with each Files method"), 1),
        ("dispatcher: points at the set below", d.count("is the list, and the only place the membership is"), 1),
        ("dispatcher: convention sentence still joined", d.count("The Files family convention is: file"), 1),
        ("dispatcher: the set is untouched", set_members(d), before),
        ("dispatcher: the set still holds the unzip member", set_count(d, '"Tools.Files.unzip"'), 1),
        ("diff: something changed", 1 if changed else 0, 1),
        ("diff: changed lines are all comments", len(offenders), 0),
    ]
    bad = [(name, got, want) for name, got, want in checks if got != want]
    if bad:
        for name, got, want in bad:
            print(f"FAIL {name}: got {got}, want {want}")
        for ln in offenders:
            print(f"     offending diff line: {ln}")
        if syntax.returncode != 0:
            print(syntax.stderr.decode())
        raise SystemExit("self-check failed after write")

    for path, _old, _new, label in EDITS:
        print(f"ok   {path.name} ({label})")
    for name, got, want in checks:
        print(f"     {name}: {got}")
    print(f"     (throwingMethods holds {before} members; the prose no longer says so)")


if __name__ == "__main__":
    main()