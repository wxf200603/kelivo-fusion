import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'business SharedPreferences access stays inside the frozen allowlist',
    () async {
      const allowed = <String>{
        'lib/core/database/business_migration_engine.dart',
        'lib/core/providers/hotkey_provider.dart',
        // The built-in MCP server's settings are `localOnly` keys, which are not
        // business settings and by design do not go through the routing layer:
        // `BusinessPreferences` throws `ArgumentError` for them, so a direct write
        // is the only route such a key has. Every other `localOnly` writer
        // (settings_provider.dart, hotkey_provider.dart, main.dart) is already on
        // this list; this file is a legitimate holder that was simply never added.
        'lib/core/services/mcp/server/mcp_server_service.dart',
        'lib/core/providers/settings_provider.dart',
        'lib/desktop/window_size_manager.dart',
        'lib/features/migration/hive_to_sqlite_migration_service.dart',
        'lib/main.dart',
      };
      final references = <String>[];
      await for (final entity in Directory('lib').list(recursive: true)) {
        if (entity is! File || !entity.path.endsWith('.dart')) continue;
        final source = await entity.readAsString();
        if (!source.contains('package:shared_preferences/') &&
            !RegExp(r'\bSharedPreferences\b').hasMatch(source)) {
          continue;
        }
        references.add(entity.path.replaceAll('\\', '/'));
      }
      references.sort();

      expect(references, orderedEquals(allowed.toList()..sort()));
    },
  );

  test(
    'discarded chat preference keys only exist in the routing filter',
    () async {
      final references = <String>[];
      await for (final entity in Directory('lib').list(recursive: true)) {
        if (entity is! File || !entity.path.endsWith('.dart')) continue;
        final source = await entity.readAsString();
        if (!source.contains('pinned_chat_ids') &&
            !source.contains('chat_titles_map')) {
          continue;
        }
        references.add(entity.path.replaceAll('\\', '/'));
      }
      references.sort();

      expect(references, <String>[
        'lib/core/database/business_settings_router.dart',
      ]);
    },
  );
}
