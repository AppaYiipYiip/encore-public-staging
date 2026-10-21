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
