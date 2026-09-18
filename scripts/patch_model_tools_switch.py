#!/usr/bin/env python3
"""patch_model_tools_switch.py — Plan A, step 4: the tool gate stops lying, and
the user gets the last word.

Two changes, one cause. `isToolModel` infers tool support from the model's
*name* (`ModelRegistry.infer`). That cannot know anything about a custom
endpoint, so `auto (StudentApi)` reads as incapable — and the app then did two
things with that verdict:

  1. `chat_input_section.dart` **deleted the assistant's MCP servers** as a side
     effect of switching models. Switching back did not bring them back.
  2. Every tool vanished from the request.

So: stop deleting, and let the user override the guess.

  lib/features/home/widgets/chat_input_section.dart   the deletion is removed
  lib/core/providers/settings_provider.dart           + toolsForAllModels (6 sites)
  lib/features/home/controllers/generation_controller.dart
                                                      isToolModel honours it
  lib/features/settings/pages/tool_schema_settings_page.dart
                                                      + the switch card
  lib/l10n/*.arb                                      + 2 strings x 4 files

Self-checks:

  1. The destructive line is gone, and the variable it left behind went with it
     (an unused local is a warning, and `--fatal-infos` turns that into CI red).
  2. `toolsForAllModels` appears at all six sites the existing flags use.
  3. The switch defaults to off, and the override is consulted *before* the
     registry so an explicit user answer wins.
  4. The card's strings are declared in the template.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAT_INPUT = ROOT / "lib/features/home/widgets/chat_input_section.dart"
SETTINGS = ROOT / "lib/core/providers/settings_provider.dart"
GENERATION = ROOT / "lib/features/home/controllers/generation_controller.dart"
TOOL_PAGE = ROOT / "lib/features/settings/pages/tool_schema_settings_page.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    # Idempotence is checked first: on a re-run the anchor is legitimately gone
    # because the replacement is already there, and reporting that as a failure
    # buries the case that matters — an anchor that never matched at all.
    if new.strip() in text:
        print(f"  {label}: already applied")
        return
    count = text.count(old)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count != 1:
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  {label}: patched")


for path in (CHAT_INPUT, SETTINGS, GENERATION, TOOL_PAGE):
    check(path.is_file(), f"missing {path.relative_to(ROOT)}")

# 1. The deletion, and the variable that only existed to drive it.
patch(
    CHAT_INPUT,
    """    final supportsTools = isToolModel(pk, mid);
    if (!supportsTools && (a?.mcpServerIds.isNotEmpty ?? false)) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final aa = ap.currentAssistant;
        if (aa != null && aa.mcpServerIds.isNotEmpty) {
          ap.updateAssistant(aa.copyWith(mcpServerIds: const <String>[]));
        }
      });
    }
""",
    """    // Nothing is cleared here on purpose. Switching to a model the registry
    // does not mark as tool-capable used to delete the assistant's MCP servers
    // as a side effect — a configuration change nobody asked for, and one that
    // switching back did not restore. They now stay configured and simply go
    // unused until a model that can call tools is selected again.
""",
    "chat_input_section: stop deleting MCP servers",
)

# 2. The flag, at every site the neighbouring flags use.
patch(
    SETTINGS,
    "  static const String _perChatModelEnabledKey = 'per_chat_model_enabled_v1';\n",
    "  static const String _perChatModelEnabledKey = 'per_chat_model_enabled_v1';\n"
    "  static const String _toolsForAllModelsKey = 'tools_for_all_models_v1';\n",
    "settings_provider: key",
)

patch(
    SETTINGS,
    "    _perChatModelEnabled = prefs.getBool(_perChatModelEnabledKey) ?? false;\n",
    "    _perChatModelEnabled = prefs.getBool(_perChatModelEnabledKey) ?? false;\n"
    "    _toolsForAllModels = prefs.getBool(_toolsForAllModelsKey) ?? false;\n",
    "settings_provider: load",
)

patch(
    SETTINGS,
    """  Future<void> setPerChatModelEnabled(bool value) async {
    if (_perChatModelEnabled == value) return;
    _perChatModelEnabled = value;
    notifyListeners();
    final prefs = _preferences;
    await prefs.setBool(_perChatModelEnabledKey, value);
  }
