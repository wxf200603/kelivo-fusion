import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'mcp_http_transport.dart';
import 'mcp_server_engine.dart';
import 'mcp_workspace_tools.dart';

/// Owns the outbound MCP server: whether it runs, on which interface and port,
/// and the token a client must present.
///
/// A [ChangeNotifier] for the same reason `McpProvider` is one — the settings
/// page reads this state and should not poll for it. A single instance, for the
/// same reason `OperitJsToolsService` is one: the server is a property of the
/// app, not of a conversation.
///
/// The token is stored in `SharedPreferences`, which is where the rest of this
/// app keeps provider API keys. That is deliberate rather than an oversight: the
/// file lives in the app's private directory, no other app can read it, and
/// pulling in a second secret store would add a native dependency for no
/// additional protection on a rooted-vs-unrooted threat model that this file
/// already loses either way.
class McpServerService extends ChangeNotifier {
  McpServerService._();

  /// The one instance the app talks to.
  static final McpServerService instance = McpServerService._();

  /// The diagnostic channel, shared with the Operit bridge so MCP events land in
  /// the same `operit_js_diag.log` as everything else the fusion logs.
  static const MethodChannel _diagChannel = MethodChannel('app.operit_js');

  static const String _enabledKey = 'mcp_server_enabled';
  static const String _lanKey = 'mcp_server_allow_lan';
  static const String _portKey = 'mcp_server_port';
  static const String _tokenKey = 'mcp_server_token';

  /// The port a fresh install listens on.
  ///
  /// Fixed rather than ephemeral on purpose: a client is configured with a URL,
  /// and a port that moved on every launch would break it silently.
  static const int defaultPort = 8765;

  /// 32 bytes of entropy, base64url encoded — long enough that guessing is not a
  /// strategy, short enough to paste into a client by hand.
  static const int _tokenBytes = 32;

  bool _enabled = false;
  bool _allowLan = false;
  bool _running = false;
  bool _loaded = false;
  int _port = defaultPort;
  String _token = '';
  String? _lastError;

  McpHttpTransport? _transport;
  McpServerEngine? _engine;

  /// Whether the stored settings have been read.
  bool get isLoaded => _loaded;

  /// Whether the user wants the server up.
  bool get enabled => _enabled;

  /// Whether it is listening right now.
  bool get isRunning => _running;

  /// True when clients outside this device may connect.
  bool get allowLan => _allowLan;

  /// The configured port.
  int get port => _port;

  /// The port actually bound, or 0 while stopped.
  int get boundPort => _transport?.boundPort ?? 0;

  /// The bearer token a client must present.
  String get token => _token;

  /// Why the last start attempt failed, if it did.
  String? get lastError => _lastError;

  /// The URL a Streamable HTTP client is configured with.
  String get streamableUrl => _urlFor('/mcp');

  /// The URL for a client that only speaks the older SSE transport.
  String get sseUrl => _urlFor('/sse');

  /// The device's non-loopback IPv4 addresses, for the "connect from a PC" hint.
  ///
  /// Best effort: this is advice shown to the user, never a precondition, so a
  /// device with no network answers with an empty list instead of throwing.
  static Future<List<String>> lanAddresses() async {
    try {
      final interfaces = await NetworkInterface.list(
        type: InternetAddressType.IPv4,
        includeLoopback: false,
      );
      return <String>[
        for (final interface in interfaces)
          for (final address in interface.addresses) address.address,
      ];
    } catch (_) {
      return const <String>[];
    }
  }

