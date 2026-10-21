import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/sync/sync_state_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

/// When the sync holds back a far smaller server answer, the person is told and
/// can choose to follow it (docs/23, B6). Otherwise nothing is shown.
void main() {
  Future<void> openSync(WidgetTester tester) async {
    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/settings/sync');
    await settle(tester);
  }

  testWidgets('nothing is shown while the library follows the server',
      (tester) async {
    final app = await pumpApp(tester);
    await openSync(tester);

    expect(find.textContaining('far fewer songs'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('a held-back answer is explained and can be followed',
      (tester) async {
    final app = await pumpApp(tester);
    await app.db.into(app.db.syncState).insert(SyncStateCompanion.insert(
          serverId: app.serverId,
          key: SyncStateStore.shrinkNotice,
          value: '40 of 100 songs',
        ));
    await openSync(tester);

    expect(find.text('Your server lists far fewer songs than before'),
        findsOneWidget);
    expect(find.textContaining('40 of 100 songs'), findsOneWidget);
    expect(find.textContaining('left as it was'), findsOneWidget);
    expect(find.text('Follow the server'), findsOneWidget);
    await closeApp(tester, app.db);
  });

  testWidgets('the notice goes away when the guard lets go', (tester) async {
    final app = await pumpApp(tester);
    await app.db.into(app.db.syncState).insert(SyncStateCompanion.insert(
          serverId: app.serverId,
          key: SyncStateStore.shrinkNotice,
          value: '40 of 100 songs',
        ));
    await openSync(tester);
    expect(find.textContaining('far fewer songs'), findsOneWidget);

    await SyncStateStore(app.db, app.serverId)
        .set(SyncStateStore.shrinkNotice, null);
    await settle(tester);

    expect(find.textContaining('far fewer songs'), findsNothing);
    await closeApp(tester, app.db);
  });
}
