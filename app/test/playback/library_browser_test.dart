import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:encore/data/db/app_database.dart';
import 'package:encore/playback/library_browser.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/test_app.dart';

void main() {
  late AppDatabase db;
  late DbLibraryBrowser browser;

  setUp(() async {
    db = AppDatabase(NativeDatabase.memory());
    final serverId = await Seed.library(db);
    browser = DbLibraryBrowser(db: db, serverId: serverId, pageSize: 3);
  });

  tearDown(() => db.close());

  test('the root offers the six top-level shelves', () async {
    final nodes = await browser.children(BrowseIds.root);
    expect(nodes.map((n) => n.id), [
      BrowseIds.recent,
      BrowseIds.playlists,
      BrowseIds.albums,
      BrowseIds.artists,
      BrowseIds.liked,
      BrowseIds.downloads,
    ]);
    expect(nodes.every((n) => n.browsable && !n.playable), isTrue);
  });

  test('playlists are browsable and capped to the page size', () async {
    final nodes = await browser.children(BrowseIds.playlists);
    expect(nodes.length, 3, reason: 'pageSize = 3 of 4 playlists');
    expect(nodes.first.id, startsWith('playlist:'));
    expect(nodes.every((n) => n.browsable), isTrue);
  });

  test('an album lists its tracks as playable items of that album', () async {
    final nodes = await browser.children(BrowseIds.album('al3'));
    expect(nodes.length, 3);
    expect(nodes.first.playable, isTrue);
    expect(nodes.first.id, 'track:al3-t1@album:al3');
  });

  test('an artist lists albums, not songs', () async {
    final nodes = await browser.children(BrowseIds.artist('ar1'));
    expect(nodes.map((n) => n.id), everyElement(startsWith('album:')));
  });

  test('the music server\'s catch-all album is named in plain words', () async {
    final serverId =
        await (db.select(db.servers)).getSingle().then((s) => s.id);
    await db.into(db.albums).insert(AlbumsCompanion.insert(
          serverId: serverId,
          id: 'al-bucket',
          name: '[Unknown Album]',
          artistId: const Value('ar1'),
          artist: const Value('Alcest'),
        ));
    await db.into(db.tracks).insert(TracksCompanion.insert(
          serverId: serverId,
          id: 'al-bucket-t1',
          title: 'Loose song',
          albumId: const Value('al-bucket'),
          album: const Value('[Unknown Album]'),
          artist: const Value('Alcest'),
        ));
    final nodes = await browser.children(BrowseIds.artist('ar1'));
    final bucket = nodes.firstWhere((n) => n.id == 'album:al-bucket');
    expect(bucket.title, 'Songs without an album');
    expect(nodes.where((n) => n.title == '[Unknown Album]'), isEmpty);
    // The car and the lock screen say "playing from" this name too.
    final request = await browser.resolvePlay('album:al-bucket');
    expect(request!.sourceName, 'Songs without an album');
  });

  test('liked songs list the starred tracks', () async {
    final nodes = await browser.children(BrowseIds.liked);
    expect(nodes.single.id, 'track:al3-t1@liked');
  });

  test('playing a track queues its whole album from that track', () async {
    final request = await browser.resolvePlay('track:al3-t3@album:al3');
    expect(request, isNotNull);
    expect(request!.tracks.length, 5);
    expect(request.startIndex, 2);
    expect(request.sourceName, 'The Walk');
    expect(request.sourceId, 'album:al3');
  });

  test('playing a browsable node starts it from the top', () async {
    final request = await browser.resolvePlay('playlist:pl1');
    expect(request!.startIndex, 0);
    expect(request.tracks.length, 6);
    expect(request.sourceName, 'Prog Snob');
  });

  test('an unknown id resolves to nothing', () async {
    expect(await browser.resolvePlay('album:nope'), isNull);
    expect(await browser.children('mystery'), isEmpty);
  });

  test('voice search: an exact artist plays all their songs', () async {
    final request = await browser.search('Periphery');
    expect(request, isNotNull);
    expect(request!.sourceId, 'artist:ar2');
    expect(request.tracks, isNotEmpty);
  });

  test('voice search: a song title plays the matches', () async {
    final request = await browser.search('Echoes');
    expect(request!.tracks.first.title, startsWith('Echoes'));
  });

  test('voice search with nothing found returns null', () async {
    expect(await browser.search('zzzzqqq'), isNull);
    expect(await browser.search('   '), isNull);
  });
}
