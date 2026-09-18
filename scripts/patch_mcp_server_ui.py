#!/usr/bin/env python3
"""patch_mcp_server_ui.py — Plan A, step 3: the settings page and its strings.

Adds the page and the entry point that reaches it:

  lib/features/mcp/pages/mcp_server_page.dart   (new)
  lib/features/mcp/pages/mcp_page.dart          + import + AppBar action
  lib/l10n/app_en.arb, app_zh.arb, app_zh_Hans.arb, app_zh_Hant.arb
                                                + the mcpServerPage* strings

The ARB files are edited textually rather than through `json.load`, because
re-serialising them would reflow four thousand lines and bury the real change.
The entries are inserted right after the opening brace; JSON object order is not
meaningful, and `flutter gen-l10n` runs on every build (`generate: true` in
pubspec), so the generated Dart is not touched here.

Self-checks:

  1. Every string the page reads exists in the template (app_en.arb). A key used
     but not declared is a compile error on the next build.
  2. No key collides with one that already exists.
  3. The page is reachable: mcp_page.dart imports it and pushes it.
  4. The entry icon is one the app actually defines (Lucide.Server does not
     exist in this codebase).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "lib/features/mcp/pages/mcp_server_page.dart"
MCP_PAGE = ROOT / "lib/features/mcp/pages/mcp_page.dart"
LUCIDE = ROOT / "lib/icons/lucide_adapter.dart"

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def patch(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    check(count == 1, f"{label}: anchor matched {count} times (expected exactly 1)")
    if count != 1:
        return
    if new.strip() in text:
        print(f"  {label}: already applied")
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"  {label}: patched")


STRINGS = {
    "app_en": {
        "mcpServerPageTitle": "Built-in MCP server",
        "mcpServerPageEnable": "Serve this workspace",
        "mcpServerPageStatusRunning": "Listening",
        "mcpServerPageStatusStopped": "Stopped",
        "mcpServerPageListenerHint": "Exposes the proot terminal over MCP. Any client that can reach this device can run commands in the same working directory the assistant uses.",
        "mcpServerPageEndpoints": "Client URLs",
        "mcpServerPageToken": "Access token",
        "mcpServerPageTokenHint": "Clients must send it as: Authorization: Bearer <token>",
        "mcpServerPageNetwork": "Network",
        "mcpServerPagePort": "Port",
        "mcpServerPageAllowLan": "Allow other devices",
        "mcpServerPageAllowLanHint": "Off keeps the server on 127.0.0.1, reachable only from this device. On lets a PC on the same Wi-Fi connect.",
        "mcpServerPagePcHint": "A client on your PC cannot see the phone's 127.0.0.1. Either turn on \"Allow other devices\" and use this device's Wi-Fi address, or forward the port from the PC:",
        "mcpServerPageCopy": "Copy",
        "mcpServerPageCopied": "Copied",
        "mcpServerPagePortTitle": "Server port",
        "mcpServerPagePortInvalid": "Enter a port between 1024 and 65535",
        "mcpServerPageTransportHttp": "Streamable HTTP",
        "mcpServerPageTransportSse": "SSE (legacy)",
    },
    "app_zh": {
        "mcpServerPageTitle": "内置 MCP 服务端",
        "mcpServerPageEnable": "对外提供本工作区",
        "mcpServerPageStatusRunning": "监听中",
        "mcpServerPageStatusStopped": "已停止",
        "mcpServerPageListenerHint": "通过 MCP 暴露 proot 终端。任何能连到本机的客户端，都能在助手使用的工作目录里执行命令。",
        "mcpServerPageEndpoints": "客户端地址",
        "mcpServerPageToken": "访问令牌",
        "mcpServerPageTokenHint": "客户端需以如下方式携带：Authorization: Bearer <令牌>",
        "mcpServerPageNetwork": "网络",
        "mcpServerPagePort": "端口",
        "mcpServerPageAllowLan": "允许其他设备连接",
        "mcpServerPageAllowLanHint": "关闭时只监听 127.0.0.1，仅本机可用。开启后同一 Wi-Fi 下的电脑才能连上。",
        "mcpServerPagePcHint": "电脑上的客户端看不到手机的 127.0.0.1。要么打开「允许其他设备连接」并使用本机的 Wi-Fi 地址，要么在电脑上把端口转发过来：",
        "mcpServerPageCopy": "复制",
        "mcpServerPageCopied": "已复制",
        "mcpServerPagePortTitle": "服务端端口",
        "mcpServerPagePortInvalid": "请输入 1024 到 65535 之间的端口",
        "mcpServerPageTransportHttp": "Streamable HTTP",
        "mcpServerPageTransportSse": "SSE（旧版）",
    },
    "app_zh_Hans": {
        "mcpServerPageTitle": "内置 MCP 服务端",
        "mcpServerPageEnable": "对外提供本工作区",
        "mcpServerPageStatusRunning": "监听中",
        "mcpServerPageStatusStopped": "已停止",
        "mcpServerPageListenerHint": "通过 MCP 暴露 proot 终端。任何能连到本机的客户端，都能在助手使用的工作目录里执行命令。",
        "mcpServerPageEndpoints": "客户端地址",
        "mcpServerPageToken": "访问令牌",
        "mcpServerPageTokenHint": "客户端需以如下方式携带：Authorization: Bearer <令牌>",
        "mcpServerPageNetwork": "网络",
        "mcpServerPagePort": "端口",
        "mcpServerPageAllowLan": "允许其他设备连接",
        "mcpServerPageAllowLanHint": "关闭时只监听 127.0.0.1，仅本机可用。开启后同一 Wi-Fi 下的电脑才能连上。",
        "mcpServerPagePcHint": "电脑上的客户端看不到手机的 127.0.0.1。要么打开「允许其他设备连接」并使用本机的 Wi-Fi 地址，要么在电脑上把端口转发过来：",
        "mcpServerPageCopy": "复制",
        "mcpServerPageCopied": "已复制",
        "mcpServerPagePortTitle": "服务端端口",
        "mcpServerPagePortInvalid": "请输入 1024 到 65535 之间的端口",
        "mcpServerPageTransportHttp": "Streamable HTTP",
        "mcpServerPageTransportSse": "SSE（旧版）",
    },
    "app_zh_Hant": {
        "mcpServerPageTitle": "內建 MCP 伺服端",
        "mcpServerPageEnable": "對外提供本工作區",
        "mcpServerPageStatusRunning": "監聽中",
        "mcpServerPageStatusStopped": "已停止",
        "mcpServerPageListenerHint": "透過 MCP 暴露 proot 終端。任何能連到本機的用戶端，都能在助手使用的工作目錄裡執行命令。",
        "mcpServerPageEndpoints": "用戶端位址",
        "mcpServerPageToken": "存取權杖",
        "mcpServerPageTokenHint": "用戶端需以如下方式攜帶：Authorization: Bearer <權杖>",
        "mcpServerPageNetwork": "網路",
        "mcpServerPagePort": "連接埠",
        "mcpServerPageAllowLan": "允許其他裝置連線",
        "mcpServerPageAllowLanHint": "關閉時只監聽 127.0.0.1，僅本機可用。開啟後同一 Wi-Fi 下的電腦才能連上。",
        "mcpServerPagePcHint": "電腦上的用戶端看不到手機的 127.0.0.1。要麼開啟「允許其他裝置連線」並使用本機的 Wi-Fi 位址，要麼在電腦上把連接埠轉送過來：",
        "mcpServerPageCopy": "複製",
        "mcpServerPageCopied": "已複製",
        "mcpServerPagePortTitle": "伺服端連接埠",
        "mcpServerPagePortInvalid": "請輸入 1024 到 65535 之間的連接埠",
        "mcpServerPageTransportHttp": "Streamable HTTP",
        "mcpServerPageTransportSse": "SSE（舊版）",
    },
}


def patch_arb(name: str, entries: dict) -> None:
    path = ROOT / f"lib/l10n/{name}.arb"
    if not path.is_file():
        check(False, f"missing lib/l10n/{name}.arb")
        return
    text = path.read_text(encoding="utf-8")
    if '"mcpServerPageTitle"' in text:
        print(f"  {name}: already applied")
        return
    check(text.startswith("{\n"), f"{name}: unexpected ARB shape")
    if not text.startswith("{\n"):
        return
    for key in entries:
        check(f'"{key}"' not in text, f"{name}: key {key} already exists")
    block = "".join(
        f'  "{key}": {json.dumps(value, ensure_ascii=False)},\n'
        for key, value in entries.items()
    )
    path.write_text("{\n" + block + text[2:], encoding="utf-8")
    print(f"  {name}.arb: +{len(entries)} strings")


for path in (PAGE, MCP_PAGE, LUCIDE):
    check(path.is_file(), f"missing {path.relative_to(ROOT)}")

for arb, entries in STRINGS.items():
    patch_arb(arb, entries)

patch(
    MCP_PAGE,
    "import '../widgets/mcp_timeout_sheet.dart';",
    "import '../widgets/mcp_timeout_sheet.dart';\nimport 'mcp_server_page.dart';",
    "mcp_page: import",
)

patch(
    MCP_PAGE,
    """        actions: [
          Tooltip(
            message: l10n.mcpTimeoutSettingsTooltip,""",
    """        actions: [
          Tooltip(
            message: l10n.mcpServerPageTitle,
            child: _TactileIconButton(
              icon: Lucide.SquareTerminal,
              color: cs.onSurface,
              size: 22,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute<void>(builder: (_) => const McpServerPage()),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Tooltip(
            message: l10n.mcpTimeoutSettingsTooltip,""",
    "mcp_page: entry action",
)

page = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""
mcp_page = MCP_PAGE.read_text(encoding="utf-8") if MCP_PAGE.is_file() else ""
lucide = LUCIDE.read_text(encoding="utf-8") if LUCIDE.is_file() else ""

# 4. Only icons the adapter actually defines; a missing one is a build error.
for icon in ("SquareTerminal", "ArrowLeft", "Copy", "RefreshCw", "Globe", "KeyRound", "Edit"):
    check(f"IconData {icon} " in lucide, f"Lucide.{icon} is not defined")
for icon in ("Server",):
    check(f"IconData {icon} " not in lucide, f"Lucide.{icon} exists after all")

# 3. Reachability.
check("import 'mcp_server_page.dart';" in mcp_page, "mcp_page does not import the page")
check("const McpServerPage()" in mcp_page, "mcp_page does not push the page")

# 1. Every getter the page uses must be declared in the template.
template = (ROOT / "lib/l10n/app_en.arb").read_text(encoding="utf-8")
for key in STRINGS["app_en"]:
    check(f'"{key}"' in template, f"{key} is not declared in app_en.arb")
used = set()
marker = "l10n.mcpServerPage"
index = 0
while True:
    index = page.find(marker, index)
    if index < 0:
        break
    end = index + len(marker)
    while end < len(page) and (page[end].isalnum() or page[end] == "_"):
        end += 1
    used.add(page[index + len("l10n.") : end])
    index = end
for key in sorted(used):
    check(key in STRINGS["app_en"], f"page reads {key}, which is not in this patch")

if failures:
    print("FAILED:")
    for item in failures:
        print("  -", item)
    sys.exit(1)

print("OK: the MCP server has a settings page")
print(f"  page   : {len(page.splitlines())} lines, {len(used)} strings used")
print("  entry  : MCP page AppBar -> Lucide.SquareTerminal")
print("  l10n   : en / zh / zh_Hans / zh_Hant (+19 strings each)")