""",
    """  Future<void> setPerChatModelEnabled(bool value) async {
    if (_perChatModelEnabled == value) return;
    _perChatModelEnabled = value;
    notifyListeners();
    final prefs = _preferences;
    await prefs.setBool(_perChatModelEnabledKey, value);
  }

  /// Whether every model is offered tools, overruling the registry's guess.
  ///
  /// The registry reads tool support off the model's name, which cannot know
  /// about a custom endpoint — so a model that does accept a `tools` array
  /// still saw every tool, and the assistant's MCP servers with them, treated
  /// as unusable. Defaults to off: a provider that genuinely cannot take
  /// `tools` will reject the whole request, so widening this is the user's call
  /// and not ours.
  bool _toolsForAllModels = false;
  bool get toolsForAllModels => _toolsForAllModels;

  Future<void> setToolsForAllModels(bool value) async {
    if (_toolsForAllModels == value) return;
    _toolsForAllModels = value;
    notifyListeners();
    final prefs = _preferences;
    await prefs.setBool(_toolsForAllModelsKey, value);
  }
""",
    "settings_provider: field + getter + setter",
)

patch(
    SETTINGS,
    "    copy._perChatModelEnabled = _perChatModelEnabled;\n",
    "    copy._perChatModelEnabled = _perChatModelEnabled;\n"
    "    copy._toolsForAllModels = _toolsForAllModels;\n",
    "settings_provider: copyWith",
)

# 3. The override is consulted before the inference, but after the per-model
#    abilities override, which is the narrower and more specific answer.
patch(
    GENERATION,
    """    final inferred = ModelRegistry.infer(
      ModelInfo(id: modelId, displayName: modelId),
    );
    return inferred.abilities.contains(ModelAbility.tool);
""",
    """    // The user's blanket answer outranks the registry's guess. It sits after
    // the per-model `abilities` override above, because that one is narrower:
    // "this model" beats "all models".
    if (settings.toolsForAllModels) return true;

    final inferred = ModelRegistry.infer(
      ModelInfo(id: modelId, displayName: modelId),
    );
    return inferred.abilities.contains(ModelAbility.tool);
