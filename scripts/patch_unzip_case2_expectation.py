#!/usr/bin/env python3
"""Fix case 2's expectation: the archive stores its two members with a trailing newline.

The first device run of `acceptance_unzip.sh` (after fc640f7) reported 10/11 with case 2 FAIL:
`a/keep.txt=changed dir/empty.txt=changed`. The host was right -- what it wrote is byte-for-byte
what the device's own `/system/bin/unzip` produces for the same members (`KEEP\n` = 5 bytes,
`EMPTY\n` = 6 bytes). The expectation was wrong: `setup()` wrote it with
`printf '%s' "$C_KEEP"`, and a shell variable cannot hold a trailing newline, so the `\n` was
dropped and `cmp -s` called a correct extraction "changed".

Two edits:

  1. Drop `C_KEEP` / `C_EMPTY`. `C_KEEP` in `acceptance_zip.sh` is a different variable that
     merely shares the name (`keep-me`); it is untouched, and nothing else in the tree reads
     either one.
  2. Materialise the two expectations from the archive with the device's own `unzip -p`, and
     assert each equals the size the archive itself reports for that member -- one source, so a
     re-cut fixture trips loudly in setup instead of drifting quietly into a judgement.

Idempotent: when the post-state is already present it says so and moves on. Any anchor that does
not match exactly once aborts before anything is written; after writing, the file is re-read and
`sh -n` has the last word.

Why the rehearsal missed it: `rehearse_unzip.sh`'s synthetic world wrote both sides with
`printf '%s'`, so it agreed with itself. A harness that is self-consistent has tested nothing.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "scripts/acceptance_unzip.sh"

EDITS = [
    (
        "drop the two constants that cannot hold the archive's bytes",
        "C_ONE=one-file\n"
        "C_KEEP=KEEP\n"
        "C_EMPTY=EMPTY\n"
        "C_TOP=TOP\n",
        "C_ONE=one-file\n"
        "C_TOP=TOP\n",
        "C_ONE=one-file\nC_TOP=TOP\n",
    ),
    (
        "materialise case 2's expectations from the archive",
        "    # Expected contents, recorded as files rather than as strings in the judgements.\n"
        "    printf '%s' \"$C_ONE\" > \"$RD/.exp_one\"\n"
        "    printf '%s' \"$C_KEEP\" > \"$RD/.exp_keep\"\n"
        "    printf '%s' \"$C_EMPTY\" > \"$RD/.exp_empty\"\n"
        "    printf '%s' \"$C_TOP\" > \"$RD/.exp_top\"\n",
        "    # Expected contents, recorded as files rather than as strings in the judgements.\n"
        "    printf '%s' \"$C_ONE\" > \"$RD/.exp_one\"\n"
        "    printf '%s' \"$C_TOP\" > \"$RD/.exp_top\"\n"
        "\n"
        "    # Case 2's two members carry a trailing newline inside the archive (\"KEEP\\n\" = 5 bytes,\n"
        "    # \"EMPTY\\n\" = 6 bytes). A shell variable cannot hold a trailing newline, so an\n"
        "    # expectation written from a constant silently dropped it, and the first device run\n"
        "    # called a byte-correct extraction \"changed\". The expected bytes are therefore\n"
        "    # materialised from the archive by the device's own unzip: the judgement is \"the host\n"
        "    # reproduced the member\", and it cannot drift from the fixture. (The rehearsal could not\n"
        "    # see this -- its synthetic world wrote both sides with printf '%s' and so agreed with\n"
        "    # itself.)\n"
        "    unzip -p \"$FIX/f_tree.zip\" 'a/keep.txt' > \"$RD/.exp_keep\"\n"
        "    unzip -p \"$FIX/f_tree.zip\" 'dir/empty.txt' > \"$RD/.exp_empty\"\n"
        "\n"
        "    # One source only: each expectation must equal the size the archive itself reports for\n"
        "    # that member. Pinning 5 and 6 here would be a second copy that goes stale the day the\n"
        "    # fixture is re-cut -- the same silent-failure shape this edit is closing.\n"
        "    [ \"$(unzip -l \"$FIX/f_tree.zip\" | awk '$4==\"a/keep.txt\"{print $1}')\" = \"$(wc -c < \"$RD/.exp_keep\" | tr -d ' ')\" ] ||\n"
        "        { echo \"FAIL .exp_keep is not the size the archive reports for a/keep.txt\" >&2; exit 1; }\n"
        "    [ \"$(unzip -l \"$FIX/f_tree.zip\" | awk '$4==\"dir/empty.txt\"{print $1}')\" = \"$(wc -c < \"$RD/.exp_empty\" | tr -d ' ')\" ] ||\n"
        "        { echo \"FAIL .exp_empty is not the size the archive reports for dir/empty.txt\" >&2; exit 1; }\n",
        "unzip -p \"$FIX/f_tree.zip\" 'a/keep.txt' > \"$RD/.exp_keep\"",
    ),
]


def main() -> None:
    src = DRIVER.read_text(encoding="utf-8")

    # Phase 1 -- every anchor checked, nothing written yet.
    pending = []
    for name, old, new, marker in EDITS:
        if marker in src:
            print(f"already applied: {name}")
            continue
        found = src.count(old)
        if found != 1:
            raise SystemExit(f"{name}: expected exactly 1 match, found {found} -- nothing written")
        pending.append((name, old, new, marker))

    if not pending:
        print("nothing to do")
        return

    # Phase 2 -- write.
    out = src
    for name, old, new, marker in pending:
        out = out.replace(old, new)
    DRIVER.write_text(out, encoding="utf-8")
    print(f"written: {DRIVER}")

    # Phase 3 -- self-check what actually landed.
    back = DRIVER.read_text(encoding="utf-8")
    for name, old, new, marker in pending:
        if old in back:
            raise SystemExit(f"self-check failed: the old text for '{name}' is still present")
        hits = back.count(marker)
        if hits != 1:
            raise SystemExit(f"self-check failed: marker for '{name}' appears {hits} times")
        print(f"self-check ok: {name}")

    syntax = subprocess.run(["sh", "-n", str(DRIVER)], capture_output=True)
    if syntax.returncode != 0:
        raise SystemExit("self-check failed: sh -n says it does not parse\n" + syntax.stderr.decode())
    print("self-check ok: sh -n")


if __name__ == "__main__":
    main()