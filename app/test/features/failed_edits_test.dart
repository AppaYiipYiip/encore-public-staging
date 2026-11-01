import 'dart:convert';

import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/outbox.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// A change the server turned down is shown, not silently undone (B1).
void main() {
  Future<void> openSync(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/settings/sync');
    await settle(tester);
  }

  Future<int> park(AppDatabase db, int serverId, String reason) =>
      db.into(db.outbox).insert(OutboxCompanion.insert(
            serverId: serverId,
            kind: OutboxKind.playlistUpdate,
            payloadJson: jsonEncode({
              'playlistId': 'p1',
              'add': ['t1', 't2'],
            }),
            createdAtMs: 1,
            status: const Value('failed'),
            lastError: Value(reason),
          ));

  testWidgets('nothing is shown when every change was saved', (tester) async {
    final app = await pumpApp(tester);
    await openSync(tester);

    expect(find.text('Songs in your library'), findsOneWidget);
    expect(find.textContaining('could not be saved'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('a rejected change is named, explained, and can be retried',
      (tester) async {
    final app = await pumpApp(tester);
    final id = await park(app.db, app.serverId, 'User is not authorised');
    await openSync(tester);

    expect(find.text('1 change could not be saved'), findsOneWidget);
    expect(find.text('Add songs to a playlist'), findsOneWidget);
    expect(find.text('User is not authorised'), findsOneWidget);

    await tester.tap(find.byTooltip('Try again'));
    await settle(tester);

    final row = await (app.db.select(app.db.outbox)
          ..where((o) => o.id.equals(id)))
        .getSingle();
    expect(row.status, 'pending');
    expect(find.textContaining('could not be saved'), findsNothing,
        reason: 'it is back in the queue, so the warning goes away');
    await closeApp(tester, app.db);
  });

  testWidgets('"Let it go" forgets the change', (tester) async {
    final app = await pumpApp(tester);
    await park(app.db, app.serverId, 'Not allowed');
    await park(app.db, app.serverId, 'Not allowed either');
    await openSync(tester);

    expect(find.text('2 changes could not be saved'), findsOneWidget);
    expect(find.text('Try all again'), findsOneWidget);

    await tester.tap(find.byTooltip('Let it go').first);
    await settle(tester);

    expect(find.text('1 change could not be saved'), findsOneWidget);
    expect(await app.db.select(app.db.outbox).get(), hasLength(1));
    await closeApp(tester, app.db);
  });
}
