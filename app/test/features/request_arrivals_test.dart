import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/request_repository.dart';
import 'package:encore/data/sync/sync_scheduler.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

void main() {
  setUpAll(loadAppFonts);

  Future<void> addRequest(
    AppDatabase db,
    int serverId, {
    required String artist,
    String? album,
  }) =>
      db.into(db.requests).insert(RequestsCompanion.insert(
            serverId: serverId,
            kind: album == null ? 'artist' : 'album',
            title: album ?? artist,
            artist: artist,
            album: Value(album),
            state: RequestState.requested,
            createdAtMs: 0,
            updatedAtMs: 0,
          ));

  testWidgets('a requested album that arrived is resolved and announced once',
      (tester) async {
    final status = StreamController<SyncStatus>();
    addTearDown(status.close);
    final app = await pumpApp(tester, overrides: [
      syncStatusProvider.overrideWith((ref) => status.stream),
    ]);
    // "Kodama" by Alcest is in the seeded library; the other one is not.
    await addRequest(app.db, app.serverId, artist: 'Alcest', album: 'Kodama');
    await addRequest(app.db, app.serverId,
        artist: 'Mastodon', album: 'Leviathan');

    await settle(tester); // the server id has reached the providers
    status.add(SyncStatus(lastSuccessAt: DateTime.utc(2026, 10, 15, 12)));
    await settle(tester);

    final rows = await app.db.select(app.db.requests).get();
    final byAlbum = {for (final r in rows) r.album: r.state};
    expect(byAlbum['Kodama'], RequestState.inLibrary);
    expect(byAlbum['Leviathan'], RequestState.requested);
    expect(find.text('"Kodama" is now in your library'), findsOneWidget);

    // A later sync with nothing new says nothing more.
    await tester.pump(const Duration(seconds: 6)); // snackbar timeout
    status.add(SyncStatus(lastSuccessAt: DateTime.utc(2026, 10, 15, 13)));
    await settle(tester);
    expect(find.textContaining('is now in your library'), findsNothing);
    await closeApp(tester, app.db);
  });

  testWidgets('several arrivals are summarised', (tester) async {
    final status = StreamController<SyncStatus>();
    addTearDown(status.close);
    final app = await pumpApp(tester, overrides: [
      syncStatusProvider.overrideWith((ref) => status.stream),
    ]);
    await addRequest(app.db, app.serverId, artist: 'Alcest', album: 'Kodama');
    await addRequest(app.db, app.serverId,
        artist: 'Periphery', album: 'The Walk');

    await settle(tester); // the server id has reached the providers
    status.add(SyncStatus(lastSuccessAt: DateTime.utc(2026, 10, 15, 12)));
    await settle(tester);

    expect(
        find.text('2 requested items are now in your library'), findsOneWidget);
    await closeApp(tester, app.db);
  });
}
