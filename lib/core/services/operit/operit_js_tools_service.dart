import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:path/path.dart' as p;

import '../../../utils/app_directories.dart';
import '../../../features/home/services/tool_approval_service.dart';

/// Bridges Operit's JS tool packages — running on the ported QuickJS engine —
/// into Kelivo's tool loop.
///
/// The native side ([OperitJsRuntime] over `app.operit_js`) owns package
/// loading and the whole host-API dispatch table; this class only:
///
/// 1. points it at the proot environment during [warmUp],
/// 2. converts the packages' `METADATA` tool schemas into the OpenAI-shaped
///    definitions Kelivo's tool loop expects,
/// 3. routes tool calls back to `callTool`.
///
/// Tool names are namespaced as `operit_<package>_<tool>` so they can never
/// collide with Kelivo's built-ins (`calculate`, `get_time_info`, …).
class OperitJsToolsService {
  OperitJsToolsService._();

  static final OperitJsToolsService instance = OperitJsToolsService._();

  static const MethodChannel _channel = MethodChannel('app.operit_js');

  /// Prefix for every tool this service owns.
  static const String namePrefix = 'operit_';

  /// Provider-side limit on function names.
  static const int _maxNameLength = 64;

  /// Packages exposed to the model.
  ///
  /// Deliberately short: registering all 31 packages would add ~150 tools and
  /// blow past provider tool limits. `super_admin` is the one that lets the
  /// model actually run terminal commands, which is the current milestone.
  static const List<String> enabledPackages = <String>['super_admin'];

  List<Map<String, dynamic>> _definitions = const <Map<String, dynamic>>[];

  /// Exported provider-safe name -> the `<package>:<tool>` the native side
  /// expects. Kept explicitly instead of parsed back out of the name, so the
  /// mapping stays lossless when both halves contain underscores
  /// (`super_admin` + `terminal_wait`).
  final Map<String, ({String packageName, String tool})> _routes =
      <String, ({String packageName, String tool})>{};

  bool _ready = false;
  bool _warming = false;
  String? _lastError;

  /// Whether [warmUp] succeeded and definitions are usable.
  bool get isReady => _ready;

  /// True while a [warmUp] is in flight (callers should not start another).
  bool get isWarming => _warming;

  /// Schemas to hand to the tool loop (empty until [warmUp] succeeds).
  List<Map<String, dynamic>> get definitions => _definitions;

  /// Why the last [warmUp] failed, for diagnostics.
  String? get lastError => _lastError;

  /// True when [toolName] belongs to this service.
  bool owns(String toolName) => _routes.containsKey(toolName);

  /// Configures the native runtime and caches tool schemas.
  ///
  /// Safe to call repeatedly; a failure leaves [isReady] false and records
  /// [lastError] rather than throwing, so a broken environment never breaks
  /// the chat path.
  Future<bool> warmUp() async {
    if (_warming) return false;
    _warming = true;
    try {
      await _mark('warmUp:enter');
      final envDir = await AppDirectories.getEnvironmentDirectory();
      await _mark('env=${envDir.path}');
      final configured = await _channel.invokeMethod<String>('configure', {
        'rootfsDir': p.join(envDir.path, 'rootfs'),
        'tmpDir': p.join(envDir.path, 'tmp'),
        'cwd': '/root',
      });

      await _mark('configured=$configured');
      final status = _decodeMap(configured);
      if (status['usable'] != true) {
        _fail('workspace not usable (rootfs missing or proot libs absent)');
        return false;
      }

      final raw = await _channel.invokeMethod<String>('listTools');
      await _mark('listTools=${raw?.length ?? 0} chars');
      return _install(raw);
    } catch (error) {
      await _mark('error=$error');
      _fail('$error');
      return false;
    } finally {
      _warming = false;
    }
  }
/// Executes a namespaced tool call and returns the result for the model.
  ///
  /// These packages include terminal/root tools, so when an [approvalService]
  /// is supplied the call goes through the same approval gate Kelivo's
  /// workspace tools use — the user stays in control of what actually runs.
  Future<Object?> handle(
    String toolName,
    Map<String, dynamic> args, {
    ToolApprovalService? approvalService,
    String? toolCallId,
    String? conversationId,
  }) async {
    final route = _routes[toolName];
    if (route == null) return _errorResult('unknown tool: $toolName');

    try {
      if (approvalService != null) {
        final id = (toolCallId ?? '').trim();
        final decision = await approvalService.requestApproval(
          toolCallId: id.isEmpty
              ? '${toolName}_${DateTime.now().microsecondsSinceEpoch}'
              : id,
          toolName: toolName,
          arguments: args,
          conversationId: conversationId,
        );
        if (!decision.approved) {
          return _errorResult(
            decision.denyReason ?? 'User denied the tool call',
          );
        }
      }

      final raw = await _channel.invokeMethod<String>('callTool', {
        'pkg': route.packageName,
        'tool': route.tool,
        'argsJson': jsonEncode(args),
      });
      if (raw == null || raw.isEmpty) return _errorResult('empty result');

      // The native side returns the tool's JSON result verbatim; pass it
      // through unchanged so the model sees the same shape Operit produces.
      final decoded = jsonDecode(raw);
      return decoded;
    } catch (error) {
      return _errorResult('$error');
    }
  }

