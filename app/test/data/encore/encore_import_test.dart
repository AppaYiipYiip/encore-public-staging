import 'package:dio/dio.dart';
import 'package:drift/native.dart';
import 'package:encore/core/client_id.dart';
import 'package:encore/core/clock.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/data/encore/encore_api.dart';
import 'package:encore/data/encore/encore_models.dart';
import 'package:encore/data/encore/encore_sync.dart';
import 'package:encore/data/fetch/import_models.dart';
import 'package:encore/features/import/encore_import_screen.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../support/fake_encore_server.dart';

void main() {
  late AppDatabase db;
  late FakeEncoreServer server;
  late EncoreApi api;
  late EncoreSync sync;
  late int serverId;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    serverId = await db.into(db.servers).insert(ServersCompanion.insert(
          name: 'Test',
          username: 'tester',
          endpointsJson: '[]',
          createdAtMs: 0,
        ));
    server = FakeEncoreServer();
    api = EncoreApi(
      dio: Dio()..httpClientAdapter = server.adapter,
      baseUrl: () => Uri.parse('http://home.test:4540'),
      auth: () => {'u': 'tester', 't': 'tok', 's': 'salt'},
    );
    sync = EncoreSync(
      db: db,
      api: api,
      serverId: serverId,
      ownerName: 'tester',
      clock: FakeClock(DateTime.utc(2026, 10, 22, 12)),
    );
  });

  tearDown(() => db.close());

  test(
      'a pasted link makes the playlist at once, and one pull puts it, its picture and every song on the phone',
      () async {
    const picture = 'https://i.ytimg.com/vi/abc/hqdefault.jpg';
    server.linkPicture = picture;

    final made = (await api.createImport(
            id: newClientId('im'),
            url: 'https://music.youtube.com/playlist?list=PL1'))
        .getOrThrow();
    await sync.pull();

    expect(made.import.total, 3);
    expect(made.import.isRunning, isTrue);
    final playlist = await (db.select(db.playlists)
          ..where((p) => p.id.equals(made.playlistId!)))
        .getSingle();
    expect(playlist.coverArt, picture,
        reason: 'the picture is there from the first second');
    final entries = await (db.select(db.playlistEntries)
          ..where((e) => e.playlistId.equals(made.playlistId!)))
        .get();
    expect(entries, hasLength(3));
    expect(playlist.songCount, 3);
  });

  test('the same import asked twice is one import and one playlist', () async {
    final id = newClientId('im');

    final first =
        (await api.createImport(id: id, url: 'https://x/y')).getOrThrow();
    final again =
        (await api.createImport(id: id, url: 'https://x/y')).getOrThrow();

    expect(again.playlistId, first.playlistId);
    expect(server.playlists, hasLength(1));
  });

  test('a list from a file is described to the server, and a liked list likes',
      () async {
    final liked = (await api.createImport(
            id: newClientId('im'),
            name: 'Liked from Spotify',
            source: 'file',
            songs: [
              describeImported(const ImportedTrack(
                  title: 'Nude', artist: 'Radiohead', durationSec: 255)),
            ],
            liked: true))
        .getOrThrow();
    await sync.pull();

    expect(liked.playlistId, isNull);
    expect(server.playlists, isEmpty);
    final likedTracks = await (db.select(db.tracks)
          ..where((t) => t.starredAtMs.isNotNull()))
        .get();
    expect(likedTracks.map((t) => t.title), ['Nude']);
  });

  test('the imports are listed with the counts of the server', () async {
    await api.createImport(id: newClientId('im'), url: 'https://x/y');

    final list = (await api.imports()).getOrThrow();

    expect(list.single.name, 'Imported playlist');
    expect(importSummary(list.single), 'Finding songs: 0 of 3');
  });

  test('what an import says in words, running or done', () {
    const running = EncoreImport(
        id: 'im_1',
        name: 'Road trip',
        source: 'youtube',
        state: 'running',
        total: 10,
        matched: 4,
        unmatched: 1,
        pending: 5,
        kept: 2);
    const done = EncoreImport(
        id: 'im_1',
        name: 'Road trip',
        source: 'youtube',
        state: 'done',
        total: 10,
        matched: 9,
        unmatched: 1,
        pending: 0,
        kept: 7);

    expect(importSummary(running), 'Finding songs: 5 of 10, 1 not found');
    expect(
        importSummary(done), '10 songs, 7 saved on your server, 1 not found');

    // A list longer than the server reads is cut: the person is told (the owner's playlist had 2,500 songs and showed 2000 with nothing said).
    const cut = EncoreImport(
        id: 'im_2',
        name: 'Long',
        source: 'youtube',
        state: 'done',
        total: 2000,
        matched: 2000,
        unmatched: 0,
        pending: 0,
        kept: 5,
        truncated: true);
    expect(importSummary(cut),
        '2000 songs, 5 saved on your server. The list is longer: only these 2000 songs were read.');
  });
}
