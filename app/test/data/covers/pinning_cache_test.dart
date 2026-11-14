import 'dart:io';
import 'dart:typed_data';

import 'package:encore/data/covers/pinning_cache.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_test/flutter_test.dart';

/// P1-10 (owner, 13 Nov 2026): the pictures of a downloaded song are kept with it, once each, and offline nothing is a letter. The cover
/// cache is least-recently-used and lives where Android may clear it; a PINNED picture is a copy that neither of those can take.
class _MemoryRegistry implements PinRegistry {
  Set<String> saved = {};
  int loads = 0;

  @override
  Future<Set<String>> load() async {
    loads++;
    return {...saved};
  }

  @override
  Future<void> save(Set<String> keys) async => saved = {...keys};
}

void main() {
  late Directory root;
  late _MemoryRegistry registry;

  PinningCacheManager make() {
    final normal = Directory('${root.path}/normal');
    final pinned = Directory('${root.path}/pinned');
    return PinningCacheManager(
      Config(
        'normal',
        repo: JsonCacheInfoRepository(path: '${root.path}/normal.json'),
        fileSystem: DirectoryFileSystem(() async => normal),
      ),
      pinned: CacheManager(
        Config(
          'pinned',
          stalePeriod: const Duration(days: 3650),
          maxNrOfCacheObjects: 100000,
          repo: JsonCacheInfoRepository(path: '${root.path}/pinned.json'),
          fileSystem: DirectoryFileSystem(() async => pinned),
        ),
      ),
      registry: registry,
    );
  }

  Uint8List bytes(int seed) => Uint8List.fromList([seed, seed + 1, seed + 2]);

  Future<List<int>?> read(PinningCacheManager cache, String key) async {
    final info = await cache.getFileFromCache(key);
    return info == null ? null : await info.file.readAsBytes();
  }

  setUp(() async {
    root = await Directory.systemTemp.createTemp('pinning_cache_test');
    registry = _MemoryRegistry();
  });

  tearDown(() async {
    try {
      if (root.existsSync()) await root.delete(recursive: true);
    } on FileSystemException {
      // Windows keeps a cache file open a moment longer: the system cleans the temporary directory.
    }
  });

  test('a pinned picture is still there after the normal cache was cleared',
      () async {
    final cache = make();
    await cache.putFile('https://srv/cover/a', bytes(1), key: 'c:1:a:256');
    expect(await cache.pin('c:1:a:256'), isTrue);

    await cache.emptyCache(); // what "Clear cache" does to the normal store

    expect(await read(cache, 'c:1:a:256'), bytes(1));
  });

  test(
      'a picture that was not pinned is gone after the normal cache was cleared (the control)',
      () async {
    final cache = make();
    await cache.putFile('https://srv/cover/a', bytes(1), key: 'c:1:a:256');
    await cache.putFile('https://srv/cover/b', bytes(2), key: 'c:1:b:256');
    await cache.pin('c:1:a:256');

    await cache.emptyCache();

    expect(await read(cache, 'c:1:b:256'), isNull);
    expect(await read(cache, 'c:1:a:256'), isNotNull);
  });

  test(
      'a picture is pinned once: pinning it again copies nothing and keeps the registry as it is',
      () async {
    final cache = make();
    await cache.putFile('https://srv/cover/a', bytes(1), key: 'k');

    expect(await cache.pin('k'), isTrue);
    expect(await cache.pin('k'), isTrue);

    expect(registry.saved, {'k'});
    expect(await cache.pinnedKeys(), {'k'});
  });

  test(
      'a picture that is not in the cache cannot be pinned, and nothing is registered',
      () async {
    final cache = make();

    expect(await cache.pin('missing'), isFalse);

    expect(registry.saved, isEmpty);
    expect(await cache.isPinned('missing'), isFalse);
  });

  test('releasing a pin lets the picture go with the next clear', () async {
    final cache = make();
    await cache.putFile('https://srv/cover/a', bytes(1), key: 'k');
    await cache.pin('k');

    await cache.unpin('k');
    await cache.emptyCache();

    expect(await read(cache, 'k'), isNull);
    expect(registry.saved, isEmpty);
  });

  test('retainOnly releases what no downloaded song needs and keeps the rest',
      () async {
    final cache = make();
    for (final key in ['a', 'b', 'c']) {
      await cache.putFile('https://srv/$key', bytes(key.codeUnitAt(0)),
          key: key);
      await cache.pin(key);
    }

    final released = await cache.retainOnly({'a', 'c'});
    await cache.emptyCache();

    expect(released, 1);
    expect(await read(cache, 'a'), isNotNull);
    expect(await read(cache, 'b'), isNull);
    expect(await read(cache, 'c'), isNotNull);
    expect(registry.saved, {'a', 'c'});
  });

  test('what is pinned is remembered by a new manager (a new run of the app)',
      () async {
    final first = make();
    await first.putFile('https://srv/cover/a', bytes(1), key: 'k');
    await first.pin('k');

    final second = make();

    expect(await second.pinnedKeys(), {'k'});
    expect(await read(second, 'k'), bytes(1));
  });

  test('the registry is read once per run, not once per question', () async {
    final cache = make();
    await cache.isPinned('a');
    await cache.isPinned('b');
    await cache.pinnedKeys();

    expect(registry.loads, 1);
  });

  test('the file registry survives a restart and ignores a damaged file',
      () async {
    final file = File('${root.path}/pins.json');
    final registry = FilePinRegistry(() async => file);

    expect(await registry.load(), isEmpty, reason: 'no file yet');
    await registry.save({'b', 'a'});
    expect(await FilePinRegistry(() async => file).load(), {'a', 'b'});

    await file.writeAsString('{not json');
    expect(await registry.load(), isEmpty);
  });
}