""",
    "generation_controller: honour the switch",
)

# 4. The card on the tools page.
patch(
    TOOL_PAGE,
    "import '../../../shared/widgets/ios_tactile.dart';",
    "import '../../../shared/widgets/ios_switch.dart';\n"
    "import '../../../shared/widgets/ios_tactile.dart';",
    "tool page: import",
)

patch(
    TOOL_PAGE,
    """        children: [
          for (final group in BuiltInToolGroup.values)""",
    """        children: [
          _ModelToolsCard(settings: settings),
          const SizedBox(height: 16),
          for (final group in BuiltInToolGroup.values)""",
    "tool page: card",
)

CARD = '''
/// The one switch that overrules the model registry's tool inference.
///
/// It belongs on the tools page rather than the model page because it is a
/// statement about tools: every model gets them, whatever the registry guessed
/// from a name it cannot possibly know the meaning of.
class _ModelToolsCard extends StatelessWidget {
  const _ModelToolsCard({required this.settings});

  final SettingsProvider settings;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final l10n = AppLocalizations.of(context)!;

    return SectionCard(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 6),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  l10n.toolSchemaSettingsModelToolsTitle,
                  style: TextStyle(
                    fontSize: 14.5,
                    fontWeight: AppFontWeights.emphasis,
                  ),
                ),
              ),
              IosSwitch(
                value: settings.toolsForAllModels,
                onChanged: (value) {
                  settings.setToolsForAllModels(value);
                },
                semanticLabel: l10n.toolSchemaSettingsModelToolsTitle,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
          child: Text(
            l10n.toolSchemaSettingsModelToolsSubtitle,
            style: TextStyle(
              fontSize: 12,
              height: 1.45,
              color: cs.onSurface.withValues(alpha: 0.6),
            ),
          ),
        ),
      ],
    );
  }
}
'''

page = TOOL_PAGE.read_text(encoding="utf-8") if TOOL_PAGE.is_file() else ""
if "_ModelToolsCard extends StatelessWidget" not in page:
    TOOL_PAGE.write_text(page.rstrip() + "\n" + CARD, encoding="utf-8")
    print("  tool page: card widget appended")
else:
    print("  tool page: card widget already present")

STRINGS = {
    "app_en": {
        "toolSchemaSettingsModelToolsTitle": "Enable tools for every model",
        "toolSchemaSettingsModelToolsSubtitle": "Off: only models the registry marks as tool-capable are offered tools and MCP. On: every model is — which is what a custom endpoint needs when its name says nothing about function calling. A provider that cannot accept a tools array will reject the request instead of ignoring it.",
    },
    "app_zh": {
        "toolSchemaSettingsModelToolsTitle": "所有模型都启用工具",
        "toolSchemaSettingsModelToolsSubtitle": "关闭时：只有注册表标注支持工具的模型才会注入工具与 MCP。开启后：任何模型都会注入——适合名字看不出是否支持 function calling 的自定义端点。若接口本身不接受 tools 参数，请求会直接失败，而不是被忽略。",
    },
    "app_zh_Hans": {
        "toolSchemaSettingsModelToolsTitle": "所有模型都启用工具",
        "toolSchemaSettingsModelToolsSubtitle": "关闭时：只有注册表标注支持工具的模型才会注入工具与 MCP。开启后：任何模型都会注入——适合名字看不出是否支持 function calling 的自定义端点。若接口本身不接受 tools 参数，请求会直接失败，而不是被忽略。",
    },
    "app_zh_Hant": {
        "toolSchemaSettingsModelToolsTitle": "所有模型都啟用工具",
        "toolSchemaSettingsModelToolsSubtitle": "關閉時：只有登錄表標註支援工具的模型才會注入工具與 MCP。開啟後：任何模型都會注入——適合名字看不出是否支援 function calling 的自訂端點。若介面本身不接受 tools 參數，請求會直接失敗，而不是被忽略。",
    },
}

for name, entries in STRINGS.items():
    path = ROOT / f"lib/l10n/{name}.arb"
    if not path.is_file():
        check(False, f"missing lib/l10n/{name}.arb")
        continue
    text = path.read_text(encoding="utf-8")
    if '"toolSchemaSettingsModelToolsTitle"' in text:
        print(f"  {name}: already applied")
        continue
    check(text.startswith("{\n"), f"{name}: unexpected ARB shape")
    if not text.startswith("{\n"):
        continue
    block = "".join(
        f'  "{key}": {json.dumps(value, ensure_ascii=False)},\n'
        for key, value in entries.items()
    )
    path.write_text("{\n" + block + text[2:], encoding="utf-8")
    print(f"  {name}.arb: +{len(entries)} strings")

# Self-checks on the result.
chat_input = CHAT_INPUT.read_text(encoding="utf-8") if CHAT_INPUT.is_file() else ""
settings = SETTINGS.read_text(encoding="utf-8") if SETTINGS.is_file() else ""
generation = GENERATION.read_text(encoding="utf-8") if GENERATION.is_file() else ""
tool_page = TOOL_PAGE.read_text(encoding="utf-8") if TOOL_PAGE.is_file() else ""

check(
    "mcpServerIds: const <String>[]" not in chat_input,
    "the destructive clear is still there",
)
check(
    "final supportsTools = isToolModel(pk, mid);" not in chat_input,
    "supportsTools is now unused, which --fatal-infos reads as a failure",
)
check("toolsForAllModels" in settings, "no toolsForAllModels in SettingsProvider")
for site in (
    "_toolsForAllModelsKey = ",
    "prefs.getBool(_toolsForAllModelsKey)",
    "await prefs.setBool(_toolsForAllModelsKey, value);",
    "bool get toolsForAllModels",
    "copy._toolsForAllModels = _toolsForAllModels;",
    "bool _toolsForAllModels = false;",
):
    check(site in settings, f"settings_provider is missing: {site}")
check(
    settings.index("bool _toolsForAllModels = false;") < settings.index(
        "copy._toolsForAllModels = _toolsForAllModels;"
    ),
    "the flag is not declared before it is copied",
)
check(
    "if (settings.toolsForAllModels) return true;" in generation,
    "isToolModel ignores the switch",
)
# The override has to sit inside isToolModel, right beside the guess it overrules.
# Comparing against the first `ModelRegistry.infer(` would be wrong: the file has
# two of them, and the one in isToolModel is not the earlier of the pair.
if "if (settings.toolsForAllModels) return true;" in generation:
    override_at = generation.find("if (settings.toolsForAllModels) return true;")
    tool_return_at = generation.find(
        "return inferred.abilities.contains(ModelAbility.tool);"
    )
    check(
        override_at < tool_return_at < override_at + 400,
        "the override is not beside the tool-capability guess it overrules",
    )
check(
    "_ModelToolsCard(settings: settings)" in tool_page,
    "the card is not placed on the tools page",
)
check(
    "_ModelToolsCard extends StatelessWidget" in tool_page,
    "the card widget is missing",
)
check("IosSwitch(" in tool_page, "the card has no switch")

template = (ROOT / "lib/l10n/app_en.arb").read_text(encoding="utf-8")
for key in STRINGS["app_en"]:
    check(f'"{key}"' in template, f"{key} is not declared in app_en.arb")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: switching models no longer deletes MCP configuration")
print("  the clear is gone, and so is the variable that drove it")
print("  SettingsProvider.toolsForAllModels: key, load, field, getter, setter, copy")
print("  isToolModel: per-model abilities > switch > registry guess")
print("  tools page: switch card + 2 strings x en / zh / zh_Hans / zh_Hant")