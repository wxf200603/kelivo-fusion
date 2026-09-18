#!/usr/bin/env python3
"""patch_capability_scope_test.py — align the capability-scope pin with 0a6309c.

The composer used to force-disable what a model could not do by writing to the
ASSISTANT, including clearing its MCP servers. `0a6309c` ("fix(tools): switching
models no longer deletes your MCP servers") removed that clearing on purpose, and
left the reason in the function:

    // Nothing is cleared here on purpose. Switching to a model the registry
    // does not mark as tool-capable used to delete the assistant's MCP servers
    // as a side effect — a configuration change nobody asked for, and one that
    // switching back did not restore.

Three places still describe the removed behaviour, and all three are documents
rather than decisions:

  (A) the call site's comment still says "disable MCP selection if model doesn't
      support tools", directly contradicting the function it introduces. It is a
      factual error, and it is the sentence that made the mechanism look like it
      still existed.
  (B) the test file's header states the composer "force-disables capabilities
      the current model lacks by writing to the ASSISTANT"
  (C) the second test asserts `mcpServerIds` is empty, i.e. it pins the deleted
      behaviour, which is why it is the last red test in the gate.

So this rewrites all three to the contract the code now implements: the composer
makes exactly one write to the assistant — turning off a reasoning budget the
model cannot honour — and that write stays scoped to the case where the assistant
really is the source of the model. The MCP servers stay configured and go unused.

Nothing else moves. (A) is a comment: the same file, with comments and blank lines
removed, has to come out token-for-token identical, and check 5 below is what says
so — "updateAssistant still appears once" would not, because (A) edits the very
file it would be counting in.

One more thing this run taught, recorded here rather than in a comment nobody
reads again: the applied state does not look like this script's replacement text.
`dart format` re-lays-out what the script writes — the `testWidgets` call below
came back split one argument per line — so "already applied" is decided on a
phrase that survives formatting, one per change, rather than on the exact lines.
Deciding on the lines made the script fail on the committed tree, which is the
only tree a fresh clone ever has.

Self-checks:

  1. Every anchor matched exactly once; the four strings that carried the removed
     behaviour are gone.
  2. The new test name and reason are in place, and the first test — the one that
     pins the scope guard — is untouched.
  3. The test file still holds exactly two tests: nothing was added here.
  4. The scope guard at chat_input_section.dart:157 is still verbatim.
  5. chat_input_section.dart: identical before and after once comment-only and
     blank lines are dropped, so (A) cannot have changed any code. The run that
     applies this is the one that proves it; a re-run has nothing left to move,
     so there it holds trivially rather than vacuously.
  6. The new header carries the commit that removed the behaviour, so the pin can
     be traced to the decision rather than to a preference.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIDGET = ROOT / "lib/features/home/widgets/chat_input_section.dart"
TEST = ROOT / "test/features/home/widgets/chat_input_section_capability_scope_test.dart"

OLD_CALL_SITE = (
    "    // Enforce model capabilities: disable MCP selection if model doesn't\n"
    "    // support tools. Skipped while the conversation overrides the model —\n"
    "    // these writes land on the assistant and would leak across conversations.\n"
)
NEW_CALL_SITE = (
    "    // Enforce the capabilities the model can honour: a reasoning budget on a\n"
    "    // model without reasoning. Skipped while the conversation overrides the\n"
    "    // model — this write lands on the assistant and would leak across\n"
    "    // conversations. The MCP servers used to be cleared here as well; they are\n"
    "    // not any more (see _enforceModelCapabilities).\n"
)

OLD_HEADER = (
    "/// The composer force-disables capabilities the current model lacks by writing\n"
    "/// to the ASSISTANT. Once a conversation can pin its own model, that write\n"
    "/// would reach every other conversation sharing the assistant, so it has to be\n"
    "/// scoped to the case where the assistant really is the source of the model.\n"
)
NEW_HEADER = (
    "/// The composer makes exactly one write to the ASSISTANT: turning off a\n"
    "/// reasoning budget the current model cannot honour. That write stays scoped to\n"
    "/// the case where the assistant really is the source of the model, because a\n"
    "/// conversation that pins its own model would otherwise reach every other\n"
    "/// conversation sharing the assistant.\n"
    "///\n"
    "/// It no longer touches the assistant's MCP servers. Switching to a model the\n"
    "/// registry does not mark as tool-capable used to delete them as a side effect\n"
    '/// (0a6309c, "fix(tools): switching models no longer deletes your MCP servers").\n'
    "/// They now stay configured and go unused until a tool-capable model is selected.\n"
)

OLD_TEST = (
    "  testWidgets('the assistant\\'s own model still disables what it cannot do', (\n"
    "    tester,\n"
    "  ) async {\n"
    "    final assistants = await loadAssistantWithMcp(tester);\n"
    "\n"
    "    await pumpComposer(\n"
    "      tester,\n"
    "      assistants: assistants,\n"
    "      isConversationOverride: false,\n"
    "    );\n"
    "\n"
    "    expect(assistants.currentAssistant?.mcpServerIds, isEmpty);\n"
    "  });\n"
)
# The layout `dart format` produced for this block, not the layout that was first
# written here by hand. The two differ, and the difference had to be applied as a
# separate style commit; carrying the formatter's layout means a replay of this
# script lands on the committed state directly.
NEW_TEST = (
    "  testWidgets(\n"
    "    'a model that cannot call tools keeps the MCP servers configured',\n"
    "    (tester) async {\n"
    "      final assistants = await loadAssistantWithMcp(tester);\n"
    "\n"
    "      await pumpComposer(\n"
    "        tester,\n"
    "        assistants: assistants,\n"
    "        isConversationOverride: false,\n"
    "      );\n"
    "\n"
    "      expect(\n"
    "        assistants.currentAssistant?.mcpServerIds,\n"
    "        const ['server-1'],\n"
    "        reason:\n"
    "            'not marking a model tool-capable is not a reason to delete a '\n"
    "            'configuration nobody asked to change; the servers stay configured '\n"
    "            'and go unused until a tool-capable model is selected',\n"
    "      );\n"
    "    },\n"
    "  );\n"
)

GUARD = "    if (!chatModelIsConversationOverride) {"

FIRST_TEST_REASON = "'one conversation must not rewrite settings shared by all of them'"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def code_lines(text: str) -> list[str]:
    """The file with comment-only and blank lines dropped.

    Trailing comments on a line that carries code stay on it, so a change to such
    a line still shows up; what this ignores is exactly the class of line this
    patch is allowed to touch.
    """
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        kept.append(line.rstrip())
    return kept


check(WIDGET.is_file() and TEST.is_file(), "the widget or the test file is missing")
widget_before = WIDGET.read_text(encoding="utf-8")
test_before = TEST.read_text(encoding="utf-8")

widget = widget_before
test = test_before

# `marker` is what decides "already applied", and it is deliberately a phrase that
# survives formatting rather than the replacement text itself. The formatter
# re-lays-out what this script writes, so on the committed tree -- the only tree a
# fresh clone has -- the applied state does not look like `new`. Deciding on the
# exact lines made this script fail there, which is what its own re-run caught.
for label, old, new, marker, target in (
    (
        "call-site comment",
        OLD_CALL_SITE,
        NEW_CALL_SITE,
        "The MCP servers used to be cleared here as well",
        "widget",
    ),
    (
        "test header",
        OLD_HEADER,
        NEW_HEADER,
        "makes exactly one write to the ASSISTANT",
        "test",
    ),
    (
        "second test",
        OLD_TEST,
        NEW_TEST,
        "not marking a model tool-capable",
        "test",
    ),
):
    haystack = widget if target == "widget" else test
    if marker in haystack:
        print(f"  {label}: already applied")
        continue
    count = haystack.count(old)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count == 1:
        if target == "widget":
            widget = widget.replace(old, new, 1)
        else:
            test = test.replace(old, new, 1)
        print(f"  {label}: rewritten")

if widget != widget_before:
    WIDGET.write_text(widget, encoding="utf-8")
if test != test_before:
    TEST.write_text(test, encoding="utf-8")

# 1. The removed behaviour is gone everywhere it was described.
for gone in (
    "disable MCP selection if model doesn't support tools",
    "force-disables capabilities the current model lacks",
    "still disables what it cannot do",
    "mcpServerIds, isEmpty",
):
    check(gone not in widget and gone not in test, f"still described somewhere: {gone}")

# 2. The new pin, and the untouched one next to it.
check("a model that cannot call tools keeps the MCP servers configured" in test, "new test name missing")
check("go unused until a tool-capable model is selected" in test, "new reason missing")
check(FIRST_TEST_REASON in test, "the first test lost its reason")
check("const ['server-1']," in test, "the new assertion does not pin the servers")

# 3. Two tests, no silent additions.
check(test.count("testWidgets(") == 2, f"the file has {test.count('testWidgets(')} tests (expected 2)")

# 4. The guard this file's first test pins is still verbatim.
check(GUARD in widget, "the scope guard is no longer verbatim")

# 5. (A) is a comment: no code moved in that file. The count goes into the log,
# so the size of what was proven is visible rather than implied.
check(
    code_lines(widget) == code_lines(widget_before),
    "chat_input_section.dart changed something other than comments",
)
check(
    len(code_lines(widget)) > 0
    and code_lines(widget) == code_lines(WIDGET.read_text(encoding="utf-8")),
    "the code-line comparison is not measuring the written file",
)
print(f"  (A) left {len(code_lines(widget))} code lines untouched")

# 6. Traceable to the decision, not to a preference.
check("0a6309c" in test, "the header does not cite the commit that removed the behaviour")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the pin matches the behaviour 0a6309c left behind, and only comments moved")