  // --------------------------------------------------------------- internals

  /// Mirrors progress into the native diagnostic log (`operit_js_diag.log`
  /// in the app's private files dir).
  ///
  /// Release builds give us no logcat output at all — Dart's `print` is not
  /// redirected there — so this is the only way to see how far [warmUp] gets
  /// on a real device. Never throws.
  Future<void> _mark(String message) async {
    try {
      await _channel.invokeMethod<void>('diag', {'msg': message});
    } catch (_) {}
  }

  void _fail(String message) {
    _ready = false;
    _definitions = const <Map<String, dynamic>>[];
    _routes.clear();
    _lastError = message;
    debugPrint('[operit_js] bridge unavailable: $message');
  }

  /// Replaces the cached schemas and routes atomically, so a partial parse
  /// can never leave [definitions] and [_routes] disagreeing.
  bool _install(String? rawJson) {
    final definitions = <Map<String, dynamic>>[];
    final routes = <String, ({String packageName, String tool})>{};
    _collect(rawJson, definitions, routes);

    _definitions = definitions;
    _routes
      ..clear()
      ..addAll(routes);
    _ready = definitions.isNotEmpty;
    _lastError = _ready
        ? null
        : 'no tools found for ${enabledPackages.join(', ')} '
              'in assets/operit_packages';
    if (_ready) {
      debugPrint(
        '[operit_js] ${definitions.length} tools registered: '
        '${routes.keys.join(', ')}',
      );
    } else {
      debugPrint('[operit_js] $_lastError');
    }
    return _ready;
  }

  /// Reads the native `listTools` payload, which is one entry per package:
  ///
  /// ```json
  /// [{"package": "super_admin", "tools": [
  ///    {"name": "super_admin:terminal", "description": "...",
  ///     "parameters": {"type": "object", "properties": {}, "required": []}}]}]
  /// ```
  void _collect(
    String? rawJson,
    List<Map<String, dynamic>> definitions,
    Map<String, ({String packageName, String tool})> routes,
  ) {
    if (rawJson == null || rawJson.isEmpty) return;
    final decoded = jsonDecode(rawJson);
    if (decoded is! List) return;

    for (final entry in decoded) {
      if (entry is! Map) continue;
      final packageName = entry['package']?.toString() ?? '';
      if (!enabledPackages.contains(packageName)) continue;

      final tools = entry['tools'];
      if (tools is! List) continue;

      for (final tool in tools) {
        if (tool is! Map) continue;

        // The native side emits `<package>:<tool>`; accept a bare name too.
        final wire = tool['name']?.toString() ?? '';
        if (wire.isEmpty) continue;
        final toolName = wire.contains(':') ? wire.split(':').last : wire;
        if (toolName.isEmpty) continue;

        final exported = _exportName(packageName, toolName);
        if (routes.containsKey(exported)) continue;

        routes[exported] = (packageName: packageName, tool: toolName);
        definitions.add(<String, dynamic>{
          'type': 'function',
          'function': <String, dynamic>{
            'name': exported,
            'description': _describe(packageName, toolName, tool['description']),
            'parameters': _parameters(tool['parameters']),
          },
        });
      }
    }
  }

  /// `operit_<package>_<tool>`, sanitised for providers and length-capped.
  String _exportName(String packageName, String toolName) {
    final name = '$namePrefix${_sanitize(packageName)}_${_sanitize(toolName)}';
    return name.length <= _maxNameLength
        ? name
        : name.substring(0, _maxNameLength);
  }

  /// Providers only accept `[a-zA-Z0-9_-]` in function names.
  String _sanitize(String value) =>
      value.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');

  String _describe(String packageName, String toolName, Object? raw) {
    final description = raw?.toString().trim() ?? '';
    if (description.isNotEmpty) return description;
    return 'Operit package `$packageName` tool `$toolName`, running on the '
        'ported QuickJS engine.';
  }

  /// Re-uses the JSON Schema the native side built from the package METADATA,
  /// falling back to an open object when a package declares nothing usable.
  Map<String, dynamic> _parameters(Object? raw) {
    if (raw is Map) {
      final parameters = <String, dynamic>{};
      raw.forEach((key, value) {
        if (key is String) parameters[key] = value;
      });
      if (parameters['type'] == 'object') {
        parameters['properties'] ??= <String, dynamic>{};
        return parameters;
      }
    }
    return <String, dynamic>{
      'type': 'object',
      'properties': <String, dynamic>{},
      'additionalProperties': true,
    };
  }

  Map<String, dynamic> _decodeMap(String? raw) {
    if (raw == null || raw.isEmpty) return const <String, dynamic>{};
    final decoded = jsonDecode(raw);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  }

  Map<String, dynamic> _errorResult(String message) => <String, dynamic>{
    'error': 'operit_js',
    'message': message,
  };
}