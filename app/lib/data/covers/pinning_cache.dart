import 'dart:async';
import 'dart:convert';
import 'dart:io' as io;

import 'package:file/file.dart' hide FileSystem;
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';

import '../../core/logger.dart';

/// Where the files of a cache live, given by the caller: the cache manager's own file system always uses the temporary directory, which Android
/// clears with "Clear cache" and may clear on its own, and the pictures of downloaded songs must outlive both (P1-10).
class DirectoryFileSystem implements FileSystem {
  DirectoryFileSystem(this._where);

  final Future<io.Directory> Function() _where;
  Future<Directory>? _directory;

  Future<Directory> _open() async {
    final place = await _where();
    final directory = const LocalFileSystem().directory(place.path);
    await directory.create(recursive: true);
    return directory;
  }

  @override
  Future<File> createFile(String name) async {
    final directory = await (_directory ??= _open());
    if (!directory.existsSync()) {
      await directory.create(recursive: true);
    }
    return directory.childFile(name);
  }
}

/// Remembers WHICH pictures are pinned (the cache manager cannot list its keys), across runs.
abstract interface class PinRegistry {
  Future<Set<String>> load();
  Future<void> save(Set<String> keys);
}

/// A [PinRegistry] kept in one small JSON file next to the pinned pictures.
class FilePinRegistry implements PinRegistry {
  FilePinRegistry(this._file);

  final Future<io.File> Function() _file;

  @override
  Future<Set<String>> load() async {
    try {
      final file = await _file();
      if (!file.existsSync()) return <String>{};
      final decoded = jsonDecode(await file.readAsString());
      return {
        if (decoded is List)
          for (final key in decoded)
            if (key is String) key,
      };
    } on Object catch (error) {
      Log.debug('covers', 'the list of pinned pictures was not read: $error');
      return <String>{};
    }
  }

  @override
  Future<void> save(Set<String> keys) async {
    final file = await _file();
    await file.parent.create(recursive: true);
    await file.writeAsString(jsonEncode(keys.toList()..sort()));
  }
}

/// The cover cache with a second, PINNED store (P1-10, owner 13 Nov 2026: "when a playlist, or even one song of an artist, is downloaded I want
/// ALL album covers and artist pictures downloaded too, each once"). The normal store is a cache: it is least-recently-used (browsing a big
/// library can push a downloaded song's cover out) and it lives where Android may clear it. A pinned picture is a copy in a directory the system
/// does not clear, with no eviction, kept for exactly as long as a downloaded song needs it ([retainOnly]).
///
/// Everything that reads a picture through this manager (`CachedNetworkImage`, the other-size lookup) finds a pinned one first, so no widget
/// changes. Pins are keyed by the picture's own key (server, cover id or artist id, size), NEVER by song id: when two songs are merged into one
/// (N-11) nothing here has to move.
class PinningCacheManager extends CacheManager {
  PinningCacheManager(
    super.config, {
    required CacheManager pinned,
    required PinRegistry registry,
  })  : _pinned = pinned,
        _registry = registry;

  final CacheManager _pinned;
  final PinRegistry _registry;
  Set<String>? _keys;

  @override
  Future<FileInfo?> getFileFromCache(String key,
      {bool ignoreMemCache = false}) async {
    final pinned =
        await _pinned.getFileFromCache(key, ignoreMemCache: ignoreMemCache);
    if (pinned != null) return pinned;
    return super.getFileFromCache(key, ignoreMemCache: ignoreMemCache);
  }

  Future<Set<String>> _load() async => _keys ??= await _registry.load();

  /// The keys that are pinned.
  Future<Set<String>> pinnedKeys() async => {...await _load()};

  /// Whether the picture under [key] is pinned.
  Future<bool> isPinned(String key) async => (await _load()).contains(key);

  /// Pins the picture under [key], copying it from the normal cache. `false` when it is not there to copy (fetch it first); `true` when it is
  /// pinned, now or already.
  Future<bool> pin(String key) async {
    final keys = await _load();
    if (keys.contains(key) && await _pinned.getFileFromCache(key) != null) {
      return true;
    }
    final cached = await super.getFileFromCache(key);
    if (cached == null) return false;
    await _pinned.putFile(
      cached.originalUrl,
      await cached.file.readAsBytes(),
      key: key,
      maxAge: const Duration(days: 3650),
      fileExtension: 'jpg',
    );
    keys.add(key);
    await _registry.save(keys);
    return true;
  }

  /// Releases the pin on [key] (the normal cache may still hold the picture).
  Future<void> unpin(String key) async {
    final keys = await _load();
    await _pinned.removeFile(key);
    if (keys.remove(key)) await _registry.save(keys);
  }

  /// Unpins every pinned picture that is not in [wanted]: the song that needed it is no longer downloaded.
  Future<int> retainOnly(Set<String> wanted) async {
    var released = 0;
    for (final key in [...await _load()]) {
      if (wanted.contains(key)) continue;
      await unpin(key);
      released++;
    }
    return released;
  }
}
