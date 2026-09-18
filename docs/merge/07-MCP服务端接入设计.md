# 07 - MCP 服务端接入（方案 A）设计

> 2026-09-18。需求来源：用户口述 6 条验收需求。
> 本文件在动代码前冻结口径；实施后按真机证据回填。

## 目标

让**外部** MCP 客户端（Cline / Claude Desktop / Operit 本体）用标准 MCP 协议，
调用融合版 Kelivo 内置的 **proot 终端**与**全局工作区**能力。

一句话验收：*外部客户端连上 → 调 terminal → 命令在 proot 里跑，且和模型用的是同一个工作目录。*

## 现状（已核实，不是转述）

| 事实 | 证据 |
|---|---|
| Kelivo 的 MCP **客户端**很完整 | `mcp_provider.dart`(2918) / `mcp_tool_service.dart`(517) / `mcp_config_import.dart` / OAuth 全套 |
| `dependencies/mcp_client` 是**纯客户端**库 | pubspec 自述 "MCP client"；只有 `ClientTransport` 抽象，**无任何服务端实现** |
| 服务端**只有先例**，没有通用实现 | `lib/core/services/mcp/kelivo_fetch/kelivo_fetch_server.dart`(557)：手写最小 JSON-RPC 引擎（initialize / tools/list / tools/call）+ `KelivoInMemoryClientTransport` |
| `workspace_stdio_transport.dart` 方向**相反** | 它 `implements ClientTransport`，作用是「Kelivo 当客户端，在 guest 里拉起一个 stdio server」。**不能当服务端传输用** |
| 终端能力有**两条链** | A 链 `WorkspacePlugin`(`app.workspace`)→`ExecRunner`/`PtySessions`：给终端 UI，**无 GlobalWorkspace**。B 链 `OperitJsRuntime`→`OperitHostDispatcher`→`KelivoWorkspaceHost`+`GlobalWorkspace`：给 Operit 包，**含全局工作区** |

**结论：需求 2/4/5 只在 B 链成立。**

## 关键决策

1. **服务端实现放在 Dart 侧。**
   `dart:io HttpServer` + `jsonEncode` 是标准能力，SSE / Streamable HTTP 都好写；
   `kelivo_fetch_server.dart` 已给出服务端范式（含 `mcp.McpProtocol.*` 常量的用法）；
   与 MCP 客户端同侧，便于统一 UI 管理。**Kotlin 侧零改动。**

2. **工具执行复用 B 链**，不另起一套：
   `MCP Server → OperitJsToolsService.instance.handle('operit_super_admin_<tool>', args)`
   → `app.operit_js` → `KelivoWorkspaceHost` → `GlobalWorkspace` + PTY。
   由此：**需求 2（继承/回写全局 CWD）与需求 4（目录不存在降级 + 埋点）天然成立**——
   它们本来就是 `GlobalWorkspace.sessionCwd()` / `follow()` / `fallback()` 的行为。

3. **传输**：以 **Streamable HTTP**（`POST /mcp`）为主，兼容 **SSE**（`GET /sse` + `POST /message`）。
   原因：Cline / Claude Desktop 跑在 PC 上，只能走网络；Operit 本体同机走 `127.0.0.1`。

4. **监听与鉴权**：默认 `127.0.0.1`（同机可用，最小暴露面）；
   可选开放 `0.0.0.0` 供局域网 PC 客户端；一律要求 `Authorization: Bearer <token>`。

5. **审批策略**：B 链 `OperitJsToolsService.handle()` 需要 `ToolApprovalService`，缺失就 **fail-closed**。
   服务端场景的调用方是用户自己在外部客户端里配的，因此提供一个显式策略：
   默认「需要审批」，可切「受信客户端免审批」。**绝不默认放开**。

## 6 条验收需求 → 落点

| # | 需求 | 落点 | 验收证据 |
|---|---|---|---|
| 1 | 服务端在 proot 工作区内运行，复用已有运行时 | 复用 B 链（`OperitJsWorkspace`），不新开 proot | 日志 `mcp: server start ...`；命令确实在 guest 内执行 |
| 2 | 调 terminal 自动继承全局 CWD；`cd` 回写全局 | `GlobalWorkspace.sessionCwd()` / `follow()`（既有） | `pwd` 输出 == prefs 里的 `global_cwd`；`cd /x` 后 `mcp: sync global cwd = /x` |
| 3 | 支持 `tools/list`、`tools/call`（+ `initialize`） | 新 `McpServerEngine` | 客户端 `tools/list` 拿到 terminal 工具；`tools/call` 返回文本结果 |
| 4 | 目标目录不存在 → 降级回 root + 埋点 | `GlobalWorkspace.restore()/fallback()`（既有） | 删掉 cwd 目录后，下一条命令在 `/root` 跑，日志有 `workspace: fallback to root` |
| 5 | 埋点 `mcp: incoming tool call terminal`、`mcp: sync global cwd` | 新增（Dart 侧调用 `diag`） | 两条字符串出现在 `operit_js_diag.log` |
| 6 | 长命令可中断（透传 Ctrl+C） | `super_admin` 的 input 工具 + `ctrlCode`（既有） | 起 `sleep 999`，发 `ctrl=c`，命令退出 |

## 文件清单（拟）

```
lib/core/services/mcp/server/
  mcp_server_engine.dart        # JSON-RPC 2.0：initialize / tools/list / tools/call
  mcp_workspace_tools.dart      # 工具面：terminal / terminal_screen / terminal_input
  mcp_http_transport.dart       # Streamable HTTP + SSE，监听 + Bearer 鉴权
  mcp_server_service.dart       # 生命周期：start/stop/status（Provider 持有）
scripts/patch_mcp_server_*.py   # 每处改动配锚点断言（项目约定）
```

## 验收方法（真机）

1. `curl` 打 `/mcp` 走一遍 `initialize` → `tools/list` → `tools/call(terminal, {command:"pwd"})`；
2. 比对上一步输出与 `kelivo_workspace.xml` 的 `global_cwd`；
3. 日志里两条 `mcp:` 埋点齐备；
4. 再用 Operit 本体（同机，`127.0.0.1`）真实接入一次。
