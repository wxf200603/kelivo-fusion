#!/usr/bin/env python3
"""Stop the live prose from naming the throw list; describe it instead.

Two comments in the working tree still call the list `THROWING_METHODS`, the
identifier it carried before it was renamed to `throwingMethods`. Neither is a
reference any compiler resolves, so both have been silently stale since that
rename:

  OperitJsRuntime.kt:399        "// dispatcher rethrows for this method (THROWING_METHODS)."
  acceptance_delete_file.sh:63  the same sentence in the driver's header

Both now describe the list rather than name it. A name copied into prose is a
copy of a variable that nothing checks, and this one has already changed once;
"the host's throw list" survives the next rename, and both sites already point
at OperitHostDispatcher.kt for the truth. The new sentence also says why it is
not named, so nobody "fixes" it back.

Deliberately NOT in this commit:

  * scripts/patch_selftest_host_prefix.py:58, plus the anchor constants in
    patch_files_delete.py and patch_files_read_binary.py, still contain
    `THROWING_METHODS`. Those files are records of what each patch did to the
    tree as it stood then; rewriting them would make the record describe a tree
    that never existed. They are also fail-safe: pass 1 demands a unique anchor,
    so re-running one against the new prose aborts before writing -- control (b)
    in the round's dry run exercises exactly that.
  * scripts/acceptance_info.sh:27 pins a count ("now six members") that went
    stale the moment Files.copy landed. Same class of debt, different repair --
    the count has to go, not the name -- so it is left for its own sweep rather
    than folded in here.

Anchors: two, one per file, each required to be unique before a byte is written.

Three passes: (1) uniqueness, (2) write, (3) self-check, which refuses the diff
if it touches any line that is not a comment. The claim of this commit is "prose
only, no behaviour", and that is worth proving rather than asserting.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
RUNTIME = KT / "quickjs/OperitJsRuntime.kt"
DRIVER = ROOT / "scripts/acceptance_delete_file.sh"

# --- OperitJsRuntime.kt: the marker-loop comment -----------------------------

R_OLD = (
    "            // An expected failure arrives here as a `THREW: ...` line: the\n"
    "            // dispatcher rethrows for this method (THROWING_METHODS).\n"
)

R_NEW = (
    "            // An expected failure arrives here as a `THREW: ...` line: this\n"
    "            // method is on the host's throw list, so the dispatcher rethrows\n"
    "            // rather than answering with an error object. The list is not named\n"
    "            // here on purpose -- it gains one member per Files method, and its\n"
    "            // identifier has already been renamed once.\n"
)

# --- acceptance_delete_file.sh: the driver's header --------------------------

A_OLD = (
    "# The failure of every case arrives as a `THREW: ...` line in the diagnostic\n"
    "# log, because the dispatcher rethrows for this method (THROWING_METHODS).\n"
)

A_NEW = (
    "# The failure of every case arrives as a `THREW: ...` line in the diagnostic\n"
    "# log: this method is on the host's throw list, so the dispatcher rethrows\n"
    "# rather than answering with an error object. The list is not named here on\n"
    "# purpose -- it gains one member per Files method, and its identifier has\n"
    "# already been renamed once.\n"
)

EDITS = [
    (RUNTIME, R_OLD, R_NEW, "runtime marker-loop comment"),
    (DRIVER, A_OLD, A_NEW, "deleteFile driver header"),
]

# Every file that may still contain the old identifier once this lands. All three
# are patch scripts, i.e. historical anchors, not live prose.
RESIDUE_OK = {
    "scripts/patch_files_delete.py",
    "scripts/patch_files_read_binary.py",
    "scripts/patch_selftest_host_prefix.py",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def main() -> None:
    staged = {RUNTIME: RUNTIME.read_text(encoding="utf-8"),
              DRIVER: DRIVER.read_text(encoding="utf-8")}

    # Pass 1: each anchor unique in its own file, before anything touches disk.
    for path, old, new, label in EDITS:
        n = staged[path].count(old)
        if n != 1:
            raise SystemExit(f"{path.name}: {label}: expected 1 anchor, found {n}")
        staged[path] = staged[path].replace(old, new)

    # Pass 2: write.
    for path, text in staged.items():
        path.write_text(text, encoding="utf-8")

    # Pass 3: self-check.
    r = RUNTIME.read_text(encoding="utf-8")
    a = DRIVER.read_text(encoding="utf-8")

    # The strongest available statement of "prose only": read the diff this commit
    # would make and require every changed line to be a comment. A code line that
    # drifted in by accident cannot pass this, whatever the word counts say.
    diff = git("diff", "-U0", "--",
               str(RUNTIME.relative_to(ROOT)), str(DRIVER.relative_to(ROOT)))
    changed = [ln for ln in diff.splitlines()
               if (ln.startswith("+") or ln.startswith("-"))
               and not ln.startswith(("+++", "---"))]
    offenders = [ln for ln in changed
                 if not ln[1:].lstrip().startswith(("//", "#"))]

    residue = set(git("grep", "-l", "THROWING_METHODS").split())

    checks = [
        ("runtime: old identifier gone", r.count("THROWING_METHODS"), 0),
        ("runtime: describes the list instead", r.count("is on the host's throw list"), 1),
        # Needle kept on one line on purpose: a phrase the wrapping splits would
        # read as "the prose is missing" when it is only re-flowed.
        ("runtime: says why it is not named", r.count("already been renamed once"), 1),
        ("runtime: the THREW sentence it belongs to kept", r.count("An expected failure arrives here as a `THREW: ...` line"), 1),
        ("runtime: following code line intact", r.count("if (target.startsWith(HOST_PREFIX)) {"), 1),
        ("runtime: marker syntax line untouched", r.count('#call host:Tools.Files.deleteFile ["/sdcard/t",false]'), 1),
        ("driver: old identifier gone", a.count("THROWING_METHODS"), 0),
        ("driver: describes the list instead", a.count("is on the host's throw list"), 1),
        ("driver: says why it is not named", a.count("already been renamed once"), 1),
        ("driver: case-3 prose kept", a.count("is the PASS, not the failure"), 1),
        ("driver: shebang intact", a.count("#!/system/bin/sh"), 1),
        ("driver: root guard call sites", a.count("need_root"), 5),
        ("diff: something changed", 1 if changed else 0, 1),
        ("diff: changed lines are all comments", len(offenders), 0),
        ("git grep: old identifier survives only in patch-script anchors", len(residue - RESIDUE_OK), 0),
    ]
    bad = [(name, got, want) for name, got, want in checks if got != want]
    if bad:
        for name, got, want in bad:
            print(f"FAIL {name}: got {got}, want {want}")
        for ln in offenders:
            print(f"     offending diff line: {ln}")
        raise SystemExit("self-check failed after write")

    for path, _old, _new, label in EDITS:
        print(f"ok   {path.name} ({label})")
    for name, got, want in checks:
        print(f"     {name}: {got}")
    print(f"     residue: {sorted(residue)}")


if __name__ == "__main__":
    main()
