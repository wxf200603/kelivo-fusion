import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:mcp_client/mcp_client.dart' as mcp;

import 'mcp_server_engine.dart';

/// Serves [McpServerEngine] over HTTP, in both shapes a client might expect.
///
/// Streamable HTTP (`POST /mcp`) is the modern shape and the primary target.
/// The legacy SSE pair (`GET /sse` announcing `POST /message`) stays because
/// plenty of working setups still point at an SSE URL, and supporting both here
/// costs a route table rather than a second implementation.
///
/// The engine is transport-agnostic, so this class only moves bytes: read,
/// authorise, dispatch, reply.
class McpHttpTransport {
  McpHttpTransport({
    required this.engine,
    required this.token,
    InternetAddress? address,
    this.port = 0,
    this.diag,
  }) : address = address ?? InternetAddress.loopbackIPv4;

  /// The protocol implementation every request is routed into.
  final McpServerEngine engine;

  /// The token a client must present.
  ///
  /// Chosen by the settings layer rather than generated here, so the value the
  /// UI shows is exactly the value in force. The server treats a valid token as
  /// the user's authorisation: it is opened deliberately, and it runs root
  /// shells, so possession is the gate.
  final String token;

  /// Interface to bind. Loopback by default — a PC client that needs the LAN
  /// has to opt in explicitly.
  final InternetAddress address;

  /// Port to bind; 0 asks the OS for a free one.
  final int port;

  /// Where this transport's log lines go. The service points it at the same
  /// `operit_js_diag.log` as the rest of the fusion; null keeps it quiet.
  final void Function(String message)? diag;

  HttpServer? _server;
  final Map<String, _SseChannel> _streams = <String, _SseChannel>{};

  /// The port actually bound, or 0 while stopped.
  int get boundPort => _server?.port ?? 0;

  /// True while the listener is up.
  bool get isRunning => _server != null;

  static const String _streamablePath = '/mcp';
  static const String _legacySsePath = '/sse';
  static const String _legacyMessagePath = '/message';
  static const String _sessionHeader = 'Mcp-Session-Id';
  static const Duration _keepAliveInterval = Duration(seconds: 15);

  /// Binds and starts serving; returns the port in use.
  ///
  /// Idempotent: a second call while running just reports the current port.
  Future<int> start() async {
    final running = _server;
    if (running != null) return running.port;

    final server = await HttpServer.bind(address, port);
    _server = server;
    diag?.call('mcp: server listening on ${address.address}:${server.port}');
    server.listen(
      (request) => unawaited(_handleRequest(request)),
      onError: (Object error) => diag?.call('mcp: server error $error'),
    );
    return server.port;
  }

  /// Closes every open stream and stops listening.
  Future<void> stop() async {
    for (final channel in _streams.values.toList()) {
      await channel.close();
    }
    _streams.clear();
    final server = _server;
    _server = null;
    await server?.close(force: true);
    if (server != null) diag?.call('mcp: server stopped');
  }

  // --------------------------------------------------------------- routing

  Future<void> _handleRequest(HttpRequest request) async {
    final response = request.response;
    _applyCors(response);
    try {
      // A browser sends the preflight without the Authorization header, so it
      // has to be answered before the token is checked.
      if (request.method == 'OPTIONS') {
        response.statusCode = HttpStatus.noContent;
        await response.close();
        return;
      }

      if (!_authorized(request)) {
        diag?.call(
          'mcp: rejected ${request.method} ${request.uri.path} (bad token)',
        );
        await _writeJson(response, HttpStatus.unauthorized, <String, dynamic>{
          'error': 'unauthorized',
        });
        return;
      }

      final path = request.uri.path;
      if (path == _streamablePath) {
        await _handleStreamable(request, response);
        return;
      }
      if (path == _legacySsePath && request.method == 'GET') {
        await _openEventStream(
          response,
          _SseChannel(_newSessionId()),
          preamble: <String, String>{
            'endpoint': '$_legacyMessagePath?sessionId=',
          },
        );
        return;
      }
      if (path == _legacyMessagePath && request.method == 'POST') {
        await _handleLegacyMessage(request, response);
        return;
      }

      await _writeJson(response, HttpStatus.notFound, <String, dynamic>{
        'error': 'not found: $path',
      });
    } catch (error) {
      diag?.call('mcp: request failed $error');
      try {
        await _writeJson(response, HttpStatus.internalServerError, {
          'error': '$error',
        });
      } catch (_) {
        // The peer is already gone; there is nothing left to answer.
      }
    }
  }

