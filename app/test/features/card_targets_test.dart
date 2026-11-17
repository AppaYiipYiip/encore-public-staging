import 'dart:async';

import 'package:drift/drift.dart' hide isNull, isNotNull;
import 'package:drift/native.dart';
import 'package:encore/app/providers.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/repos/release_store.dart';
import 'package:encore/features/downloads/download_card_jobs.dart';
import 'package:encore/features/downloads/download_providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// docs/design S-95 (P2-29): the downloads the card follows, read the real way (the pins of the phone and the names in its database), not handed over
/// by a test: a loose song is never a card, a release is one download, the size the phone knows is carried, and when the pins change (a second Download
/// while one runs) the list is never empty for a moment, because an empty list would take the running card away and make it again.
void main() {
  late AppDatabase db;
  late StreamController<List<PinRow>> pins;

  PinRow pin(String type, String id) => PinRow(
        serverId: 1,
        targetType: type,
        targetId: id,
        quality: 'original',
        createdAtMs: 0,
      );

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: 1,
          id: 'pl_1',
          name: 'Prog snob',
          songCount: const Value(217),
        ));
    await db.into(db.playlists).insert(PlaylistsCompanion.insert(
          serverId: 1,
          id: 'pl_one',
          name: 'One song',
          songCount: const Value(1),
        ));
    pins = StreamController<List<PinRow>>();
  });

  tearDown(() async {
    await pins.close();
    await db.close();
  });

  ProviderContainer start() {
    final c = ProviderContainer(overrides: [
      databaseProvider.overrideWithValue(db),
      pinsProvider.overrideWith((ref) => pins.stream),
      phoneReleasesProvider.overrideWith((ref) => Stream.value({
            'cat:1': const PhoneRelease(
                refIds: ['a', 'b'], title: 'Kodama', download: true),
            'cat:2': const PhoneRelease(
                refIds: ['s'], title: 'A single', download: true),
          })),
    ]);
    addTearDown(c.dispose);
    return c;
  }

  Future<void> turn() => Future<void>.delayed(const Duration(milliseconds: 30));

  test(
      'the downloads are the playlists and the releases, with the size the phone knows',
      () async {
    final c = start();
    final seen = <List<CardTarget>>[];
    c.listen(cardTargetsProvider, (_, next) => seen.add(next),
        fireImmediately: true);

    pins.add([
      pin('playlist', 'pl_1'),
      pin('playlist', 'pl_one'),
      pin('track', 'a'),
      pin('track', 'b'),
      pin('track', 's'),
      pin('track', 'a_loose_song'),
    ]);
    await turn();

    final byName = {for (final t in c.read(cardTargetsProvider)) t.name: t};
    expect(byName.keys.toSet(), {'Prog snob', 'One song', 'Kodama', 'A single'},
        reason: 'a loose song is never a card; a release is ONE download');
    expect(byName['Prog snob']!.knownSongs, 217);
    expect(byName['Prog snob']!.playlistId, 'pl_1');
    expect(byName['One song']!.knownSongs, 1);
    expect(byName['Kodama']!.knownSongs, 2);
    expect(byName['Kodama']!.key, 'release:cat:1');
    expect(byName['A single']!.knownSongs, 1);
  });

  test(
      'a second Download while one runs never makes the list empty for a moment',
      () async {
    final c = start();
    final seen = <List<CardTarget>>[];
    c.listen(cardTargetsProvider, (_, next) => seen.add(next),
        fireImmediately: true);

    pins.add([pin('playlist', 'pl_1')]);
    await turn();
    expect(c.read(cardTargetsProvider).map((t) => t.name), ['Prog snob']);
    final before = seen.length;

    pins.add([pin('playlist', 'pl_1'), pin('track', 'a'), pin('track', 'b')]);
    await turn();

    expect(c.read(cardTargetsProvider).map((t) => t.name).toSet(),
        {'Prog snob', 'Kodama'});
    for (final list in seen.skip(before)) {
      expect(list, isNotEmpty,
          reason:
              'an empty list would take the running card away and make it again');
    }
  });
}
