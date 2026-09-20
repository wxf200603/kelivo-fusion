#!/usr/bin/env python3
"""Correct the mislabelled parse-error claim in the fileRead KDoc.

Audit finding: the fileRead KDoc said that a lenient decode's damage surfaces
downstream "where operit_editor.js:2729-2741 reports it as a manifest *parse*
error". The line range is real; the label is not.

  operit_editor.js:2729  try {
  operit_editor.js:2730      const parsed = JSON.parse(text);
  operit_editor.js:2741  catch {
  operit_editor.js:2742      // HJSON-like manifests will fall back to regex parsing below.
  operit_editor.js:2743  }

The catch carries a comment and nothing else: it swallows the JSON.parse failure
into the regex fallback at 2744-2761. The errors that can actually reach a caller
are thrown at 2762-2767, and they are missing-field ones:

  manifest.toolpkg_id is required: <path>   (2762-2764)
  manifest.main is required: <path>         (2765-2767)

So the underlying argument survives - an encoding problem really does come back
wearing a content problem's clothes - but its label sent a reader to the catch
looking for a report that is not there. Renamed, not held over: a label that
points triage at the wrong location is a bug, unlike a merely stale name.

Three sites, one sentence:

  1. KelivoHost.kt                - the fileRead KDoc paragraph
  2. scripts/patch_files_read.py  - E1_NEW (the string that generates it)
  3. scripts/patch_files_read.py  - the module docstring's sub-decision bullet

Site 2 must move with site 1, otherwise the next re-run of patch_files_read.py
writes the wrong label back into KelivoHost.kt.

Anchors: each pattern must match exactly once inside its own file. Anything else
aborts before a byte is written. (A single global anchor is not available: the
KDoc sentence occurs twice repo-wide - once in KelivoHost.kt, once inside
E1_NEW - so the guard here is per file, which is where the edits land.)

Three passes: (1) uniqueness, (2) write, (3) self-check - the old label is gone,
the replacement is present in all three sites, and the KDoc that E1_NEW would
generate still equals the KDoc actually shipped in KelivoHost.kt.

No commit here. Stage the three files and commit separately.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KT = ROOT / "android/app/src/main/kotlin/com/psyche/kelivo"
HOST = KT / "quickjs/KelivoHost.kt"
SELF = ROOT / "scripts/patch_files_read.py"

# Written for site 1 and site 2 (identical text, different files/prefixes).
NEW_KDOC_LINES = [
    "Decoding is strict: a CharsetDecoder with REPORT on malformed input and on",
    "unmappable characters, not readText(). A lenient decode replaces bad bytes with",
    "U+FFFD and hands the damage downstream, where operit_editor.js:2729-2741 does",
    "not report a parse error: its catch (2741-2743) carries only a comment and",
    "swallows the JSON.parse failure into the regex fallback below. The error that",
    "can survive is a missing-field one \u2014 manifest.toolpkg_id is required (2762) or",
    "manifest.main is required (2765) \u2014 an encoding problem wearing a content",
    "problem's clothes. Failing here, at the read, is how it stays an encoding problem.",
]

# Site 3 keeps the docstring's own punctuation idiom (" - ", "i.e.").
NEW_DOC_LINES = [
    "strict UTF-8 decoding - CharsetDecoder with REPORT on malformed input and",
    "unmappable characters, not readText(). A lenient decode replaces bad bytes with",
    "U+FFFD and hands the damage downstream, where operit_editor.js:2729-2741 does",
    "not report a parse error: its catch (2741-2743) carries only a comment and",
    "swallows the JSON.parse failure into the regex fallback below. The error that",
    "can survive is a missing-field one, i.e. `manifest.toolpkg_id is required`",
    "(2762) or `manifest.main is required` (2765) - an encoding problem wearing a",
    "content problem's clothes.",
]

KO_DOC = re.compile(
    r"Decoding is strict:.*?problem's clothes\. Here it fails at the read, "
    r"where it happened\.",
    re.S,
)
KO_SCRIPTS_DOC = re.compile(
    r"strict UTF-8 decoding - CharsetDecoder.*?\*parse\* error, i\.e\. an encoding "
    r"problem wearing a content problem's clothes\.",
    re.S,
)
# Used after the write, to compare the generated KDoc with the shipped one.
KO_NEW = re.compile(r"Decoding is strict:.*?stays an encoding problem\.", re.S)

DEAD = "reports it as a manifest"
DEAD2 = "report the damage as a manifest"
ALIVE = "its catch (2741-2743) carries only a comment"


def only(text: str, pat: re.Pattern, label: str) -> re.Match:
    hits = list(pat.finditer(text))
    if len(hits) != 1:
        raise SystemExit(f"{label}: anchor not unique, found {len(hits)}")
    return hits[0]


def rebuild(text: str, m: re.Match, lines: list[str], cont_prefix: str | None = None) -> str:
    ls = text.rfind("\n", 0, m.start()) + 1
    prefix = text[ls:m.start()]
    if prefix.strip() != "*":
        raise SystemExit(f"unexpected line prefix {prefix!r}")
    # A hanging-indent block (the docstring bullet) continues with plain spacing,
    # not with the "*" marker: reusing the first-line prefix there would split one
    # bullet into one bullet per line in the rendered RST.
    cont = prefix if cont_prefix is None else cont_prefix
    out = [prefix + lines[0]] + [cont + ln for ln in lines[1:]]
    return text[:ls] + "\n".join(out) + text[m.end():]


def strip_prefixes(snippet: str) -> str:
    return "\n".join(ln.strip().lstrip("*").strip() for ln in snippet.splitlines())


def main() -> None:
    host = HOST.read_text(encoding="utf-8")
    self_src = SELF.read_text(encoding="utf-8")

    # Pass 1: every anchor unique in its own file, before anything touches disk.
    m_host = only(host, KO_DOC, HOST.name)
    m_e1 = only(self_src, KO_DOC, f"{SELF.name} (E1_NEW)")
    m_doc = only(self_src, KO_SCRIPTS_DOC, f"{SELF.name} (docstring)")
    # Each site must carry its own dead label exactly once, and only where it lives:
    # the KDoc sentence is in both files, the docstring wording is in the script only.
    for name, text, dead in (
        (HOST.name, host, DEAD),
        (SELF.name, self_src, DEAD),
        (SELF.name, self_src, DEAD2),
    ):
        n = text.count(dead)
        if n != 1:
            raise SystemExit(f"{name}: expected 1x {dead!r}, found {n}")

    new_host = rebuild(host, m_host, NEW_KDOC_LINES)

    # Both script edits, applied to the original source in one shot each.
    after_e1 = rebuild(self_src, m_e1, NEW_KDOC_LINES)
    m_doc2 = only(after_e1, KO_SCRIPTS_DOC, f"{SELF.name} (docstring, post-E1 shift)")
    new_self = rebuild(after_e1, m_doc2, NEW_DOC_LINES, cont_prefix="    ")

    # Pass 2: write.
    HOST.write_text(new_host, encoding="utf-8")
    SELF.write_text(new_self, encoding="utf-8")

    # Pass 3: self-check.
    host2 = HOST.read_text(encoding="utf-8")
    self2 = SELF.read_text(encoding="utf-8")
    for name, text, n_alive in ((HOST.name, host2, 1), (SELF.name, self2, 2)):
        if DEAD in text or DEAD2 in text:
            raise SystemExit(f"{name}: old label still present after write")
        n = text.count(ALIVE)
        if n != n_alive:
            raise SystemExit(f"{name}: expected {n_alive}x the replacement, found {n}")

    gen = KO_NEW.search(self2)
    ship = KO_NEW.search(host2)
    if gen is None or ship is None:
        raise SystemExit("self-check: could not re-extract the KDoc for comparison")
    if strip_prefixes(gen.group(0)) != strip_prefixes(ship.group(0)):
        raise SystemExit("self-check: E1_NEW no longer reproduces the shipped KDoc")

    # The docstring bullet must stay one bullet: its continuations are plain
    # spacing, never the "*" marker (that would break the RST list shape).
    bullet = re.search(
        r"^ *\* strict UTF-8 decoding - CharsetDecoder.*?content problem's clothes\.$",
        self2,
        re.S | re.M,
    )
    if bullet is None:
        raise SystemExit("self-check: docstring bullet not found after write")
    for ln in bullet.group(0).splitlines()[1:]:
        if re.match(r" *\*", ln):
            raise SystemExit(f"self-check: continuation mis-marked as a bullet: {ln!r}")

    non_ascii = [c for c in host2 if ord(c) > 127]
    print(f"{HOST.name}: {HOST}")
    print(f"{SELF.name}: {SELF}")
    print(f"old label gone: {host2.count(DEAD)==0} / {self2.count(DEAD)==0}")
    print(f"replacement present: {host2.count(ALIVE)} / {self2.count(ALIVE)}")
    print("E1_NEW reproduces the shipped KDoc: yes")
    print(f"non-ASCII in {HOST.name}: {sorted(set(non_ascii))}")


if __name__ == "__main__":
    main()
