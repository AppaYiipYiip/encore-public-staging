import 'dart:math';

import 'package:flutter/foundation.dart';

import '../data/db/app_database.dart';

/// One entry of the play queue. [uid] distinguishes two occurrences of the
/// same track (a queue may contain a song twice).
@immutable
class QueueItem {
  const QueueItem({
    required this.uid,
    required this.id,
    required this.title,
    this.artist,
    this.album,
    this.albumId,
    this.artistId,
    this.catalogueArtistId,
    this.coverArt,
    this.durationSec,
    this.suffix,
    this.bitRate,
    this.size,
    this.rgTrackGain,
    this.rgAlbumGain,
    this.rgTrackPeak,
    this.rgAlbumPeak,
    this.starred = false,
    this.directUri,
    this.imageUrl,
    this.fullSong = false,
  });

  /// A catalogue sample that is not in the library (30 s preview).
  factory QueueItem.preview({
    required int uid,
    required String id,
    required String title,
    required Uri uri,
    String? artist,
    String? catalogueArtistId,
    String? album,
    String? imageUrl,
    int? durationSec,
    bool fullSong = false,
  }) =>
      QueueItem(
        uid: uid,
        id: id,
        title: title,
        artist: artist,
        fullSong: fullSong,
        catalogueArtistId: catalogueArtistId,
        album: album,
        durationSec: durationSec,
        directUri: uri,
        imageUrl: imageUrl,
      );

  factory QueueItem.fromTrack(TrackRow t, {required int uid}) => QueueItem(
        uid: uid,
        id: t.id,
        title: t.title,
        artist: t.artist,
        album: t.album,
        albumId: t.albumId,
        artistId: t.artistId,
        coverArt: t.coverArt,
        durationSec: t.durationSec,
        suffix: t.suffix,
        bitRate: t.bitRate,
        size: t.size,
        rgTrackGain: t.rgTrackGain,
        rgAlbumGain: t.rgAlbumGain,
        rgTrackPeak: t.rgTrackPeak,
        rgAlbumPeak: t.rgAlbumPeak,
        starred: t.starredAtMs != null,
      );

  final int uid;
  final String id;
  final String title;
  final String? artist;
  final String? album;
  final String? albumId;
  final String? artistId;

  /// The catalogue's id of [artist] (a sample or a stream-only song).
  final String? catalogueArtistId;
  final String? coverArt;
  final int? durationSec;
  final String? suffix;
  final int? bitRate;
  final int? size;
  final double? rgTrackGain;
  final double? rgAlbumGain;
  final double? rgTrackPeak;
  final double? rgAlbumPeak;
  final bool starred;

  /// Play exactly this URL (catalogue previews); library tracks leave it null
  /// and are resolved through the server / downloads.
  final Uri? directUri;

  /// Artwork URL for items that have no server cover id.
  final String? imageUrl;

  /// The whole song from the instant-play service, not a sample (it has no
  /// library id yet, but it is listening that counts).
  final bool fullSong;

  bool get isLibraryTrack => directUri == null;

  Duration? get duration =>
      durationSec == null ? null : Duration(seconds: durationSec!);

  @override
  bool operator ==(Object other) => other is QueueItem && other.uid == uid;

  @override
  int get hashCode => uid.hashCode;

  @override
  String toString() => 'QueueItem($uid, $id, $title)';
}

enum QueueRepeat { off, all, one }

/// The play queue: what is in it, in which order, and where we are.
///
/// Pure data structure (no I/O, no timers) so every rule is unit-tested:
///
/// * [items] keeps the order the user built; [_order] is the play order.
///   With shuffle off the two are the same; with shuffle on, [_order] is a
///   permutation that starts at the current item.
/// * Skipping by hand and finishing a track differ for repeat-one: finishing
///   repeats the track, pressing "next" moves on.
class QueueModel {
  QueueModel({Random? random}) : _random = random ?? Random();

  final Random _random;
  final List<QueueItem> _items = [];
  final List<int> _order = [];
  int _cursor = -1;
  int _nextUid = 1;

  bool _shuffle = false;
  QueueRepeat _repeat = QueueRepeat.off;

  // -------------------------------------------------------------------- read

  bool get isEmpty => _items.isEmpty;
  int get length => _items.length;
  bool get shuffle => _shuffle;
  QueueRepeat get repeat => _repeat;

  /// Position in play order (`-1` when the queue is empty).
  int get cursor => _cursor;

  QueueItem? get current =>
      _cursor < 0 || _cursor >= _order.length ? null : _items[_order[_cursor]];

