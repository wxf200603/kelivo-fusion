import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:Kelivo/core/database/app_database.dart';
import 'package:Kelivo/core/database/chat_database_repository.dart';
import 'package:Kelivo/core/models/chat_message.dart';
import 'package:Kelivo/core/models/conversation.dart';

void main() {
  late AppDatabase database;
  late ChatDatabaseRepository repository;

  setUp(() async {
    database = AppDatabase(NativeDatabase.memory());
    repository = ChatDatabaseRepository(database);
    await repository.ensureReady();
  });

  tearDown(() => repository.close());

  test('reasoning fields round-trip through putMessage/getMessage', () async {
    await repository.putConversation(
      Conversation(id: 'c-reasoning', title: 'Reasoning'),
    );

    final startedAt = DateTime.utc(2026, 9, 19, 12, 0, 0);
    final finishedAt = DateTime.utc(2026, 9, 19, 12, 0, 5);
    const segments = '[{"text":"think","start":0,"end":5}]';

    final message = ChatMessage(
      id: 'm-reasoning',
      role: 'assistant',
      content: 'answer',
      conversationId: 'c-reasoning',
      groupId: 'g-reasoning',
      version: 0,
      timestamp: DateTime.utc(2026, 9, 19, 12, 0, 6),
      reasoningStartAt: startedAt,
      reasoningFinishedAt: finishedAt,
      reasoningSegmentsJson: segments,
    );

    await repository.putMessage(message, messageOrder: 0);

    final loaded = await repository.getMessage('m-reasoning');
    expect(loaded, isNotNull);
    expect(loaded!.reasoningStartAt, startedAt);
    expect(loaded.reasoningFinishedAt, finishedAt);
    expect(loaded.reasoningSegmentsJson, segments);
  });
}
