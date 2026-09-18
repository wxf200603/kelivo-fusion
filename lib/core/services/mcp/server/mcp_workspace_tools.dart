import 'dart:convert';

import 'package:flutter/services.dart';

import '../../operit/operit_js_tools_service.dart';
import 'mcp_server_engine.dart';

/// The tool surface the workspace server hands to foreign MCP clients.
///
/// Every tool is a thin adapter over the Operit bridge, because the terminal
/// work already exists there: `KelivoWorkspaceHost` owns the proot launcher, the
/// retained PTY and `GlobalWorkspace`. Routing through it is what makes an
/// external client share the *model's* working directory — a second, separate
/// shell would silently diverge from it on the first `cd`.
class McpWorkspaceTools {
  McpWorkspaceTools({this.diag});

  /// Where these tools' log lines go. The service points it at the same
  /// `operit_js_diag.log` as the rest of the fusion; null keeps them quiet.
  final void Function(String message)? diag;

  /// The bridge channel shared with the Operit runtime.
  static const MethodChannel _channel = MethodChannel('app.operit_js');

  /// The package whose terminal family the server exposes.
  static const String _package = 'super_admin';

  /// The four terminal tools, mirroring `super_admin` one for one.
  ///
  /// `terminal` and `terminal_input` are the ones the acceptance criteria name:
  /// the first proves the shared working directory, the second is how a foreign
  /// client interrupts a long command (ctrl + c).
  List<McpServerTool> build() => <McpServerTool>[
    McpServerTool(
      name: 'terminal',
      description:
          '在融合版 Kelivo 的 Ubuntu (proot) 环境里执行命令并收集输出。'
          '工作目录与 App 内的模型共用：调用会继承全局工作区，命令里的 `cd` 也会写回全局。'
          '建议每次都显式传 timeoutMs，避免命令挂住；'
          '不要用 `set -e` / `set -o errexit`，那会让会话退出并卡死。'
          '传入同一个 sessionId 可复用同一个终端会话，上下文连贯。',
      inputSchema: <String, dynamic>{
        'type': 'object',
        'properties': <String, dynamic>{
          'command': <String, dynamic>{
            'type': 'string',
            'description': '要执行的命令',
          },
          'timeoutMs': <String, dynamic>{
            'type': 'string',
            'description': '超时毫秒数（字符串，最低 3000）。不传则前台默认 15000',
          },
          'sessionId': <String, dynamic>{
            'type': 'string',
            'description': '目标终端会话 ID；不传则使用默认会话',
          },
        },
        'required': <String>['command'],
      },
      invoke: (arguments) => _call('terminal', arguments),
    ),
    McpServerTool(
      name: 'terminal_wait',
      description:
          '等待同一终端会话中的上一条命令执行完成。'
          '与 sleep 不同：命令真正结束就提前返回。超时会取消当前命令并保留会话。',
      inputSchema: <String, dynamic>{
        'type': 'object',
        'properties': <String, dynamic>{
          'timeoutMs': <String, dynamic>{
            'type': 'string',
            'description': '超时毫秒数（字符串，最低 3000）。默认 300000',
          },
          'sessionId': <String, dynamic>{
            'type': 'string',
            'description': '目标终端会话 ID；不传则使用默认会话',
          },
        },
      },
      invoke: (arguments) => _call('terminal_wait', arguments),
    ),
    McpServerTool(
      name: 'terminal_getscreen',
      description: '获取目标终端会话当前可见的屏幕内容（读会话自身的字节缓冲，含提示符与全屏程序）。',
      inputSchema: <String, dynamic>{
        'type': 'object',
        'properties': <String, dynamic>{
          'sessionId': <String, dynamic>{
            'type': 'string',
            'description': '目标终端会话 ID；不传则使用默认会话',
          },
        },
      },
      invoke: (arguments) => _call('terminal_getscreen', arguments),
    ),
    McpServerTool(
      name: 'terminal_input',
      description:
          '向目标终端会话写入输入，用于交互式程序与中断。'
          'control=ctrl 且 input=c 即发送 Ctrl+C（中断长命令）。',
      inputSchema: <String, dynamic>{
        'type': 'object',
        'properties': <String, dynamic>{
          'input': <String, dynamic>{
            'type': 'string',
            'description': '写入终端的文本',
          },
          'control': <String, dynamic>{
            'type': 'string',
            'description': '控制键：enter / tab / esc / ctrl',
          },
          'sessionId': <String, dynamic>{
            'type': 'string',
            'description': '目标终端会话 ID；不传则使用默认会话',
          },
        },
      },
      invoke: (arguments) => _call('terminal_input', arguments),
    ),
  ];

  // --------------------------------------------------------------- internals

  Future<McpToolResult> _call(
    String tool,
    Map<String, dynamic> arguments,
  ) async {
    await _mark('mcp: incoming tool call $tool');
    try {
      await _ensureRuntime();
      var raw = await _invoke(tool, arguments);

      // A runtime that re-attached since the last warm-up drops the workspace it
      // was pointed at and refuses every call with this marker. Re-configuring
      // is the same recovery the in-app path uses, so a model switch cannot
      // leave the server answering errors forever.
      if (_runtimeLost(raw)) {
        await _mark('mcp: runtime not configured, re-configuring');
        await OperitJsToolsService.instance.warmUp();
        raw = await _invoke(tool, arguments);
      }

      // The shared directory is the point of the whole server, so record what
      // the host reports after a command ran: a `cd` inside the command shows
      // up here, which is what makes the sync verifiable from the log alone.
      if (tool == 'terminal') {
        final cwd = await _workspaceCwd();
        if (cwd != null && cwd.isNotEmpty) {
          await _mark('mcp: sync global cwd = $cwd');
        }
      }

      if (raw == null || raw.isEmpty) {
        return const McpToolResult.error(
          'the workspace bridge returned an empty result',
        );
      }
      return McpToolResult(raw);
    } catch (error) {
      return McpToolResult.error('$error');
    }
  }

  /// The bridge returns the tool's JSON result verbatim, as the model sees it.
  Future<String?> _invoke(String tool, Map<String, dynamic> arguments) =>
      _channel.invokeMethod<String>('callTool', <String, dynamic>{
        'pkg': _package,
        'tool': tool,
        'argsJson': jsonEncode(arguments),
      });

  /// Configures the native runtime once, if the in-app path has not already.
  Future<void> _ensureRuntime() async {
    final bridge = OperitJsToolsService.instance;
    if (bridge.isReady || bridge.isWarming) return;
    await bridge.warmUp();
  }

  /// The host's current shared working directory, for the log only.
  ///
  /// Best effort on purpose: this is evidence, never a precondition, so a host
  /// that cannot answer it does not fail the tool call.
  Future<String?> _workspaceCwd() async {
    try {
      return await _channel.invokeMethod<String>('workspaceCwd');
    } catch (_) {
      return null;
    }
  }

  static bool _runtimeLost(String? raw) =>
      raw != null && raw.contains('runtime not configured');

  /// Mirrors an event into `operit_js_diag.log` — the only log a release build
  /// exposes on device. Never throws: diagnostics must not fail a tool call.
  Future<void> _mark(String message) async {
    diag?.call(message);
    try {
      await _channel.invokeMethod<void>('diag', <String, dynamic>{
        'msg': message,
      });
    } catch (_) {}
  }
}