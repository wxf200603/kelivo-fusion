#!/usr/bin/env python3
"""patch_mcp_server_storage_logging.py — make every settings write say so.

`load()` already reports `stored=<true|false>`, and that is the line which
settles whether the *previous* launch's write survived. It has to be that way,
because on this app a returning `setString` proves nothing:
`BusinessKeyRegistry.classify` sorts every key before it is stored, and the
migration cleanup deletes whatever is not `localOnly` — so a write can land in
`FlutterSharedPreferences.xml` and be gone by the next start, silently, which is
exactly how the token went missing in the first place.

What was missing was the other half of the pair: the six write sites said
nothing at all. With both halves logged, a failed persist is distinguishable
from a failed read in one `operit_js_diag.log` — which is what makes the
on-device check ("`stored=true` after a restart, switch and token unchanged")
mean something instead of being a coin flip between two silent failures.

Self-checks:

  1. Every write site logs, and the read site still reports `stored=`.
  2. Each anchor matched exactly once, so no edit landed twice or on the wrong
     site — the anchors are indentation-sensitive on purpose, since
     `setString(_tokenKey, _token)` occurs at three different depths.
  3. No write was restructured, only annotated. Wrapping a write in a fresh
     try/catch would change what a failure does; `setEnabled` deliberately keeps
     the one it has, because "the switch applied but did not persist" is a
     half-truth worth naming exactly as it is.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "lib/core/services/mcp/server/mcp_server_service.dart"

READ_MARKER = "'mcp: settings loaded enabled=$_enabled port=$_port '"
STORED_MARKER = "'token=${_token.length}chars stored=$hadToken',"

# (what the write does, anchor, anchor with the log line inserted)
EDITS = (
    (
        "load: first token",
        "        _token = _generateToken();\n"
        "        await prefs.setString(_tokenKey, _token);\n"
        "      }\n",
        "        _token = _generateToken();\n"
        "        await prefs.setString(_tokenKey, _token);\n"
        "        // Logged beside the write rather than trusted instead of it: a\n"
        "        // `setString` that returns has already been seen to store nothing\n"
        "        // here, so the line that settles it is `stored=true` next launch.\n"
        "        unawaited(_mark('mcp: wrote token len=${_token.length}chars'));\n"
        "      }\n",
    ),
    (
        "start: token before listening",
        "      final prefs = await SharedPreferences.getInstance();\n"
        "      await prefs.setString(_tokenKey, _token);\n"
        "      notifyListeners();\n",
        "      final prefs = await SharedPreferences.getInstance();\n"
        "      await prefs.setString(_tokenKey, _token);\n"
        "      unawaited(\n"
        "        _mark('mcp: wrote token before start len=${_token.length}chars'),\n"
        "      );\n"
        "      notifyListeners();\n",
    ),
    (
        "setEnabled",
        "      await prefs.setBool(_enabledKey, value);\n"
        "    } catch (error) {\n",
        "      await prefs.setBool(_enabledKey, value);\n"
        "      unawaited(_mark('mcp: wrote enabled=$value'));\n"
        "    } catch (error) {\n",
    ),
    (
        "setAllowLan",
        "    await prefs.setBool(_lanKey, value);\n",
        "    await prefs.setBool(_lanKey, value);\n"
        "    unawaited(_mark('mcp: wrote allow_lan=$value'));\n",
    ),
    (
        "setPort",
        "    await prefs.setInt(_portKey, value);\n",
        "    await prefs.setInt(_portKey, value);\n"
        "    unawaited(_mark('mcp: wrote port=$value'));\n",
    ),
    (
        "regenerateToken",
        "    await prefs.setString(_tokenKey, _token);\n",
        "    await prefs.setString(_tokenKey, _token);\n"
        "    unawaited(\n"
        "      _mark('mcp: wrote regenerated token len=${_token.length}chars'),\n"
        "    );\n",
    ),
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


check(SERVICE.is_file(), f"missing {SERVICE.relative_to(ROOT)}")
text = SERVICE.read_text(encoding="utf-8") if SERVICE.is_file() else ""
original = text

def locate(lines: list[str], anchor: str) -> list[int]:
    """Line indexes where `anchor` appears as a whole block of lines.

    A substring count is not enough, and this was measured rather than assumed:
    `"    await prefs.setString(_tokenKey, _token)"` is contained in the
    six-space form used by `start()`, so the write in `regenerateToken` counted
    as three matches. Comparing line lists removes that ambiguity, and the
    caller still insists on exactly one hit.
    """
    needle = anchor.splitlines(keepends=True)
    width = len(needle)
    return [
        index
        for index in range(len(lines) - width + 1)
        if lines[index:index + width] == needle
    ]


for label, anchor, replacement in EDITS:
    if replacement in text:
        print(f"  {label}: already applied")
        continue
    lines = text.splitlines(keepends=True)
    hits = locate(lines, anchor)
    check(len(hits) == 1, f"{label}: anchor matched {len(hits)} times (expected exactly 1)")
    if len(hits) == 1:
        width = len(anchor.splitlines(keepends=True))
        lines[hits[0]:hits[0] + width] = replacement.splitlines(keepends=True)
        text = "".join(lines)
        print(f"  {label}: logged")

if text != original:
    SERVICE.write_text(text, encoding="utf-8")

# 1. Both halves of the pair are present.
check(READ_MARKER in text, "the read site no longer reports the loaded settings")
check(STORED_MARKER in text, "the read site no longer prints stored=<true|false>")
for label, _, replacement in EDITS:
    # Two of the message strings wrap across lines, so the check is on the call
    # rather than on `unawaited(_mark(` being contiguous.
    check("_mark(" in replacement, f"{label}: no log line in the replacement")

# 3. Writes are annotated, not restructured: each one still follows the same
# call, and the count of log lines matches the count of write sites.
check(
    text.count("'mcp: wrote ") == len(EDITS),
    f"expected {len(EDITS)} write log lines, found {text.count(chr(39) + 'mcp: wrote ')}",
)
for key in ("_enabledKey", "_lanKey", "_portKey", "_tokenKey"):
    check(f"setBool({key}" in text or f"setInt({key}" in text or f"setString({key}" in text,
          f"no write of {key} is left")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: every settings write now reports itself")
print("  wrote token / enabled / allow_lan / port / regenerated token")
print("  paired with the read site's stored=<true|false> on the next launch")
