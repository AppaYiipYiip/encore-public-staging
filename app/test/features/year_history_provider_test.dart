import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/app/session.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/features/year/year_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fake_http.dart';
import '../support/test_app.dart';

/// Found on the phone (build 22): `mia` listened to a song to its end, the
/// server recorded the play, and her Year in Music still said "Nothing to count
/// yet" until the app was restarted, because the history was read once and kept
/// for the whole session.
void main() {
  late AppDatabase db;
  late FakeHttpAdapter adapter;
  late ServerSession session;
  var served = 0; // how many plays the server has

  setUp(() async {
    served = 0;
    db = AppDatabase(NativeDatabase.memory());
    await Seed.library(db);
    adapter = FakeHttpAdapter(routes: {
      '/auth/login': (_) => const FakeResponse.json({'token': 't'}),
      '/api/scrobble': (_) => FakeResponse.json(
            [
              for (var i = 0; i < served; i++)
                {
                  'id': i,
                  'mediaFileId': 'al1-t1',
                  'submissionTime': 1792234918 + i,
                },
            ],
            headers: {'X-Total-Count': '$served'},
          ),
    });
    final server = (await db.select(db.servers).get()).first;
    session = await ServerSession.create(
      verifyAddresses: false,
      db: db,
      server: server,
      password: 'x',
      dio: fakeDio(adapter),
    );
  });

  tearDown(() async {
    await session.dispose();
    await db.close();
  });

  ProviderContainer container({required Duration keep}) {
    final c = ProviderContainer(overrides: [
      sessionProvider.overrideWith((ref) async => session),
      playHistoryKeepProvider.overrideWithValue(keep),
    ]);
    addTearDown(c.dispose);
    return c;
  }

  Future<void> screenClosed() async {
    // The provider is released a moment after its last listener goes.
    await Future<void>.delayed(const Duration(milliseconds: 20));
  }

  test('a play made after the screen was closed shows when it is opened again',
      () async {
    final c = container(keep: Duration.zero);
    final open = c.listen(playHistoryProvider, (_, __) {});
    expect(await c.read(playHistoryProvider.future), isEmpty);
    open.close();
    await screenClosed();

    served = 1; // the person listened to a song meanwhile

    expect(await c.read(playHistoryProvider.future), hasLength(1));
  });

  test('flipping between month, year and all time does not read it again',
      () async {
    final c = container(keep: const Duration(minutes: 2));
    final open = c.listen(playHistoryProvider, (_, __) {});
    await c.read(playHistoryProvider.future);
    open.close();
    await screenClosed();
    served = 1;

    final again = await c.read(playHistoryProvider.future);

    expect(again, isEmpty, reason: 'kept for two minutes after the screen');
    expect(adapter.requests.where((r) => r.uri.path == '/api/scrobble'),
        hasLength(1));
  });
}
