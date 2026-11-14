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

/// Remembers WHICH pictures are pinned and for which servers (the cache manager cannot list its keys), across runs. A picture is wanted by the
/// downloaded songs of one or more servers (the app has several profiles): it is released only when no server wants it.
abstract interface class PinRegistry {
  Future<Map<String, Set<int>>> load();
  Future<void> save(Map<String, Set<int>> owners);
}

/// A [PinRegistry] kept in one small JSON file next to the pinned pictures.
class FilePinRegistry implements PinRegistry {
  FilePinRegistry(this._file);

  final Future<io.File> Function() _file;

  @override
  Future<Map<String, Set<int>>> load() async {
    try {
      final file = await _file();
      if (!file.existsSync()) return <String, Set<int>>{};
      final decoded = jsonDecode(await file.readAsString());
      return {
        if (decoded is Map)
          for (final entry in decoded.entries)
            if (entry.key is String && entry.value is List)
              entry.key as String: {
                for (final owner in entry.value as List)
                  if (owner is int) owner,
              },
      };
    } on Object catch (error) {
      Log.debug('covers', 'the list of pinned pictures was not read: $error');
      return <String, Set<int>>{};
    }
  }

  @override
  Future<void> save(Map<String, Set<int>> owners) async {
    final file = await _file();
    await file.parent.create(recursive: true);
    await file.writeAsString(jsonEncode({
      for (final key in owners.keys.toList()..sort())
        key: owners[key]!.toList()..sort(),
    }));
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
  Map<String, Set<int>>? _owners;

  /// The pinned store is an extra: a damaged index file or a store that cannot be opened must never make a picture unreadable, so a failed
  /// look there is logged and the normal cache answers.
  @override
  Future<FileInfo?> getFileFromCache(String key,
      {bool ignoreMemCache = false}) async {
    try {
      final pinned =
          await _pinned.getFileFromCache(key, ignoreMemCache: ignoreMemCache);
      if (pinned != null) return pinned;
    } on Object catch (error) {
      Log.debug('covers', 'the pinned store could not be read: $error');
    }
    return super.getFileFromCache(key, ignoreMemCache: ignoreMemCache);
  }

  Future<Map<String, Set<int>>> _load() async =>
      _owners ??= await _registry.load();

  /// The keys that are pinned (for any server).
  Future<Set<String>> pinnedKeys() async => {...(await _load()).keys};

  /// Whether the picture under [key] is pinned.
  Future<bool> isPinned(String key) async => (await _load()).containsKey(key);

  /// Pins the picture under [key] for the server [owner], copying it from the normal cache. `false` when it is not there to copy (fetch it
  /// first); `true` when it is pinned, now or already.
  Future<bool> pin(String key, {int owner = 0}) async {
    final owners = await _load();
    final known = owners[key];
    if (known != null && await _pinned.getFileFromCache(key) != null) {
      if (known.add(owner)) await _registry.save(owners);
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
    (owners[key] ??= <int>{}).add(owner);
    await _registry.save(owners);
    return true;
  }

  /// Releases the pin of [owner] on [key]; the picture is deleted when no server wants it any more (the normal cache may still hold it).
  Future<void> unpin(String key, {int owner = 0}) async {
    final owners = await _load();
    final known = owners[key];
    if (known == null) return;
    known.remove(owner);
    if (known.isEmpty) {
      owners.remove(key);
      await _pinned.removeFile(key);
    }
    await _registry.save(owners);
  }

  /// Releases the pins of [owner] on every picture that is not in [wanted] (its downloaded songs no longer need it). Another server's pins are
  /// never touched: the app runs one server at a time and each run only knows its own downloads.
  Future<int> retainOnly(Set<String> wanted, {int owner = 0}) async {
    var released = 0;
    for (final entry in [...(await _load()).entries]) {
      if (wanted.contains(entry.key) || !entry.value.contains(owner)) continue;
      await unpin(entry.key, owner: owner);
      released++;
    }
    return released;
  }

  /// Everything, pinned pictures too (signing out: the pictures of an account must not stay on the phone). [emptyCache] empties only the normal
  /// store, which is what Android's "Clear cache" does to it.
  Future<void> clearEverything() async {
    await emptyCache();
    try {
      await _pinned.emptyCache();
    } on Object catch (error) {
      Log.debug('covers', 'the pinned store was not emptied: $error');
    }
    _owners = <String, Set<int>>{};
    await _registry.save(_owners!);
  }
}