  /// `POST` carries calls, `GET` opens the server→client stream, `DELETE` says
  /// the session is over.
  Future<void> _handleStreamable(
    HttpRequest request,
    HttpResponse response,
  ) async {
    if (request.method == 'POST') {
      await _handleStreamablePost(request, response);
      return;
    }
    if (request.method == 'GET') {
      if (!_wantsEventStream(request)) {
        response.statusCode = HttpStatus.methodNotAllowed;
        await response.close();
        return;
      }
      await _openEventStream(response, _SseChannel(_newSessionId()));
      return;
    }
    if (request.method == 'DELETE') {
      response.statusCode = HttpStatus.ok;
      await response.close();
      return;
    }
    response.statusCode = HttpStatus.methodNotAllowed;
    await response.close();
  }

  Future<void> _handleStreamablePost(
    HttpRequest request,
    HttpResponse response,
  ) async {
    final message = await _readJson(request, response);
    if (message == null) return;

    final reply = await engine.handleMessage(message);

    // Notifications have no reply: MCP answers 202 with no body for them.
    if (reply == null) {
      response.statusCode = HttpStatus.accepted;
      await response.close();
      return;
    }

    // Issued on the handshake, so a client tracking several servers can tell
    // them apart; later requests may echo it back.
    if (_isInitialize(message)) {
      response.headers.set(_sessionHeader, _newSessionId());
    }

    if (_wantsEventStream(request)) {
      await _writeEventStreamOnce(response, reply);
      return;
    }
    await _writeJson(response, HttpStatus.ok, reply);
  }

  /// The legacy transport: the message arrives here, the reply leaves on the
  /// stream opened by `GET /sse`.
  Future<void> _handleLegacyMessage(
    HttpRequest request,
    HttpResponse response,
  ) async {
    final sessionId = request.uri.queryParameters['sessionId'] ?? '';
    final channel = _streams[sessionId];
    if (channel == null) {
      await _writeJson(response, HttpStatus.notFound, <String, dynamic>{
        'error': 'unknown session: $sessionId',
      });
      return;
    }

    final message = await _readJson(request, response);
    if (message == null) return;

    final reply = await engine.handleMessage(message);
    if (reply != null) {
      for (final entry in reply is List ? reply : <dynamic>[reply]) {
        if (entry is Map) channel.send(entry.cast<String, dynamic>());
      }
    }
    // The reply travels on the stream, so accepting the message is the whole
    // answer here.
    response.statusCode = HttpStatus.accepted;
    await response.close();
  }

  // ---------------------------------------------------------------- streams

  /// Opens a server→client SSE stream and holds it until the client leaves.
  ///
  /// [preamble] carries the legacy transport's `endpoint` event; the modern
  /// transport has no equivalent and passes nothing.
  Future<void> _openEventStream(
    HttpResponse response,
    _SseChannel channel, {
    Map<String, String>? preamble,
  }) async {
    _streams[channel.id] = channel;

    response.statusCode = HttpStatus.ok;
    response.headers.contentType = ContentType(
      'text',
      'event-stream',
      charset: 'utf-8',
    );
    response.headers.set(HttpHeaders.cacheControlHeader, 'no-cache');
    response.headers.set(_sessionHeader, channel.id);

    final preambleEntries = preamble?.entries.toList() ?? const [];
    for (final entry in preambleEntries) {
      // The legacy endpoint event carries a relative URL with a placeholder for
      // the session id, because the id is only known once the channel exists.
      final data = entry.key == 'endpoint'
          ? '${entry.value}${channel.id}'
          : entry.value;
      response.write('event: ${entry.key}\ndata: $data\n\n');
    }
    await response.flush();
    diag?.call('mcp: stream open ${channel.id}');

    final subscription = channel.events.listen((payload) {
      try {
        response.write(
          'event: message\ndata: ${jsonEncode(payload)}\n\n',
        );
      } catch (_) {
        // A late message for a client that already left is not an error worth
        // surfacing; the stream teardown below is the real signal.
      }
    });
    // Writes do not throw until flushed, so an idle stream would only notice a
    // vanished client on the next message; a comment frame keeps it honest and
    // stops proxies from closing it.
    final keepAlive = Timer.periodic(_keepAliveInterval, (_) {
      try {
        response.write(': keep-alive\n\n');
        unawaited(response.flush().catchError((Object _) {}));
      } catch (_) {
        // The peer vanished. A write only fails once the socket is gone, and
        // `done` follows, which is where the stream is torn down.
      }
    });

    try {
      await channel.done;
    } finally {
      await subscription.cancel();
      keepAlive.cancel();
      _streams.remove(channel.id);
      try {
        await response.close();
      } catch (_) {
        // Already closed by the peer.
      }
      diag?.call('mcp: stream closed ${channel.id}');
    }
  }

