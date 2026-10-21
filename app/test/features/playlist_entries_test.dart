import 'package:drift/drift.dart' show Value;
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);

  testWidgets('opening a big playlist fetches its entries on demand',
      (tester) async {
    final fetched = <String>[];
    final app = await pumpApp(tester, overrides: [
      ensurePlaylistProvider.overrideWith((ref, id) async {
        fetched.add(id);
      }),
    ]);

    // A server-generated playlist background sync skipped: 3 songs known,
    // no entries stored yet.
    await app.db.into(app.db.playlists).insert(PlaylistsCompanion.insert(
          serverId: app.serverId,
          id: 'big',
          name: 'Everything',
          songCount: const Value(3),
          readonly: const Value(true),
        ));

    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/playlist/big');
    await settle(tester);

    expect(fetched, ['big']);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    // The fetch lands: rows appear without any refresh gesture.
    for (var i = 0; i < 3; i++) {
      await app.db.into(app.db.playlistEntries).insert(
            PlaylistEntriesCompanion.insert(
              serverId: app.serverId,
              playlistId: 'big',
              position: i,
              trackId: 'al3-t${i + 1}',
            ),
          );
    }
    await settle(tester);
    expect(find.text('Opening The'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsNothing);

    await closeApp(tester, app.db);
  });

  testWidgets('a failed fetch offers Try again', (tester) async {
    var attempts = 0;
    final app = await pumpApp(tester, overrides: [
      ensurePlaylistProvider.overrideWith((ref, id) async {
        attempts++;
        throw StateError('offline');
      }),
    ]);
    await app.db.into(app.db.playlists).insert(PlaylistsCompanion.insert(
          serverId: app.serverId,
          id: 'big',
          name: 'Everything',
          songCount: const Value(3),
        ));

    final element = tester.element(find.byType(Scaffold).first);
    GoRouter.of(element).go('/home/playlist/big');
    await settle(tester);

    expect(find.text('Try again'), findsOneWidget);
    await tester.tap(find.text('Try again'));
    await settle(tester);
    expect(attempts, greaterThanOrEqualTo(2));

    await closeApp(tester, app.db);
  });
}