  /// Items in the order they will be played.
  List<QueueItem> get ordered => [for (final i in _order) _items[i]];

  /// Items as the user arranged them (shuffle ignored).
  List<QueueItem> get items => List.unmodifiable(_items);

  /// What plays after [current] (without wrapping).
  List<QueueItem> get upNext => [
        for (var i = _cursor + 1; i < _order.length; i++) _items[_order[i]],
      ];

  QueueItem? get peekNext {
    if (_order.isEmpty) return null;
    if (_cursor + 1 < _order.length) return _items[_order[_cursor + 1]];
    if (_repeat == QueueRepeat.all) return _items[_order.first];
    return null;
  }

  bool get hasNext => peekNext != null;

  bool get hasPrevious =>
      _cursor > 0 || (_repeat == QueueRepeat.all && _order.length > 1);

  /// A fresh unique id for a new entry.
  int newUid() => _nextUid++;

  QueueItem itemFor(TrackRow track) =>
      QueueItem.fromTrack(track, uid: newUid());

  // ------------------------------------------------------------------ change

  /// Replaces the whole queue and positions it on [startIndex] (index into
  /// [items], i.e. the order the caller passed).
  void replace(
    List<QueueItem> items, {
    int startIndex = 0,
    bool? shuffle,
  }) {
    _items
      ..clear()
      ..addAll(items);
    if (shuffle != null) _shuffle = shuffle;
    if (_items.isEmpty) {
      _order.clear();
      _cursor = -1;
      return;
    }
    final start = startIndex.clamp(0, _items.length - 1);
    if (_shuffle) {
      _order
        ..clear()
        ..add(start)
        ..addAll(_shuffled([
          for (var i = 0; i < _items.length; i++)
            if (i != start) i,
        ]));
      _cursor = 0;
    } else {
      _order
        ..clear()
        ..addAll(List.generate(_items.length, (i) => i));
      _cursor = start;
    }
  }

  /// Finished current track: returns `true` when there is something to play
  /// (possibly the same track again).
  bool advanceAuto() {
    if (_order.isEmpty) return false;
    if (_repeat == QueueRepeat.one) return true;
    return _step();
  }

  /// The user pressed "next".
  bool skipNext() => _order.isEmpty ? false : _step();

  bool _step() {
    if (_cursor + 1 < _order.length) {
      _cursor++;
      return true;
    }
    if (_repeat == QueueRepeat.all) {
      _cursor = 0;
      return true;
    }
    return false;
  }

  /// The user pressed "previous" (callers restart the track instead when it
  /// has been playing for a few seconds).
  bool skipPrevious() {
    if (_order.isEmpty) return false;
    if (_cursor > 0) {
      _cursor--;
      return true;
    }
    if (_repeat == QueueRepeat.all && _order.length > 1) {
      _cursor = _order.length - 1;
      return true;
    }
    return false;
  }

  /// Jumps to position [orderIndex] in play order.
  bool jumpTo(int orderIndex) {
    if (orderIndex < 0 || orderIndex >= _order.length) return false;
    _cursor = orderIndex;
    return true;
  }

  /// Appends to the end of the queue.
  void addToEnd(QueueItem item) {
    if (_items.isEmpty) {
      replace([item], shuffle: _shuffle);
      return;
    }
    _items.add(item);
    _order.add(_items.length - 1);
  }

  /// Inserts right after the current item.
  void playNext(QueueItem item) {
    if (_items.isEmpty) {
      replace([item], shuffle: _shuffle);
      return;
    }
    final currentIndex = _order[_cursor];
    // Keep the user-visible order sensible when shuffle is off: the new item
    // sits right after the current one in [items] too.
    final at = _shuffle ? _items.length : currentIndex + 1;
    for (var i = 0; i < _order.length; i++) {
      if (_order[i] >= at) _order[i]++;
    }
    _items.insert(at, item);
    _order.insert(_cursor + 1, at);
  }

  /// Removes the entry at play-order position [orderIndex]. Returns `true`
  /// when it was the current one (the caller must start the next entry).
  bool removeAt(int orderIndex) {
    if (orderIndex < 0 || orderIndex >= _order.length) return false;
    final itemIndex = _order.removeAt(orderIndex);
    _items.removeAt(itemIndex);
    for (var i = 0; i < _order.length; i++) {
      if (_order[i] > itemIndex) _order[i]--;
    }
    if (_items.isEmpty) {
      _cursor = -1;
      return true;
    }
    if (orderIndex < _cursor) {
      _cursor--;
      return false;
    }
    if (orderIndex == _cursor) {
      // The entry that followed slid into this slot.
      if (_cursor >= _order.length) _cursor = _order.length - 1;
      return true;
    }
    return false;
  }