  /// Reads the stored settings and starts the server if the user left it on.
  ///
  /// Called once at startup, next to `OperitJsToolsService.warmUp()`. Safe to
  /// call again: the settings are simply re-read.
  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      _enabled = prefs.getBool(_enabledKey) ?? false;
      _allowLan = prefs.getBool(_lanKey) ?? false;
      _port = prefs.getInt(_portKey) ?? defaultPort;
      _token = prefs.getString(_tokenKey) ?? '';
      final hadToken = _token.isNotEmpty;
      if (!hadToken) {
        _token = _generateToken();
        await prefs.setString(_tokenKey, _token);
        // Logged beside the write rather than trusted instead of it: a
        // `setString` that returns has already been seen to store nothing
        // here, so the line that settles it is `stored=true` next launch.
        unawaited(_mark('mcp: wrote token len=${_token.length}chars'));
      }
      _loaded = true;
      // Reported through the channel rather than trusting the write: on device
      // this line is what tells a failed persist apart from a failed read.
      unawaited(
        _mark(
          'mcp: settings loaded enabled=$_enabled port=$_port '
          'token=${_token.length}chars stored=$hadToken',
        ),
      );
      notifyListeners();
      if (_enabled) await start();
    } catch (error, stack) {
      // Without this the exception vanished into the zone: the future is
      // started with `unawaited`, and the app's logger ships switched off.
      unawaited(_mark('mcp: load failed: $error'));
      debugPrint('[mcp_server] load failed: $error\n$stack');
    }
  }

  /// Starts the listener; returns true when it is up.
  ///
  /// Safe to call while already running — the existing port is reported and
  /// nothing is rebound.
  Future<bool> start() async {
    if (_running) return true;
    _lastError = null;

    // A token is the whole authorisation story, so there is never a window
    // where the server runs without one.
    if (_token.isEmpty) {
      _token = _generateToken();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_tokenKey, _token);
      unawaited(
        _mark('mcp: wrote token before start len=${_token.length}chars'),
      );
      notifyListeners();
    }

    try {
      _engine = McpServerEngine(
        serverName: 'kelivo-workspace',
        serverVersion: '1.0.0',
        tools: McpWorkspaceTools().build(),
        diag: _diag,
      );
      _transport = McpHttpTransport(
        engine: _engine!,
        token: _token,
        address: _allowLan
            ? InternetAddress.anyIPv4
            : InternetAddress.loopbackIPv4,
        port: _port,
        diag: _diag,
      );
      final bound = await _transport!.start();
      _running = true;
      unawaited(
        _mark(
          'mcp: server ready on ${_allowLan ? '0.0.0.0' : '127.0.0.1'}:$bound',
        ),
      );
    } catch (error) {
      _lastError = '$error';
      _running = false;
      await _teardown();
      unawaited(_mark('mcp: start failed: $error'));
    }
    notifyListeners();
    return _running;
  }

  /// Stops the listener and releases the engine.
  Future<void> stop() async {
    if (!_running && _transport == null) return;
    await _teardown();
    _running = false;
    notifyListeners();
    unawaited(_mark('mcp: server stopped'));
  }

  /// Turns the server on or off and remembers the choice.
  Future<void> setEnabled(bool value) async {
    if (_enabled == value) return;
    _enabled = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool(_enabledKey, value);
      unawaited(_mark('mcp: wrote enabled=$value'));
    } catch (error) {
      // The switch still applies to this run; only its persistence failed, and
      // that is exactly the kind of half-truth worth naming in the log.
      unawaited(_mark('mcp: setEnabled($value) could not persist: $error'));
    }
    unawaited(_mark('mcp: setEnabled $value'));
    notifyListeners();
    if (value) {
      await start();
    } else {
      await stop();
    }
  }

  /// Moves the listener between loopback and every interface.
  ///
  /// A restart is unavoidable: the socket is already bound to one address, and
  /// widening that in place is not something a bound listener allows.
  Future<void> setAllowLan(bool value) async {
    if (_allowLan == value) return;
    _allowLan = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_lanKey, value);
    unawaited(_mark('mcp: wrote allow_lan=$value'));
    notifyListeners();
    if (_running) {
      await stop();
      await start();
    }
  }

  /// Changes the port, restarting the listener when it is running.
  ///
  /// Ports below 1024 are refused rather than attempted: binding them needs
  /// privileges this app does not have, and the failure would only surface as an
  /// opaque socket error at start time.
  Future<void> setPort(int value) async {
    if (value < 1024 || value > 65535 || value == _port) return;
    _port = value;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_portKey, value);
    unawaited(_mark('mcp: wrote port=$value'));
    notifyListeners();
    if (_running) {
      await stop();
      await start();
    }
  }

  /// Replaces the token, disconnecting every client until they are updated.
  ///
  /// The running transport holds the old value in its constructor, so the new
  /// one only takes effect after a restart.
  Future<String> regenerateToken() async {
    _token = _generateToken();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_tokenKey, _token);
    unawaited(_mark('mcp: wrote regenerated token len=${_token.length}chars'));
    notifyListeners();
    if (_running) {
      await stop();
      await start();
    }
    unawaited(_mark('mcp: token regenerated'));
    return _token;
  }

  // --------------------------------------------------------------- internals

  String _urlFor(String path) => 'http://127.0.0.1:$_port$path';

  Future<void> _teardown() async {
    final transport = _transport;
    _transport = null;
    await transport?.stop();
    _engine?.close();
    _engine = null;
  }

  void _diag(String message) => unawaited(_mark(message));

  /// Mirrors a message into the diagnostic log. Never throws: a log that breaks
  /// the server would be worse than a missing line.
  Future<void> _mark(String message) async {
    try {
      await _diagChannel.invokeMethod<void>('diag', <String, dynamic>{
        'msg': message,
      });
    } catch (_) {}
  }

  static String _generateToken() {
    final random = Random.secure();
    final bytes = List<int>.generate(_tokenBytes, (_) => random.nextInt(256));
    return base64Url.encode(bytes).replaceAll('=', '');
  }

  @override
  void dispose() {
    // The socket outlives this object's notifications, so the transport is
    // stopped directly: notifying a disposed notifier would throw, and leaving
    // the port bound would outlive the app's own shutdown.
    final transport = _transport;
    _transport = null;
    _engine?.close();
    _engine = null;
    _running = false;
    unawaited(transport?.stop() ?? Future<void>.value());
    super.dispose();
  }
}
