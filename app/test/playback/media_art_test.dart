import 'dart:async';
import 'dart:io';

import 'package:encore/playback/media_art.dart';
import 'package:flutter_test/flutter_test.dart';

/// Artwork handed to the media session is readable by every app that can see
/// media controls (notification listeners, Bluetooth, the car). A server cover
/// URL carries the Subsonic username, token and salt, which can be replayed, so
/// only a local file may ever be published (docs/23, B24; ADR-017).
/// A file name like the cache manager's: no characters a path cannot hold.
String _name(String key) => key.replaceAll(':', '_');

void main() {
  const credentialed =
      'http://home:4533/rest/getCoverArt?id=al1&size=768&u=marwa&t=abc123&s=salt';

  late Map<String, File> cache;
  late List<String> downloads;
  late Future<File?> Function(String url, String key) download;

  MediaArtResolver resolver(
      {Duration wait = const Duration(milliseconds: 80)}) {
    return MediaArtResolver(
      serverId: 1,
      cachedFile: (key) async => cache[key],
      download: (url, key) => download(url, key),
      urlFor: (id, size) => credentialed.replaceFirst('al1', id),
      wait: wait,
    );
  }

  setUp(() {
    cache = {};
    downloads = [];
    download = (url, key) async {
      downloads.add(url);
      final file = File('/cache/${_name(key)}.jpg');
      cache[key] = file;
      return file;
    };
  });

  test('a cached cover is a local file and nothing is downloaded', () async {
    cache['cover:1:al1:768'] = File('/cache/al1.jpg');

    final uri = await resolver().resolve('al1');

    expect(uri, Uri.file('/cache/al1.jpg'));
    expect(downloads, isEmpty);
  });

  test('the other size of the cover stands in and nothing is downloaded',
      () async {
    // Seen in a row (the small size) but never in the player: good enough for the lock screen, and it works offline.
    cache['cover:1:al1:256'] = File('/cache/al1-small.jpg');

    final uri = await resolver().resolve('al1');

    expect(uri, Uri.file('/cache/al1-small.jpg'));
    expect(downloads, isEmpty);
  });

  test('a cover that is not cached is fetched, then published as a local file',
      () async {
    final uri = await resolver().resolve('al1');

    expect(uri!.scheme, 'file');
    expect(downloads, hasLength(1),
        reason: 'the credentialed URL is used to fetch and nowhere else');
  });

  test('a slow download publishes nothing now, and still fills the cache',
      () async {
    final gate = Completer<void>();
    download = (url, key) async {
      await gate.future;
      return cache[key] = File('/cache/${_name(key)}.jpg');
    };

    final uri = await resolver().resolve('al1');

    expect(uri, isNull, reason: 'never the network URL instead');
    gate.complete();
    await pumpEventQueue();
    expect(cache, contains('cover:1:al1:768'),
        reason: 'the next request finds it');
  });

  test('a failing download publishes nothing and does not throw', () async {
    download = (url, key) async => throw const SocketException('offline');

    expect(await resolver().resolve('al1'), isNull);
  });

  test('a download that finds no file publishes nothing', () async {
    download = (url, key) async => null;

    expect(await resolver().resolve('al1'), isNull);
  });

  test('without a session there is no art, and no request', () async {
    final noSession = MediaArtResolver(
      serverId: 1,
      cachedFile: (key) async => null,
      download: (url, key) => download(url, key),
      urlFor: (id, size) => null,
    );

    expect(await noSession.resolve('al1'), isNull);
    expect(downloads, isEmpty);
  });

  test('whatever happens, the result never carries credentials', () async {
    final outcomes = <Uri?>[];
    // cache hit, miss + fetched, slow, failing, empty
    cache['cover:1:hit:768'] = File('/cache/hit.jpg');
    outcomes.add(await resolver().resolve('hit'));
    outcomes.add(await resolver().resolve('miss'));
    download = (url, key) => Completer<File?>().future; // never completes
    outcomes.add(await resolver().resolve('slow'));
    download = (url, key) async => throw const SocketException('x');
    outcomes.add(await resolver().resolve('bad'));
    download = (url, key) async => null;
    outcomes.add(await resolver().resolve('none'));

    for (final uri in outcomes.whereType<Uri>()) {
      expect(uri.scheme, 'file');
      expect(uri.toString(), isNot(contains('t=')));
      expect(uri.toString(), isNot(contains('u=')));
      expect(uri.toString(), isNot(contains('salt')));
    }
  });

  group('P4-24: Data saver in force asks for the small picture only', () {
    test(
        'a cover that is not cached is fetched at the small size, not the large',
        () async {
      final sizesAsked = <int>[];
      final small = MediaArtResolver(
        serverId: 1,
        cachedFile: (key) async => cache[key],
        download: (url, key) => download(url, key),
        urlFor: (id, size) {
          sizesAsked.add(size);
          return credentialed.replaceFirst('al1', id);
        },
        smallOnly: () => true,
      );

      final uri = await small.resolve('al1');

      expect(uri!.scheme, 'file');
      expect(sizesAsked, [256]);
      expect(cache, contains('cover:1:al1:256'));
      expect(cache, isNot(contains('cover:1:al1:768')));
    });

    test('a large cover that is already on the phone still stands in: no bytes',
        () async {
      cache['cover:1:al1:768'] = File('/cache/al1-large.jpg');
      final small = MediaArtResolver(
        serverId: 1,
        cachedFile: (key) async => cache[key],
        download: (url, key) => download(url, key),
        urlFor: (id, size) => credentialed,
        smallOnly: () => true,
      );

      expect(await small.resolve('al1'), Uri.file('/cache/al1-large.jpg'));
      expect(downloads, isEmpty);
    });

    test('not in force (the default): the large size, as before', () async {
      final sizesAsked = <int>[];
      final normal = MediaArtResolver(
        serverId: 1,
        cachedFile: (key) async => cache[key],
        download: (url, key) => download(url, key),
        urlFor: (id, size) {
          sizesAsked.add(size);
          return credentialed;
        },
        smallOnly: () => false,
      );

      await normal.resolve('al1');
      expect(sizesAsked, [768]);
    });
  });
}