  /// Moves an entry in play order (drag & drop in the queue sheet).
  void move(int from, int to) {
    if (from == to ||
        from < 0 ||
        to < 0 ||
        from >= _order.length ||
        to >= _order.length) {
      return;
    }
    final currentItem = _order[_cursor];
    final moved = _order.removeAt(from);
    _order.insert(to, moved);
    _cursor = _order.indexOf(currentItem);
    if (!_shuffle) _normaliseToIdentity(currentItem);
  }

  /// With shuffle off, [items] must equal play order (so un-shuffling later
  /// keeps the arrangement the user made).
  void _normaliseToIdentity(int currentItem) {
    final arranged = [for (final i in _order) _items[i]];
    final current = _items[currentItem];
    _items
      ..clear()
      ..addAll(arranged);
    _order
      ..clear()
      ..addAll(List.generate(_items.length, (i) => i));
    _cursor = _items.indexOf(current);
  }

  /// Drops everything after the current entry.
  void clearUpNext() {
    if (_order.isEmpty) return;
    final keep = _cursor + 1;
    final removed = _order.sublist(keep)..sort((a, b) => b.compareTo(a));
    _order.removeRange(keep, _order.length);
    for (final index in removed) {
      _items.removeAt(index);
      for (var i = 0; i < _order.length; i++) {
        if (_order[i] > index) _order[i]--;
      }
    }
  }

  void setShuffle(bool value) {
    if (value == _shuffle) return;
    _shuffle = value;
    if (_items.isEmpty) return;
    final currentItem = _order[_cursor];
    if (value) {
      _order
        ..clear()
        ..add(currentItem)
        ..addAll(_shuffled([
          for (var i = 0; i < _items.length; i++)
            if (i != currentItem) i,
        ]));
      _cursor = 0;
    } else {
      _order
        ..clear()
        ..addAll(List.generate(_items.length, (i) => i));
      _cursor = currentItem;
    }
  }

  void setRepeat(QueueRepeat value) => _repeat = value;

  List<int> _shuffled(List<int> input) {
    final list = [...input];
    for (var i = list.length - 1; i > 0; i--) {
      final j = _random.nextInt(i + 1);
      final t = list[i];
      list[i] = list[j];
      list[j] = t;
    }
    return list;
  }

  // ------------------------------------------------------------ persistence

  Map<String, Object?> toJson() => {
        'ids': [for (final i in _items) i.id],
        'order': List<int>.of(_order),
        'cursor': _cursor,
        'shuffle': _shuffle,
        'repeat': _repeat.name,
        'named': {
          for (final i in _items)
            if (i.directUri != null && i.artist != null)
              i.id: {'artist': i.artist, 'title': i.title, 'album': i.album},
        },
      };

  /// Rebuilds the queue from [json] and the resolved [tracksById]. Entries
  /// whose track no longer exists are dropped (the cursor is repaired).
  void restore(Map<String, Object?> json, Map<String, TrackRow> tracksById) {
    final ids = ((json['ids'] as List?) ?? const []).cast<String>();
    final order = ((json['order'] as List?) ?? const []).cast<int>();
    final cursor = (json['cursor'] as int?) ?? 0;
    _shuffle = (json['shuffle'] as bool?) ?? false;
    _repeat = QueueRepeat.values.asNameMap()[json['repeat']] ?? QueueRepeat.off;

    // Map saved item indexes to surviving ones.
    final survivors = <int, int>{};
    final items = <QueueItem>[];
    for (var i = 0; i < ids.length; i++) {
      final track = tracksById[ids[i]];
      if (track == null) continue;
      survivors[i] = items.length;
      items.add(itemFor(track));
    }
    _items
      ..clear()
      ..addAll(items);
    _order.clear();
    var newCursor = -1;
    for (var pos = 0; pos < order.length; pos++) {
      final mapped = survivors[order[pos]];
      if (mapped == null) continue;
      // The first surviving entry at or after the saved cursor.
      if (newCursor == -1 && pos >= cursor) newCursor = _order.length;
      _order.add(mapped);
    }
    if (newCursor == -1 && _order.isNotEmpty) newCursor = _order.length - 1;
    if (_order.length != _items.length) {
      // Inconsistent snapshot: fall back to the arranged order.
      _order
        ..clear()
        ..addAll(List.generate(_items.length, (i) => i));
      newCursor = _items.isEmpty ? -1 : 0;
    }
    _cursor = _items.isEmpty ? -1 : newCursor.clamp(0, _items.length - 1);
  }
}
