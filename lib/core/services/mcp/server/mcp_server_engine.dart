import 'package:mcp_client/mcp_client.dart' as mcp;

/// A tool the server exposes: the schema a client reads, plus what runs it.
class McpServerTool {
  const McpServerTool({
    required this.name,
    required this.description,
    required this.inputSchema,
    required this.invoke,
  });

  /// The name a client passes to `tools/call`.
  final String name;

  /// Description used verbatim in the `tools/list` entry.
  final String description;

  /// JSON Schema for the arguments object.
  final Map<String, dynamic> inputSchema;

  /// Runs the tool. Throwing is allowed — the engine turns it into an error
  /// result, so one bad call never tears down the session.
  final Future<McpToolResult> Function(Map<String, dynamic> arguments) invoke;

  /// The `tools/list` entry for this tool.
  Map<String, dynamic> toDefinition() => <String, dynamic>{
    'name': name,
    'description': description,
    'inputSchema': inputSchema,
  };
}

/// The outcome of one tool call, in MCP's `tools/call` result shape.
class McpToolResult {
  const McpToolResult(this.text) : isError = false;
  const McpToolResult.error(this.text) : isError = true;

  /// The single text block handed back to the client.
  final String text;

  /// True when the tool failed. MCP carries this in the *result*, not as a
  /// JSON-RPC error, because the call itself was served.
  final bool isError;

  Map<String, dynamic> toPayload() => <String, dynamic>{
    'content': <Map<String, dynamic>>[
      <String, dynamic>{'type': 'text', 'text': text},
    ],
    'isError': isError,
  };
}

/// A JSON-RPC 2.0 MCP server, generic over the tools it serves.
///
/// Speaks the subset an external client needs — `initialize`, `tools/list`,
/// `tools/call`, plus `ping` — and nothing else. `kelivo_fetch_server.dart`
/// proved this wire behaviour against the real `mcp_client` library; this keeps
/// it, but separates the protocol from the tool surface so each can be tested
/// and replaced on its own.
class McpServerEngine {
  McpServerEngine({
    required this.serverName,
    required this.serverVersion,
    required List<McpServerTool> tools,
    void Function(String message)? diag,
  }) : _tools = <String, McpServerTool>{
         for (final tool in tools) tool.name: tool,
       },
       _diag = diag;

  /// Name reported in `initialize`'s `serverInfo`.
  final String serverName;

  /// Version reported in `initialize`'s `serverInfo`.
  final String serverVersion;

  final Map<String, McpServerTool> _tools;
  final void Function(String message)? _diag;

  bool _closed = false;

  /// Handles one message (or a JSON-RPC batch) and returns the reply.
  ///
  /// Returns `null` when nothing must be sent back: a notification, or a
  /// message that arrived after [close].
  Future<dynamic> handleMessage(dynamic message) async {
    if (_closed) return null;
    if (message is List) {
      final replies = <dynamic>[];
      for (final entry in message) {
        final reply = await _handleSingle(entry);
        if (reply != null) replies.add(reply);
      }
      return replies.isEmpty ? null : replies;
    }
    return _handleSingle(message);
  }

  /// Names of the tools served, for diagnostics.
  List<String> get toolNames => _tools.keys.toList();

  /// Stops answering. In-flight calls are unaffected.
  void close() => _closed = true;

  // --------------------------------------------------------------- internals

  Future<Map<String, dynamic>?> _handleSingle(dynamic raw) async {
    if (raw is! Map) {
      return _error(null, code: _invalidRequest, message: 'Invalid Request');
    }
    final request = raw.cast<String, dynamic>();
    final id = request['id'];
    final method = (request['method'] ?? '').toString();
    final params = request['params'] is Map
        ? (request['params'] as Map).cast<String, dynamic>()
        : <String, dynamic>{};

    // A notification carries no id and must not be answered. `initialized` is
    // the one clients always send, so logging it keeps handshakes traceable.
    if (id == null) {
      _diag?.call('mcp: notification ${method.isEmpty ? '(none)' : method}');
      return null;
    }

    switch (method) {
      case mcp.McpProtocol.methodInitialize:
        return _ok(id, result: _initializeResult());
      case mcp.McpProtocol.methodListTools:
        return _ok(id, result: _listToolsResult());
      case mcp.McpProtocol.methodCallTool:
        return _callTool(id, params);
      case 'ping':
        return _ok(id, result: <String, dynamic>{});
      default:
        return _error(
          id,
          code: _methodNotFound,
          message: 'Method not found: $method',
        );
    }
  }

  Map<String, dynamic> _initializeResult() => <String, dynamic>{
    'protocolVersion': mcp.McpProtocol.defaultVersion,
    'serverInfo': <String, dynamic>{
      'name': serverName,
      'version': serverVersion,
    },
    'capabilities': <String, dynamic>{
      'tools': <String, dynamic>{'listChanged': false},
    },
  };

  Map<String, dynamic> _listToolsResult() => <String, dynamic>{
    'tools': _tools.values.map((tool) => tool.toDefinition()).toList(),
  };

  Future<Map<String, dynamic>> _callTool(
    dynamic id,
    Map<String, dynamic> params,
  ) async {
    final name = (params['name'] ?? '').toString();
    final tool = _tools[name];
    if (tool == null) {
      return _error(id, code: _invalidParams, message: 'Unknown tool: $name');
    }
    final arguments = params['arguments'] is Map
        ? (params['arguments'] as Map).cast<String, dynamic>()
        : <String, dynamic>{};
    try {
      final result = await tool.invoke(arguments);
      return _ok(id, result: result.toPayload());
    } catch (error) {
      return _ok(id, result: McpToolResult.error('$error').toPayload());
    }
  }

  Map<String, dynamic> _ok(dynamic id, {required Map<String, dynamic> result}) =>
      <String, dynamic>{'jsonrpc': '2.0', 'id': id, 'result': result};

  Map<String, dynamic> _error(
    dynamic id, {
    required int code,
    required String message,
  }) => <String, dynamic>{
    'jsonrpc': '2.0',
    'id': id,
    'error': <String, dynamic>{'code': code, 'message': message},
  };

  static const int _invalidRequest = -32600;
  static const int _methodNotFound = -32601;
  static const int _invalidParams = -32602;
}