  /// Writes one reply as a single-event SSE response and ends the stream.
  ///
  /// A client that only accepts `text/event-stream` still gets its answer
  /// without keeping a connection open for a push that will never come.
  Future<void> _writeEventStreamOnce(
    HttpResponse response,
    dynamic payload,
  ) async {
    response.statusCode = HttpStatus.ok;
    response.headers.contentType = ContentType(
      'text',
      'event-stream',
      charset: 'utf-8',
    );
    response.headers.set(HttpHeaders.cacheControlHeader, 'no-cache');
    for (final entry in payload is List ? payload : <dynamic>[payload]) {
      response.write('event: message\ndata: ${jsonEncode(entry)}\n\n');
    }
    await response.close();
  }

  // ----------------------------------------------------------------- plumbing

  /// Reads and decodes the request body, answering 400 itself on bad input.
  ///
  /// Returns `null` when it has already replied, so callers just bail out.
  Future<dynamic> _readJson(
    HttpRequest request,
    HttpResponse response,
  ) async {
    final body = await utf8.decoder.bind(request).join();
    if (body.trim().isEmpty) {
      await _writeJson(response, HttpStatus.badRequest, <String, dynamic>{
        'error': 'empty body',
      });
      return null;
    }
    try {
      return jsonDecode(body);
    } catch (error) {
      await _writeJson(response, HttpStatus.badRequest, <String, dynamic>{
        'error': 'invalid json: $error',
      });
      return null;
    }
  }

  Future<void> _writeJson(
    HttpResponse response,
    int status,
    Object? payload,
  ) async {
    response.statusCode = status;
    response.headers.contentType = ContentType.json;
    response.write(jsonEncode(payload));
    await response.close();
  }

  /// A stream is only chosen when the client did not also accept plain JSON,
  /// which is the cheaper reply and the one a request/response client wants.
  bool _wantsEventStream(HttpRequest request) {
    final accept = request.headers.value(HttpHeaders.acceptHeader) ?? '';
    if (accept.contains('application/json')) return false;
    return accept.contains('text/event-stream');
  }

  bool _authorized(HttpRequest request) {
    if (token.isEmpty) return false;
    final header = request.headers.value(HttpHeaders.authorizationHeader);
    if (header == null || !header.startsWith('Bearer ')) return false;
    return _constantTimeEquals(header.substring(7).trim(), token);
  }

  /// Compares without stopping at the first difference, so a wrong token cannot
  /// be recovered one character at a time from response timing.
  static bool _constantTimeEquals(String a, String b) {
    if (a.length != b.length) return false;
    var difference = 0;
    for (var index = 0; index < a.length; index++) {
      difference |= a.codeUnitAt(index) ^ b.codeUnitAt(index);
    }
    return difference == 0;
  }

  /// A CORS preflight never carries the token, so the headers must be set on
  /// every reply — including the ones that reject.
  static void _applyCors(HttpResponse response) {
    response.headers.set('Access-Control-Allow-Origin', '*');
    response.headers.set(
      'Access-Control-Allow-Headers',
      'Authorization, Content-Type, Mcp-Session-Id, Accept',
    );
    response.headers.set(
      'Access-Control-Allow-Methods',
      'GET, POST, DELETE, OPTIONS',
    );
    response.headers.set('Access-Control-Expose-Headers', _sessionHeader);
  }

  static bool _isInitialize(dynamic message) {
    if (message is List) return message.any(_isInitialize);
    if (message is! Map) return false;
    return message['method'] == mcp.McpProtocol.methodInitialize;
  }

  static String _newSessionId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }
}

/// One open server→client stream.
class _SseChannel {
  _SseChannel(this.id);

  final String id;
  final StreamController<Map<String, dynamic>> _events =
      StreamController<Map<String, dynamic>>.broadcast();
  final Completer<void> _closed = Completer<void>();

  Stream<Map<String, dynamic>> get events => _events.stream;

  /// Completes when the stream is torn down.
  Future<void> get done => _closed.future;

  /// Queues a message for the client; a closed channel drops it rather than
  /// throwing into the protocol path.
  void send(Map<String, dynamic> payload) {
    if (!_events.isClosed) _events.add(payload);
  }

  Future<void> close() async {
    if (!_closed.isCompleted) _closed.complete();
    if (!_events.isClosed) await _events.close();
  }
}